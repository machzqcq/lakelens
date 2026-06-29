"""Meta Explorer — browse the Databricks Unity Catalog snapshot.

Backs the Meta Explorer UI page. The source data is the `databricks_meta`
table, populated by `extract/meta_extractor.py` via the Databricks SDK.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import ColumnLineage, DatabricksMeta, TableLineage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meta", tags=["meta-explorer"])


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class MetaStats(BaseModel):
    catalogs: int
    databases: int
    tables: int
    columns: int
    last_extract: Optional[str] = None


class CatalogRow(BaseModel):
    catalog: str
    database_count: int
    table_count: int
    column_count: int


class DatabaseRow(BaseModel):
    catalog: str
    database: str
    table_count: int
    column_count: int


class TableRow(BaseModel):
    catalog: str
    database: str
    table_name: str
    table_type: Optional[str] = None
    table_owner: Optional[str] = None
    table_comment: Optional[str] = None
    column_count: int


class ColumnRow(BaseModel):
    col_name: str
    data_type: Optional[str] = None
    comment: Optional[str] = None


class TableDetail(BaseModel):
    catalog: str
    database: str
    table_name: str
    table_type: Optional[str] = None
    table_owner: Optional[str] = None
    table_comment: Optional[str] = None
    columns: list[ColumnRow]


class SearchHit(BaseModel):
    catalog: str
    database: str
    table_name: str
    col_name: Optional[str] = None
    data_type: Optional[str] = None
    table_comment: Optional[str] = None
    matched_in: str  # 'table' | 'column' | 'comment'


# ---------------------------------------------------------------------------
# Helper — common scope filter (data_origin + soft-delete)
# ---------------------------------------------------------------------------

def _scoped(stmt, user: AuthedUser):
    return (
        stmt
        .where(DatabricksMeta.data_origin == user.viewing_data_mode)
        .where(DatabricksMeta.deleted_at.is_(None))
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=MetaStats)
async def stats(user: AuthedUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Single aggregation pass: distinct counts at the right grain.
    row = (await db.execute(
        _scoped(select(
            func.count(distinct(DatabricksMeta.catalog)).label("catalogs"),
            func.count(distinct(
                func.concat(DatabricksMeta.catalog, ".", DatabricksMeta.db_schema)
            )).label("databases"),
            func.count(distinct(
                func.concat(
                    DatabricksMeta.catalog, ".",
                    DatabricksMeta.db_schema, ".",
                    DatabricksMeta.table_name,
                )
            )).label("tables"),
            func.count().label("columns"),
            func.max(DatabricksMeta.as_of).label("last_extract"),
        ), user)
    )).one()
    return MetaStats(
        catalogs=int(row.catalogs or 0),
        databases=int(row.databases or 0),
        tables=int(row.tables or 0),
        columns=int(row.columns or 0),
        last_extract=str(row.last_extract) if row.last_extract else None,
    )


@router.get("/catalogs", response_model=list[CatalogRow])
async def list_catalogs(user: AuthedUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = _scoped(select(
        DatabricksMeta.catalog,
        func.count(distinct(DatabricksMeta.db_schema)).label("database_count"),
        func.count(distinct(
            func.concat(DatabricksMeta.db_schema, ".", DatabricksMeta.table_name)
        )).label("table_count"),
        func.count().label("column_count"),
    ), user).group_by(DatabricksMeta.catalog).order_by(DatabricksMeta.catalog)
    rows = (await db.execute(stmt)).mappings().all()
    return [CatalogRow(**dict(r)) for r in rows]


@router.get("/databases", response_model=list[DatabaseRow])
async def list_databases(
    catalog: str = Query(...),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = _scoped(select(
        DatabricksMeta.catalog,
        DatabricksMeta.db_schema.label("database"),
        func.count(distinct(DatabricksMeta.table_name)).label("table_count"),
        func.count().label("column_count"),
    ), user).where(DatabricksMeta.catalog == catalog).group_by(
        DatabricksMeta.catalog, DatabricksMeta.db_schema
    ).order_by(DatabricksMeta.db_schema)
    rows = (await db.execute(stmt)).mappings().all()
    return [DatabaseRow(**dict(r)) for r in rows]


@router.get("/tables", response_model=list[TableRow])
async def list_tables(
    catalog: str = Query(...),
    database: str = Query(...),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = _scoped(select(
        DatabricksMeta.catalog,
        DatabricksMeta.db_schema.label("database"),
        DatabricksMeta.table_name,
        func.max(DatabricksMeta.table_type).label("table_type"),
        func.max(DatabricksMeta.table_owner).label("table_owner"),
        func.max(DatabricksMeta.table_comment).label("table_comment"),
        func.count().label("column_count"),
    ), user).where(
        DatabricksMeta.catalog == catalog,
        DatabricksMeta.db_schema == database,
    ).group_by(
        DatabricksMeta.catalog, DatabricksMeta.db_schema, DatabricksMeta.table_name,
    ).order_by(DatabricksMeta.table_name)
    rows = (await db.execute(stmt)).mappings().all()
    return [TableRow(**dict(r)) for r in rows]


@router.get("/table-detail", response_model=TableDetail)
async def table_detail(
    catalog: str = Query(...),
    database: str = Query(...),
    table_name: str = Query(...),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = _scoped(select(
        DatabricksMeta.col_name,
        DatabricksMeta.data_type,
        DatabricksMeta.comment,
        DatabricksMeta.table_type,
        DatabricksMeta.table_owner,
        DatabricksMeta.table_comment,
    ), user).where(
        DatabricksMeta.catalog == catalog,
        DatabricksMeta.db_schema == database,
        DatabricksMeta.table_name == table_name,
    )
    rows = (await db.execute(stmt)).mappings().all()
    columns = [
        ColumnRow(col_name=r["col_name"], data_type=r["data_type"], comment=r["comment"])
        for r in rows
    ]
    return TableDetail(
        catalog=catalog, database=database, table_name=table_name,
        table_type=(rows[0]["table_type"] if rows else None),
        table_owner=(rows[0]["table_owner"] if rows else None),
        table_comment=(rows[0]["table_comment"] if rows else None),
        columns=columns,
    )


# ---------------------------------------------------------------------------
# Bulk export — flat rows for CSV/XLSX download from the UI
# ---------------------------------------------------------------------------
#
# Three grains. Each row carries enough parent context to stand on its own:
#   - catalogs: one row per catalog with rollup counts
#   - tables:   one row per (catalog, database, table) — includes catalog/database
#   - columns:  one row per (catalog, database, table, column) — fully qualified
#
# These endpoints intentionally return ALL rows in scope (no pagination); the
# data volume of databricks_meta is modest (tens of thousands of column rows
# even on large workspaces) and an export that silently truncates would mislead.


class ExportTableRow(BaseModel):
    catalog: str
    database: str
    table_name: str
    table_type: Optional[str] = None
    table_owner: Optional[str] = None
    table_comment: Optional[str] = None
    column_count: int


class ExportColumnRow(BaseModel):
    catalog: str
    database: str
    table_name: str
    table_type: Optional[str] = None
    table_owner: Optional[str] = None
    table_comment: Optional[str] = None
    col_name: str
    data_type: Optional[str] = None
    comment: Optional[str] = None


@router.get("/export/catalogs", response_model=list[CatalogRow])
async def export_catalogs(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Same shape as /catalogs; explicit endpoint so the UI has a stable contract for export."""
    stmt = _scoped(select(
        DatabricksMeta.catalog,
        func.count(distinct(DatabricksMeta.db_schema)).label("database_count"),
        func.count(distinct(
            func.concat(DatabricksMeta.db_schema, ".", DatabricksMeta.table_name)
        )).label("table_count"),
        func.count().label("column_count"),
    ), user).group_by(DatabricksMeta.catalog).order_by(DatabricksMeta.catalog)
    rows = (await db.execute(stmt)).mappings().all()
    return [CatalogRow(**dict(r)) for r in rows]


@router.get("/export/tables", response_model=list[ExportTableRow])
async def export_tables(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every table across all catalogs, with catalog+database carried on each row."""
    stmt = _scoped(select(
        DatabricksMeta.catalog,
        DatabricksMeta.db_schema.label("database"),
        DatabricksMeta.table_name,
        func.max(DatabricksMeta.table_type).label("table_type"),
        func.max(DatabricksMeta.table_owner).label("table_owner"),
        func.max(DatabricksMeta.table_comment).label("table_comment"),
        func.count().label("column_count"),
    ), user).group_by(
        DatabricksMeta.catalog, DatabricksMeta.db_schema, DatabricksMeta.table_name,
    ).order_by(
        DatabricksMeta.catalog, DatabricksMeta.db_schema, DatabricksMeta.table_name,
    )
    rows = (await db.execute(stmt)).mappings().all()
    return [ExportTableRow(**dict(r)) for r in rows]


@router.get("/export/columns", response_model=list[ExportColumnRow])
async def export_columns(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every column across all tables, with catalog+database+table on each row."""
    stmt = _scoped(select(
        DatabricksMeta.catalog,
        DatabricksMeta.db_schema.label("database"),
        DatabricksMeta.table_name,
        DatabricksMeta.table_type,
        DatabricksMeta.table_owner,
        DatabricksMeta.table_comment,
        DatabricksMeta.col_name,
        DatabricksMeta.data_type,
        DatabricksMeta.comment,
    ), user).order_by(
        DatabricksMeta.catalog,
        DatabricksMeta.db_schema,
        DatabricksMeta.table_name,
        DatabricksMeta.col_name,
    )
    rows = (await db.execute(stmt)).mappings().all()
    return [ExportColumnRow(**dict(r)) for r in rows]


@router.get("/search", response_model=list[SearchHit])
async def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(50, le=200),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Substring search across table names, column names, and comments."""
    needle = f"%{q.lower()}%"
    stmt = _scoped(select(
        DatabricksMeta.catalog,
        DatabricksMeta.db_schema.label("database"),
        DatabricksMeta.table_name,
        DatabricksMeta.col_name,
        DatabricksMeta.data_type,
        DatabricksMeta.table_comment,
    ), user).where(
        or_(
            func.lower(DatabricksMeta.table_name).like(needle),
            func.lower(DatabricksMeta.col_name).like(needle),
            func.lower(DatabricksMeta.comment).like(needle),
            func.lower(DatabricksMeta.table_comment).like(needle),
        )
    ).limit(limit)
    rows = (await db.execute(stmt)).mappings().all()
    out: list[SearchHit] = []
    for r in rows:
        tn = (r["table_name"] or "").lower()
        cn = (r["col_name"] or "").lower()
        if q.lower() in tn:
            matched = "table"
        elif q.lower() in cn:
            matched = "column"
        else:
            matched = "comment"
        out.append(SearchHit(
            catalog=r["catalog"],
            database=r["database"],
            table_name=r["table_name"],
            col_name=r["col_name"],
            data_type=r["data_type"],
            table_comment=r["table_comment"],
            matched_in=matched,
        ))
    return out


# ---------------------------------------------------------------------------
# Lineage — system.access.table_lineage / column_lineage
# ---------------------------------------------------------------------------
#
# Endpoints intentionally avoid traversing the graph server-side beyond depth=2.
# Each request returns:
#   * the "center" node
#   * its direct upstream neighbours (sources that write to it)
#   * its direct downstream neighbours (targets it writes to)
# The UI handles further expansion by re-requesting with a new center. This
# keeps each response bounded and makes the page snappy even on very dense
# lineage graphs.


class LineageBreakdownEntry(BaseModel):
    label: str
    count: int


class LineageStats(BaseModel):
    # Headline counters.
    table_edges: int
    column_edges: int
    distinct_tables: int
    distinct_columns: int
    distinct_entities: int
    last_event: Optional[str] = None
    # New dimensions surfaced from system.access.* schema.
    direct_edges: int = 0
    indirect_edges: int = 0
    read_only_events: int = 0
    write_only_events: int = 0
    read_write_events: int = 0
    by_entity_type: list[LineageBreakdownEntry] = []   # NOTEBOOK / JOB / PIPELINE / ...
    by_source_type: list[LineageBreakdownEntry] = []   # TABLE / VIEW / MATERIALIZED_VIEW / ...
    by_target_type: list[LineageBreakdownEntry] = []
    column_distinct_tables: int = 0                    # column-level only stat
    column_distinct_entities: int = 0
    column_last_event: Optional[str] = None


class LineageNeighbour(BaseModel):
    full_name: str
    catalog: Optional[str] = None
    database: Optional[str] = None
    table_name: Optional[str] = None
    type: Optional[str] = None
    edge_count: int
    # Top contributing entities (job/notebook) that emit edges between
    # this neighbour and the centre node.
    sample_entities: list[str] = []


class TableLineageGraph(BaseModel):
    center: str
    upstream: list[LineageNeighbour]
    downstream: list[LineageNeighbour]


class ColumnLineageNeighbour(BaseModel):
    full_name: str        # source/target table FQN
    column_name: str
    edge_count: int


class ColumnLineageGraph(BaseModel):
    center_table: str
    center_column: str
    upstream: list[ColumnLineageNeighbour]
    downstream: list[ColumnLineageNeighbour]


class LineageTopEntry(BaseModel):
    """One row in 'most-active tables / entities' rollups."""
    label: str
    edge_count: int


class LineageTops(BaseModel):
    top_sources:    list[LineageTopEntry]   # tables read from most
    top_targets:    list[LineageTopEntry]   # tables written to most
    top_entities:   list[LineageTopEntry]   # jobs/notebooks producing the most edges
    top_columns:    list[LineageTopEntry]   # column-level edge concentration
    orphan_tables:  list[str]               # appear in meta but never as src/tgt
    terminal_tables: list[str]              # appear as target but never as source


class LineageSearchHit(BaseModel):
    full_name: str
    table_edges_in:  int
    table_edges_out: int


def _scoped_lineage(stmt, user: AuthedUser, model):
    return (
        stmt
        .where(model.data_origin == user.viewing_data_mode)
        .where(model.deleted_at.is_(None))
    )


@router.get("/lineage/stats", response_model=LineageStats)
async def lineage_stats(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """High-level rollup for the Lineage landing tiles, including the
    Databricks-native dimensions (direct vs indirect, event class,
    entity_type and source_type breakdowns)."""
    table_count = (await db.execute(
        _scoped_lineage(select(func.count()).select_from(TableLineage), user, TableLineage)
    )).scalar() or 0
    col_count = (await db.execute(
        _scoped_lineage(select(func.count()).select_from(ColumnLineage), user, ColumnLineage)
    )).scalar() or 0
    distinct_tables = (await db.execute(
        _scoped_lineage(
            select(func.count(distinct(
                func.coalesce(TableLineage.source_table_full_name,
                              TableLineage.target_table_full_name)
            ))),
            user, TableLineage,
        )
    )).scalar() or 0
    distinct_columns = (await db.execute(
        _scoped_lineage(
            select(func.count(distinct(
                func.concat(
                    func.coalesce(ColumnLineage.source_table_full_name, ColumnLineage.target_table_full_name),
                    ":",
                    func.coalesce(ColumnLineage.source_column_name,     ColumnLineage.target_column_name),
                )
            ))),
            user, ColumnLineage,
        )
    )).scalar() or 0
    distinct_entities = (await db.execute(
        _scoped_lineage(
            select(func.count(distinct(TableLineage.entity_id))),
            user, TableLineage,
        ).where(TableLineage.entity_id.isnot(None))
    )).scalar() or 0
    last_event = (await db.execute(
        _scoped_lineage(select(func.max(TableLineage.event_time)), user, TableLineage)
    )).scalar()

    # New dimensions: direct/indirect split.
    direct_edges = (await db.execute(
        _scoped_lineage(select(func.count()).select_from(TableLineage), user, TableLineage)
        .where(TableLineage.direct_access.is_(True))
    )).scalar() or 0
    indirect_edges = (await db.execute(
        _scoped_lineage(select(func.count()).select_from(TableLineage), user, TableLineage)
        .where(TableLineage.direct_access.is_(False))
    )).scalar() or 0

    # Event class — derived from source/target nullability.
    read_only = (await db.execute(
        _scoped_lineage(select(func.count()).select_from(TableLineage), user, TableLineage)
        .where(TableLineage.source_table_full_name.isnot(None))
        .where(TableLineage.target_table_full_name.is_(None))
    )).scalar() or 0
    write_only = (await db.execute(
        _scoped_lineage(select(func.count()).select_from(TableLineage), user, TableLineage)
        .where(TableLineage.source_table_full_name.is_(None))
        .where(TableLineage.target_table_full_name.isnot(None))
    )).scalar() or 0
    read_write = (await db.execute(
        _scoped_lineage(select(func.count()).select_from(TableLineage), user, TableLineage)
        .where(TableLineage.source_table_full_name.isnot(None))
        .where(TableLineage.target_table_full_name.isnot(None))
    )).scalar() or 0

    # Breakdowns.
    by_entity = (await db.execute(
        _scoped_lineage(
            select(
                func.coalesce(TableLineage.entity_type, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, TableLineage,
        ).group_by("k").order_by(func.count().desc()).limit(20)
    )).all()
    by_source = (await db.execute(
        _scoped_lineage(
            select(
                func.coalesce(TableLineage.source_type, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, TableLineage,
        ).where(TableLineage.source_type.isnot(None))
         .group_by("k").order_by(func.count().desc()).limit(20)
    )).all()
    by_target = (await db.execute(
        _scoped_lineage(
            select(
                func.coalesce(TableLineage.target_type, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, TableLineage,
        ).where(TableLineage.target_type.isnot(None))
         .group_by("k").order_by(func.count().desc()).limit(20)
    )).all()

    # Column-only stats.
    col_dt = (await db.execute(
        _scoped_lineage(
            select(func.count(distinct(
                func.coalesce(ColumnLineage.source_table_full_name,
                              ColumnLineage.target_table_full_name)
            ))),
            user, ColumnLineage,
        )
    )).scalar() or 0
    col_de = (await db.execute(
        _scoped_lineage(
            select(func.count(distinct(ColumnLineage.entity_id))),
            user, ColumnLineage,
        ).where(ColumnLineage.entity_id.isnot(None))
    )).scalar() or 0
    col_last = (await db.execute(
        _scoped_lineage(select(func.max(ColumnLineage.event_time)), user, ColumnLineage)
    )).scalar()

    return LineageStats(
        table_edges=int(table_count),
        column_edges=int(col_count),
        distinct_tables=int(distinct_tables),
        distinct_columns=int(distinct_columns),
        distinct_entities=int(distinct_entities),
        last_event=str(last_event) if last_event is not None else None,
        direct_edges=int(direct_edges),
        indirect_edges=int(indirect_edges),
        read_only_events=int(read_only),
        write_only_events=int(write_only),
        read_write_events=int(read_write),
        by_entity_type=[LineageBreakdownEntry(label=r.k, count=int(r.c)) for r in by_entity],
        by_source_type=[LineageBreakdownEntry(label=r.k, count=int(r.c)) for r in by_source],
        by_target_type=[LineageBreakdownEntry(label=r.k, count=int(r.c)) for r in by_target],
        column_distinct_tables=int(col_dt),
        column_distinct_entities=int(col_de),
        column_last_event=str(col_last) if col_last is not None else None,
    )


@router.get("/lineage/search", response_model=list[LineageSearchHit])
async def lineage_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find candidate `full_name`s the user can pivot to as the graph centre."""
    needle = f"%{q.lower()}%"
    # Union of distinct sources + distinct targets matching the substring,
    # ranked by total edges touching them.
    src_stmt = _scoped_lineage(
        select(
            TableLineage.source_table_full_name.label("fn"),
            func.count().label("c"),
        ),
        user, TableLineage,
    ).where(
        TableLineage.source_table_full_name.isnot(None),
        func.lower(TableLineage.source_table_full_name).like(needle),
    ).group_by(TableLineage.source_table_full_name)
    tgt_stmt = _scoped_lineage(
        select(
            TableLineage.target_table_full_name.label("fn"),
            func.count().label("c"),
        ),
        user, TableLineage,
    ).where(
        TableLineage.target_table_full_name.isnot(None),
        func.lower(TableLineage.target_table_full_name).like(needle),
    ).group_by(TableLineage.target_table_full_name)

    src_rows = {r.fn: r.c for r in (await db.execute(src_stmt)).all()}
    tgt_rows = {r.fn: r.c for r in (await db.execute(tgt_stmt)).all()}
    fns = sorted(
        set(src_rows) | set(tgt_rows),
        key=lambda fn: -(src_rows.get(fn, 0) + tgt_rows.get(fn, 0)),
    )[:limit]
    return [
        LineageSearchHit(
            full_name=fn,
            table_edges_in=int(tgt_rows.get(fn, 0)),
            table_edges_out=int(src_rows.get(fn, 0)),
        )
        for fn in fns
    ]


@router.get("/lineage/table-graph", response_model=TableLineageGraph)
async def table_graph(
    full_name: str = Query(..., min_length=3),
    limit: int = Query(25, ge=1, le=200),
    direct_only: bool = Query(
        False,
        description="If true, only edges where direct_access=true are counted. "
                    "Direct = the source/target was referenced directly by the "
                    "statement; indirect = surfaced by lineage analysis as a "
                    "transitive dependency.",
    ),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Direct upstream + downstream neighbours of one table (depth = 1)."""
    # Upstream = sources that have `full_name` as their target
    up_stmt = _scoped_lineage(
        select(
            TableLineage.source_table_full_name.label("fn"),
            TableLineage.source_table_catalog,
            TableLineage.source_table_schema,
            TableLineage.source_table_name,
            func.max(TableLineage.source_type).label("type"),
            func.count().label("edges"),
        ),
        user, TableLineage,
    ).where(
        TableLineage.target_table_full_name == full_name,
        TableLineage.source_table_full_name.isnot(None),
    ).group_by(
        TableLineage.source_table_full_name,
        TableLineage.source_table_catalog,
        TableLineage.source_table_schema,
        TableLineage.source_table_name,
    ).order_by(func.count().desc()).limit(limit)

    down_stmt = _scoped_lineage(
        select(
            TableLineage.target_table_full_name.label("fn"),
            TableLineage.target_table_catalog,
            TableLineage.target_table_schema,
            TableLineage.target_table_name,
            func.max(TableLineage.target_type).label("type"),
            func.count().label("edges"),
        ),
        user, TableLineage,
    ).where(
        TableLineage.source_table_full_name == full_name,
        TableLineage.target_table_full_name.isnot(None),
    ).group_by(
        TableLineage.target_table_full_name,
        TableLineage.target_table_catalog,
        TableLineage.target_table_schema,
        TableLineage.target_table_name,
    ).order_by(func.count().desc()).limit(limit)

    if direct_only:
        up_stmt = up_stmt.where(TableLineage.direct_access.is_(True))
        down_stmt = down_stmt.where(TableLineage.direct_access.is_(True))

    up_rows = (await db.execute(up_stmt)).all()
    down_rows = (await db.execute(down_stmt)).all()

    # For each neighbour, sample up to 3 entity labels that produce its edges.
    async def _sample_entities(side: str, neighbour_fn: str) -> list[str]:
        if side == "up":
            ent_stmt = _scoped_lineage(
                select(
                    func.coalesce(TableLineage.entity_type, "?").label("et"),
                    func.coalesce(TableLineage.entity_id, "?").label("eid"),
                    func.count().label("c"),
                ),
                user, TableLineage,
            ).where(
                TableLineage.source_table_full_name == neighbour_fn,
                TableLineage.target_table_full_name == full_name,
            )
        else:
            ent_stmt = _scoped_lineage(
                select(
                    func.coalesce(TableLineage.entity_type, "?").label("et"),
                    func.coalesce(TableLineage.entity_id, "?").label("eid"),
                    func.count().label("c"),
                ),
                user, TableLineage,
            ).where(
                TableLineage.source_table_full_name == full_name,
                TableLineage.target_table_full_name == neighbour_fn,
            )
        ent_stmt = ent_stmt.group_by("et", "eid").order_by(func.count().desc()).limit(3)
        rows = (await db.execute(ent_stmt)).all()
        return [f"{r.et}: {r.eid}" for r in rows]

    upstream = [
        LineageNeighbour(
            full_name=r.fn,
            catalog=r.source_table_catalog,
            database=r.source_table_schema,
            table_name=r.source_table_name,
            type=r.type,
            edge_count=int(r.edges),
            sample_entities=await _sample_entities("up", r.fn),
        )
        for r in up_rows
    ]
    downstream = [
        LineageNeighbour(
            full_name=r.fn,
            catalog=r.target_table_catalog,
            database=r.target_table_schema,
            table_name=r.target_table_name,
            type=r.type,
            edge_count=int(r.edges),
            sample_entities=await _sample_entities("down", r.fn),
        )
        for r in down_rows
    ]
    return TableLineageGraph(center=full_name, upstream=upstream, downstream=downstream)


@router.get("/lineage/column-graph", response_model=ColumnLineageGraph)
async def column_graph(
    full_name: str = Query(..., min_length=3),
    column_name: str = Query(..., min_length=1),
    limit: int = Query(25, ge=1, le=200),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Direct upstream + downstream column edges (depth = 1) for one column."""
    up_stmt = _scoped_lineage(
        select(
            ColumnLineage.source_table_full_name.label("fn"),
            ColumnLineage.source_column_name.label("col"),
            func.count().label("edges"),
        ),
        user, ColumnLineage,
    ).where(
        ColumnLineage.target_table_full_name == full_name,
        ColumnLineage.target_column_name == column_name,
        ColumnLineage.source_table_full_name.isnot(None),
    ).group_by(
        ColumnLineage.source_table_full_name,
        ColumnLineage.source_column_name,
    ).order_by(func.count().desc()).limit(limit)

    down_stmt = _scoped_lineage(
        select(
            ColumnLineage.target_table_full_name.label("fn"),
            ColumnLineage.target_column_name.label("col"),
            func.count().label("edges"),
        ),
        user, ColumnLineage,
    ).where(
        ColumnLineage.source_table_full_name == full_name,
        ColumnLineage.source_column_name == column_name,
        ColumnLineage.target_table_full_name.isnot(None),
    ).group_by(
        ColumnLineage.target_table_full_name,
        ColumnLineage.target_column_name,
    ).order_by(func.count().desc()).limit(limit)

    upstream = [
        ColumnLineageNeighbour(full_name=r.fn, column_name=r.col, edge_count=int(r.edges))
        for r in (await db.execute(up_stmt)).all()
    ]
    downstream = [
        ColumnLineageNeighbour(full_name=r.fn, column_name=r.col, edge_count=int(r.edges))
        for r in (await db.execute(down_stmt)).all()
    ]
    return ColumnLineageGraph(
        center_table=full_name, center_column=column_name,
        upstream=upstream, downstream=downstream,
    )


@router.get("/lineage/tops", response_model=LineageTops)
async def lineage_tops(
    limit: int = Query(15, ge=1, le=100),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Roll-ups used by the Lineage overview tiles.

    - top_sources / top_targets: tables ranked by edges-out / edges-in.
    - top_entities:    jobs / notebooks ranked by total emitted edges.
    - top_columns:     (table, column) pairs ranked by column-edge count.
    - orphan_tables:   present in databricks_meta but never seen in lineage.
    - terminal_tables: appear as a target but never as a source (leaf nodes).
    """
    src_stmt = _scoped_lineage(
        select(TableLineage.source_table_full_name.label("fn"), func.count().label("c")),
        user, TableLineage,
    ).where(TableLineage.source_table_full_name.isnot(None)) \
     .group_by(TableLineage.source_table_full_name) \
     .order_by(func.count().desc()).limit(limit)

    tgt_stmt = _scoped_lineage(
        select(TableLineage.target_table_full_name.label("fn"), func.count().label("c")),
        user, TableLineage,
    ).where(TableLineage.target_table_full_name.isnot(None)) \
     .group_by(TableLineage.target_table_full_name) \
     .order_by(func.count().desc()).limit(limit)

    ent_stmt = _scoped_lineage(
        select(
            func.coalesce(TableLineage.entity_type, "?").label("et"),
            func.coalesce(TableLineage.entity_id, "?").label("eid"),
            func.count().label("c"),
        ),
        user, TableLineage,
    ).where(TableLineage.entity_id.isnot(None)) \
     .group_by("et", "eid") \
     .order_by(func.count().desc()).limit(limit)

    col_stmt = _scoped_lineage(
        select(
            func.concat(
                func.coalesce(ColumnLineage.target_table_full_name, ColumnLineage.source_table_full_name),
                "::",
                func.coalesce(ColumnLineage.target_column_name,     ColumnLineage.source_column_name),
            ).label("label"),
            func.count().label("c"),
        ),
        user, ColumnLineage,
    ).group_by("label").order_by(func.count().desc()).limit(limit)

    src_rows = (await db.execute(src_stmt)).all()
    tgt_rows = (await db.execute(tgt_stmt)).all()
    ent_rows = (await db.execute(ent_stmt)).all()
    col_rows = (await db.execute(col_stmt)).all()

    sources_set = {r.fn for r in src_rows}
    targets_set = {r.fn for r in tgt_rows}
    # Terminal = appears as target somewhere but never as source.
    terminal_stmt = _scoped_lineage(
        select(distinct(TableLineage.target_table_full_name).label("fn")),
        user, TableLineage,
    ).where(TableLineage.target_table_full_name.isnot(None))
    all_targets = {r.fn for r in (await db.execute(terminal_stmt)).all()}
    all_sources_stmt = _scoped_lineage(
        select(distinct(TableLineage.source_table_full_name).label("fn")),
        user, TableLineage,
    ).where(TableLineage.source_table_full_name.isnot(None))
    all_sources = {r.fn for r in (await db.execute(all_sources_stmt)).all()}
    terminal = sorted(all_targets - all_sources)[:limit]

    # Orphan = appears in databricks_meta but never in lineage (either side).
    meta_fn_stmt = _scoped(
        select(distinct(func.concat(
            DatabricksMeta.catalog, ".",
            DatabricksMeta.db_schema, ".",
            DatabricksMeta.table_name,
        )).label("fn")),
        user,
    )
    meta_fns = {r.fn for r in (await db.execute(meta_fn_stmt)).all()}
    orphan = sorted(meta_fns - (all_targets | all_sources))[:limit]

    return LineageTops(
        top_sources=[LineageTopEntry(label=r.fn, edge_count=int(r.c)) for r in src_rows],
        top_targets=[LineageTopEntry(label=r.fn, edge_count=int(r.c)) for r in tgt_rows],
        top_entities=[
            LineageTopEntry(label=f"{r.et}: {r.eid}", edge_count=int(r.c)) for r in ent_rows
        ],
        top_columns=[LineageTopEntry(label=r.label, edge_count=int(r.c)) for r in col_rows],
        orphan_tables=orphan,
        terminal_tables=terminal,
    )


class ColumnLineageTops(BaseModel):
    # Columns that flow OUT to many distinct downstream (table, column) pairs.
    most_fanned_out:  list[LineageTopEntry]
    # Columns that have many distinct upstream (table, column) pairs feeding them.
    most_depended_on: list[LineageTopEntry]
    # Tables ranked by total column edges (source side).
    tables_by_col_edges: list[LineageTopEntry]
    # Entities ranked by column-edge count.
    top_entities: list[LineageTopEntry]


@router.get("/lineage/column-tops", response_model=ColumnLineageTops)
async def lineage_column_tops(
    limit: int = Query(15, ge=1, le=100),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Column-lineage-specific roll-ups for the Column Lineage dashboard."""
    src_label = func.concat(
        ColumnLineage.source_table_full_name, "::", ColumnLineage.source_column_name,
    )
    tgt_label = func.concat(
        ColumnLineage.target_table_full_name, "::", ColumnLineage.target_column_name,
    )

    # Most-fanned-out source column → many distinct (target_table, target_column).
    fan_stmt = _scoped_lineage(
        select(
            src_label.label("label"),
            func.count(distinct(tgt_label)).label("c"),
        ),
        user, ColumnLineage,
    ).where(
        ColumnLineage.source_table_full_name.isnot(None),
        ColumnLineage.source_column_name.isnot(None),
        ColumnLineage.target_table_full_name.isnot(None),
        ColumnLineage.target_column_name.isnot(None),
    ).group_by("label").order_by(func.count(distinct(tgt_label)).desc()).limit(limit)

    # Most-depended-on target column → many distinct upstream columns.
    dep_stmt = _scoped_lineage(
        select(
            tgt_label.label("label"),
            func.count(distinct(src_label)).label("c"),
        ),
        user, ColumnLineage,
    ).where(
        ColumnLineage.source_table_full_name.isnot(None),
        ColumnLineage.source_column_name.isnot(None),
        ColumnLineage.target_table_full_name.isnot(None),
        ColumnLineage.target_column_name.isnot(None),
    ).group_by("label").order_by(func.count(distinct(src_label)).desc()).limit(limit)

    # Tables ranked by total column edges originated (source side).
    tbl_stmt = _scoped_lineage(
        select(ColumnLineage.source_table_full_name.label("fn"), func.count().label("c")),
        user, ColumnLineage,
    ).where(ColumnLineage.source_table_full_name.isnot(None)) \
     .group_by(ColumnLineage.source_table_full_name) \
     .order_by(func.count().desc()).limit(limit)

    ent_stmt = _scoped_lineage(
        select(
            func.coalesce(ColumnLineage.entity_type, "?").label("et"),
            func.coalesce(ColumnLineage.entity_id, "?").label("eid"),
            func.count().label("c"),
        ),
        user, ColumnLineage,
    ).where(ColumnLineage.entity_id.isnot(None)) \
     .group_by("et", "eid") \
     .order_by(func.count().desc()).limit(limit)

    return ColumnLineageTops(
        most_fanned_out=[LineageTopEntry(label=r.label, edge_count=int(r.c))
                         for r in (await db.execute(fan_stmt)).all()],
        most_depended_on=[LineageTopEntry(label=r.label, edge_count=int(r.c))
                          for r in (await db.execute(dep_stmt)).all()],
        tables_by_col_edges=[LineageTopEntry(label=r.fn, edge_count=int(r.c))
                             for r in (await db.execute(tbl_stmt)).all()],
        top_entities=[LineageTopEntry(label=f"{r.et}: {r.eid}", edge_count=int(r.c))
                      for r in (await db.execute(ent_stmt)).all()],
    )
