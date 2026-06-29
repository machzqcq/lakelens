"""Admin endpoints for data extraction and ingestion."""

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import BillingUsage, Cluster, Job, ListPrice, QueryHistory, Warehouse, Workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DataSourceStatus(BaseModel):
    source: str = Field(description="'databricks', 'parquet', or 'seed'")
    databricks_host: Optional[str] = Field(None, description="Configured Databricks host")
    databricks_connected: bool = Field(description="Whether Databricks credentials are available")


class TableCounts(BaseModel):
    billing_usage: int
    list_prices: int
    clusters: int
    warehouses: int
    jobs: int


class IngestResult(BaseModel):
    source: str
    tables_ingested: dict[str, int]
    duration_seconds: float


class ExtractionResult(BaseModel):
    tables_extracted: dict[str, int]
    tables_ingested: dict[str, int]
    parquet_saved: bool
    duration_seconds: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=DataSourceStatus)
async def data_source_status():
    """Check the current data source configuration."""
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    profile = os.getenv("DATABRICKS_CONFIG_PROFILE")
    has_creds = bool((host and token) or profile)

    return DataSourceStatus(
        source="databricks" if has_creds else "seed",
        databricks_host=host,
        databricks_connected=has_creds,
    )


@router.get("/table-counts", response_model=TableCounts)
async def table_counts(db: AsyncSession = Depends(get_db)):
    """Get current row counts for all tables."""
    counts = {}
    for model, name in [
        (BillingUsage, "billing_usage"),
        (ListPrice, "list_prices"),
        (Cluster, "clusters"),
        (Warehouse, "warehouses"),
        (Job, "jobs"),
    ]:
        result = await db.execute(select(func.count()).select_from(model))
        counts[name] = result.scalar() or 0
    return TableCounts(**counts)


@router.post("/extract", response_model=ExtractionResult)
async def extract_from_databricks(
    mode: str = Query("full", description="'full' (replace tables) or 'incremental' (append new rows)"),
    start_date: str = Query("2024-01-01", description="Start date YYYY-MM-DD (full mode) or fallback when no cursor (incremental)"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD (default: today)"),
    save_parquet: bool = Query(True, description="Also save extracted data as parquet"),
    groups: Optional[list[str]] = Query(
        None,
        description=(
            "Subset of extraction groups to refresh: 'billing', 'compute', "
            "'query_history', 'meta', 'lineage'. Pass repeated (e.g. ?groups=billing&groups=meta). "
            "Defaults to all groups."
        ),
    ),
    table_lineage_days_back: int = Query(
        14, ge=1, le=365,
        description=(
            "Lookback (days) for system.access.table_lineage. Default 2 weeks. "
            "Ignored when 'lineage' is not in the selected groups."
        ),
    ),
    column_lineage_days_back: int = Query(
        7, ge=1, le=365,
        description=(
            "Lookback (days) for system.access.column_lineage — typically much "
            "higher volume than table_lineage. Default 1 week."
        ),
    ),
    audit_events_days_back: int = Query(
        3, ge=1, le=365,
        description="Lookback (days) for system.access.audit. Default 3 — audit is high-cardinality.",
    ),
    assistant_events_days_back: int = Query(
        30, ge=1, le=365,
        description="Lookback (days) for system.access.assistant_events. Default 30 — low volume.",
    ),
    node_timeline_days_back: int = Query(
        3, ge=1, le=365,
        description="Lookback (days) for system.compute.node_timeline. Default 3 — per-minute-per-instance, heaviest compute table.",
    ),
    warehouse_events_days_back: int = Query(
        30, ge=1, le=365,
        description="Lookback (days) for system.compute.warehouse_events. Default 30 — modest event volume.",
    ),
    instance_events_days_back: int = Query(
        14, ge=1, le=365,
        description="Lookback (days) for system.compute.node_events (instance_events). Default 14 — modest event volume.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Proxy extraction to the dedicated extractor service, then ingest the
    just-written parquet snapshots into Postgres.

    Modes:
      * `full` — overwrites the data_origin='real' partition of every table
        in the selected groups. Tables outside the selected groups are NOT
        touched (their previous parquet snapshot stays in place; ingest
        only reads what the extractor wrote on this run).
      * `incremental` — appends new rows for the selected groups. For
        query_history this passes the per-table cursor in `ingest_cursors`
        to the extractor as the SQL window start; for billing_usage we
        rely on `record_id` upserts; meta is a snapshot so it's fully
        replaced even in incremental mode.

    Groups → tables mapping (see extract.groups.GROUPS):
      * billing       → billing_usage, list_prices
      * compute       → clusters, warehouses, jobs, workspaces
      * query_history → query_history
      * meta          → databricks_meta

    Architecture: this endpoint POSTs to the extractor service
    (``EXTRACTOR_URL``, default ``http://extractor:8000``). The extractor
    has the only databricks-connect install in the stack — the backend's
    pyspark 4.1.1 pinning forbids it from coexisting here.
    """
    import time
    import progress as progress_module

    if mode not in ("full", "incremental"):
        raise HTTPException(status_code=400, detail="mode must be 'full' or 'incremental'")

    from extract.groups import ALL_GROUPS, GROUPS
    selected_groups = [g for g in (groups or list(ALL_GROUPS)) if g in GROUPS]
    if not selected_groups:
        raise HTTPException(
            status_code=400,
            detail=f"groups must contain at least one of: {list(ALL_GROUPS)}",
        )

    # Progress tracker: groups picked + a fixed "calling extractor" phase + a
    # post-ingest phase for each table the extractor wrote. We re-set the total
    # after the extractor returns (we don't know the exact table list until
    # then).
    tracker = await progress_module.start(
        "extract",
        label=f"Extract from Databricks ({mode}, groups: {', '.join(selected_groups)})",
        total_steps=2,
    )

    t0 = time.time()

    # For incremental mode, look up the high-watermark cursor for query_history
    # and pass that as start_date so the extractor's SQL `WHERE start_time >= X`
    # window only grabs new rows. Only relevant when query_history is selected.
    effective_start_date = start_date
    if mode == "incremental" and "query_history" in selected_groups:
        from sqlalchemy import select
        from models import IngestCursor
        cur = (await db.execute(
            select(IngestCursor)
            .where(IngestCursor.table_name == "query_history", IngestCursor.data_origin == "real")
        )).scalar_one_or_none()
        if cur and cur.max_update_time:
            effective_start_date = cur.max_update_time.date().isoformat()
            logger.info("[extract] incremental: starting query_history from cursor %s", effective_start_date)

    # ---- Cancellable work pipeline ----------------------------------------
    # The whole extract+ingest flow runs as a Task so we can cancel the
    # in-flight `httpx.post` when the user clicks Cancel in the UI. A
    # sibling watcher coroutine polls the progress module's cancel flag
    # and cancels the work task when it flips. asyncio.CancelledError
    # cleanly tears down the httpx connection; the extractor service on
    # the far side keeps running but will eventually time out / finish on
    # its own (its Spark session is stopped in its finally block).
    import asyncio
    import httpx
    extractor_url = os.getenv("EXTRACTOR_URL", "http://extractor:8000").rstrip("/")
    payload = {
        "mode": mode,
        "start_date": effective_start_date,
        "end_date": end_date,
        "groups": selected_groups,
        "save_parquet": save_parquet,
        "table_lineage_days_back": table_lineage_days_back,
        "column_lineage_days_back": column_lineage_days_back,
        "audit_events_days_back": audit_events_days_back,
        "assistant_events_days_back": assistant_events_days_back,
        "node_timeline_days_back": node_timeline_days_back,
        "warehouse_events_days_back": warehouse_events_days_back,
        "instance_events_days_back": instance_events_days_back,
    }

    async def _run_extract_and_ingest() -> tuple[list[str], dict[str, int], dict[str, int]]:
        """The actual work — extractor HTTP call + per-table ingest.
        Returns (tables_written, extracted_counts, ingested_counts).
        Raises HTTPException on extractor / ingest errors."""
        await tracker.step(
            f"Calling extractor service at {extractor_url} for groups: {', '.join(selected_groups)}…"
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
                resp = await client.post(f"{extractor_url}/extract", json=payload)
            if resp.status_code >= 400:
                detail = (resp.json().get("detail") if "application/json" in resp.headers.get("content-type", "")
                          else resp.text)
                await tracker.fail(f"Extractor returned {resp.status_code}: {detail}")
                raise HTTPException(status_code=resp.status_code, detail=f"Extractor service: {detail}")
            ext_result = resp.json()
        except HTTPException:
            raise
        except httpx.RequestError as e:
            logger.exception("Extractor service request failed")
            await tracker.fail(f"Could not reach extractor at {extractor_url}: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Could not reach extractor at {extractor_url}: {e}",
            )

        tables_written: list[str] = ext_result.get("tables_written") or []
        extracted_counts: dict[str, int] = ext_result.get("row_counts") or {}
        logger.info(
            "[extract] extractor returned %d tables (%s) in %.1fs from %s",
            len(tables_written),
            ", ".join(tables_written),
            float(ext_result.get("duration_seconds", 0.0) or 0.0),
            ext_result.get("target", "?"),
        )

        # Re-size the tracker now that we know how many tables actually came
        # back. +2 accounts for the initial "calling extractor" step plus
        # the "extractor finished" tick.
        await tracker.set_total(2 + len(tables_written))
        await tracker.step(
            f"Extractor finished. Ingesting {len(tables_written)} table(s): {', '.join(tables_written)}…"
        )

        async def _per_table(name: str, n: int) -> None:
            await tracker.step(f"Ingested {name} ({n:,} rows)")

        try:
            from extract.ingest import ingest_from_parquet
            ingested_counts = await ingest_from_parquet(
                db,
                data_dir=os.getenv("DATA_DIR", "data"),
                replace=(mode == "full"),
                data_origin="real",
                tables=tables_written or None,
                progress_cb=_per_table,
            )
        except asyncio.CancelledError:
            # Re-raise so the outer task-cancel handler runs.
            raise
        except Exception as e:
            logger.exception("Ingestion failed")
            await tracker.fail(f"Ingestion failed: {e}")
            raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")

        return tables_written, extracted_counts, ingested_counts

    async def _cancel_watcher(work: asyncio.Task) -> None:
        """Poll the progress cancel flag every 0.5s; cancel the work task
        when it flips. Exits silently when the work task finishes first."""
        try:
            while not work.done():
                if progress_module.is_cancel_requested("extract"):
                    work.cancel()
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    work_task = asyncio.create_task(_run_extract_and_ingest())
    watcher_task = asyncio.create_task(_cancel_watcher(work_task))
    try:
        tables_written, extracted_counts, ingested_counts = await work_task
    except asyncio.CancelledError:
        # User pressed Cancel — finalize the progress entry and return a
        # 499-style response (Starlette accepts arbitrary status codes).
        await tracker.cancelled("Cancelled by user. The extractor may still be finishing its current step.")
        raise HTTPException(status_code=499, detail="Extract cancelled by user")
    finally:
        if not watcher_task.done():
            watcher_task.cancel()
            try:
                await watcher_task
            except (asyncio.CancelledError, Exception):
                pass

    duration = round(time.time() - t0, 2)
    await tracker.finish(summary={
        "tables_ingested": ingested_counts,
        "duration_seconds": duration,
    })
    return ExtractionResult(
        tables_extracted=extracted_counts,
        tables_ingested=ingested_counts,
        parquet_saved=save_parquet,
        duration_seconds=duration,
    )


@router.post("/ingest-parquet", response_model=IngestResult)
async def ingest_from_parquet_files(
    data_dir: str = Query("data", description="Directory containing parquet files"),
    replace: bool = Query(False, description="Replace existing data (True) or append (False)"),
    db: AsyncSession = Depends(get_db),
):
    """Ingest data from parquet files on disk into Postgres.

    Useful for loading pre-extracted data without a live Databricks connection.
    Looks for files matching: billing_usage_*.parquet, list_prices_*.parquet, etc.
    """
    import time
    import progress as progress_module

    t0 = time.time()
    tracker = await progress_module.start(
        "ingest-parquet",
        label="Load Real Data (Parquet)",
        total_steps=1,  # set conservatively; the callback advances steps
    )
    await tracker.message(f"Scanning {data_dir} for parquet files…")

    async def _per_table(name: str, n: int) -> None:
        await tracker.step(f"Ingested {name} ({n:,} rows)")

    try:
        from extract.ingest import ingest_from_parquet

        counts = await ingest_from_parquet(
            db, data_dir=data_dir, replace=replace, data_origin="real",
            progress_cb=_per_table,
        )
    except Exception as e:
        logger.exception("Parquet ingestion failed")
        await tracker.fail(str(e))
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")

    duration = round(time.time() - t0, 2)
    await tracker.finish(summary={"tables_ingested": counts, "duration_seconds": duration})
    return IngestResult(
        source="parquet",
        tables_ingested=counts,
        duration_seconds=duration,
    )


@router.post("/clear-data", response_model=TableCounts)
async def clear_all_data(
    db: AsyncSession = Depends(get_db),
):
    """Delete all data from all tables. Used before switching data sources."""
    from sqlalchemy import delete as sa_delete

    for model in [
        BillingUsage, ListPrice, Cluster, Warehouse, Job,
        QueryHistory, Workspace,
    ]:
        await db.execute(sa_delete(model))
    await db.commit()
    logger.info("All tables cleared.")
    return TableCounts(billing_usage=0, list_prices=0, clusters=0, warehouses=0, jobs=0)


@router.post("/seed-demo", response_model=IngestResult)
async def seed_demo_data(
    replace: bool = Query(True, description="Replace existing DEMO rows (no effect on real data)"),
    db: AsyncSession = Depends(get_db),
):
    """Load demo data from `demo_*.parquet` files. ONLY touches `data_origin='demo'` rows.

    The demo snapshot is produced by `scripts/simulate_demo_data.py`. Real
    data (`data_origin='real'`) is never affected. If you want a clean demo
    set, call this with `replace=true` (the default).
    """
    import time
    from pathlib import Path
    import progress as progress_module

    t0 = time.time()

    data_dir = Path("data")
    demo_files = list(data_dir.glob("demo_billing_usage_*.parquet"))
    if not demo_files:
        raise HTTPException(
            status_code=404,
            detail=(
                "No demo_*.parquet files found in data/. "
                "Generate them first by running: "
                "python scripts/simulate_demo_data.py"
            ),
        )

    tracker = await progress_module.start(
        "seed-demo", label="Load Demo Data", total_steps=1,
    )
    await tracker.message("Scanning data/ for demo_*.parquet files…")

    async def _per_table(name: str, n: int) -> None:
        await tracker.step(f"Ingested demo {name} ({n:,} rows)")

    try:
        from extract.ingest import ingest_from_parquet
        counts = await ingest_from_parquet(
            db, data_dir="data", replace=replace, file_prefix="demo_",
            data_origin="demo",
            progress_cb=_per_table,
        )
    except Exception as e:
        logger.exception("Demo parquet ingestion failed")
        await tracker.fail(str(e))
        raise HTTPException(status_code=500, detail=f"Demo load failed: {e}")

    duration = round(time.time() - t0, 2)
    await tracker.finish(summary={"tables_ingested": counts, "duration_seconds": duration})
    return IngestResult(
        source="demo-parquet",
        tables_ingested=counts,
        duration_seconds=duration,
    )


class EngineState(BaseModel):
    engine: str  # 'duckdb' | 'spark'
    # Only meaningful when engine='spark'. 'jdbc_views' = base PG tables
    # exposed as session temp views; 'materialized' = base tables copied
    # into spark_catalog.default as managed Delta tables.
    spark_mode: Optional[str] = None  # 'jdbc_views' | 'materialized' | None


@router.get("/engine", response_model=EngineState)
async def get_engine_endpoint(db: AsyncSession = Depends(get_db)):
    """Return the current Query Intel engine choice + Spark sub-mode."""
    from engine_config import get_engine, get_spark_mode

    engine = await get_engine(db)
    mode = await get_spark_mode(db) if engine == "spark" else None
    return EngineState(engine=engine, spark_mode=mode)


@router.patch("/engine", response_model=EngineState)
async def set_engine_endpoint(
    body: EngineState,
    db: AsyncSession = Depends(get_db),
):
    """Switch the Query Intel engine (and optionally the Spark sub-mode).

    Affects the next Extract / Transform run and every subsequent read.
    """
    from engine_config import set_engine, set_spark_mode

    try:
        engine = await set_engine(db, body.engine)  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    mode: Optional[str] = None
    if engine == "spark" and body.spark_mode:
        try:
            mode = await set_spark_mode(db, body.spark_mode)  # type: ignore[arg-type]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # Bring the live Spark session in line — drop temp views or
        # re-register them depending on the new mode. Safe to call even
        # if Spark Connect is unreachable (it's a no-op then).
        try:
            from spark_session import apply_spark_mode
            apply_spark_mode(mode)
        except Exception as e:  # noqa: BLE001
            logger.warning("apply_spark_mode failed (non-fatal): %s", e)
    elif engine == "spark":
        # Engine changed to spark but mode not explicitly set — keep prior
        # value (or default if absent) so the response is always populated.
        from engine_config import get_spark_mode
        mode = await get_spark_mode(db)
    return EngineState(engine=engine, spark_mode=mode)


class MaterializeResult(BaseModel):
    counts: dict[str, int]   # table_name → row count (or -1 if failed)
    duration_seconds: float


@router.post("/materialize-postgres-to-spark", response_model=MaterializeResult)
async def materialize_postgres_to_spark_endpoint(db: AsyncSession = Depends(get_db)):
    """Copy every Postgres-resident base table into spark_catalog.default
    as a managed Delta table. One-time setup for the `materialized` Spark
    sub-mode. Idempotent — re-runs overwrite in place.

    Publishes progress to the live tracker so the Data Management UI can
    render a card while this is running. May take a few minutes for
    `table_lineage` / `column_lineage` partitions of any real size.
    """
    import asyncio
    import time
    import progress as progress_module

    tracker = await progress_module.start(
        "materialize-postgres",
        label="Materialize Postgres → Spark warehouse",
        total_steps=0,  # set after we know the table list
    )

    t0 = time.time()
    counts: dict[str, int] = {}

    try:
        # Spark calls are blocking — run on a worker thread so we don't
        # peg the event loop. The progress callback is async-safe via
        # asyncio.run_coroutine_threadsafe-style schedule below.
        loop = asyncio.get_running_loop()

        def _async_step(table: str, rows: int) -> None:
            asyncio.run_coroutine_threadsafe(
                tracker.step(f"Materialised {table} ({rows:,} rows)"), loop,
            )

        from spark_session import materialize_postgres_tables, _BASE_TABLES
        await tracker.set_total(len(_BASE_TABLES) + 1)
        await tracker.step("Reading Postgres schemas and starting Spark write…")
        counts = await asyncio.to_thread(
            materialize_postgres_tables, _async_step,
        )

        # Now persist the mode flip so future reads use the catalog tables.
        from engine_config import set_spark_mode
        await set_spark_mode(db, "materialized")

        duration = round(time.time() - t0, 2)
        await tracker.finish(summary={"counts": counts, "duration_seconds": duration})
        return MaterializeResult(counts=counts, duration_seconds=duration)
    except Exception as e:  # noqa: BLE001
        await tracker.fail(str(e))
        logger.exception("Materialization failed")
        raise HTTPException(status_code=500, detail=f"Materialization failed: {e}")


class QueryIntelResult(BaseModel):
    source_file: str
    rows_processed: int
    statements_inserted: int
    tables_extracted: int
    columns_extracted: int
    tags_extracted: int
    params_extracted: int
    errors_extracted: int
    parse_failures: int
    duration_seconds: float


@router.post("/extract-query-intel", response_model=QueryIntelResult)
async def extract_query_intel_endpoint(
    use_demo: bool = Query(True, description="True = read demo_query_history_*.parquet"),
    db: AsyncSession = Depends(get_db),
):
    """Run the Query Intel ETL: parse statement_text with sqlglot, flatten
    nested structs, derive metrics, and bulk-rebuild the qi_* tables.

    Idempotent — re-run any time. Replaces all qi_* rows.
    """
    import progress as progress_module
    kind = f"query-intel-{'demo' if use_demo else 'real'}"
    tracker = await progress_module.start(
        kind,
        label=f"Query Profiler ETL ({'demo' if use_demo else 'real'})",
        total_steps=3,
    )
    await tracker.step("Reading query_history parquet…")
    try:
        from extract.query_intel import extract_query_intel

        prefix = "demo_" if use_demo else ""
        await tracker.step("Parsing statement_text with sqlglot and writing qi_* tables…")
        result = await extract_query_intel(db, data_dir="data", file_prefix=prefix)
    except FileNotFoundError as e:
        await tracker.fail(str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("Query Intel extraction failed")
        await tracker.fail(str(e))
        raise HTTPException(status_code=500, detail=f"Query Intel extraction failed: {e}")

    await tracker.step(
        f"{result.get('statements_inserted', 0):,} statements · "
        f"{result.get('tables_extracted', 0):,} table refs · "
        f"{result.get('columns_extracted', 0):,} column refs"
    )
    await tracker.finish(summary={"duration_seconds": result.get("duration_seconds")})
    return QueryIntelResult(**result)


class LineageRollupResult(BaseModel):
    data_origin: str
    rollup_rows:   int
    table_edges:   int
    column_edges:  int
    direct_edges:  int
    indirect_edges:int
    distinct_entities: int
    last_event:    Optional[str] = None
    duration_seconds: float


@router.post("/transform-lineage", response_model=LineageRollupResult)
async def transform_lineage_endpoint(
    use_demo: bool = Query(False, description="True = compute rollups over the demo partition; False = real."),
    db: AsyncSession = Depends(get_db),
):
    """Rebuild `lineage_rollups` for one `data_origin` partition.

    Aggregates table_lineage edges into one row per (data_origin, full_name)
    with edges-in / edges-out / direct / indirect counts and last-event
    timestamps. The Lineage dashboards read from this cache for KPI tiles
    so a 10M-row table_lineage doesn't get re-aggregated on every page load.
    """
    import time
    from datetime import datetime
    from sqlalchemy import case, delete, func, select, distinct
    from models import TableLineage, ColumnLineage, LineageRollup
    import progress as progress_module

    origin = "demo" if use_demo else "real"
    kind = f"transform-lineage-{origin}"
    tracker = await progress_module.start(
        kind,
        label=f"Lineage rollups ({origin})",
        total_steps=5,
    )
    t0 = time.time()

    # 1. Wipe the existing rollup partition.
    await tracker.step("Wiping previous lineage_rollups partition…")
    await db.execute(delete(LineageRollup).where(LineageRollup.data_origin == origin))
    await db.flush()

    # Portable boolean→int expression — sum(case when direct then 1 else 0).
    direct_int = case((TableLineage.direct_access.is_(True), 1), else_=0)

    # 2. Build per-FQN aggregates by source side and target side. We merge
    #    the two halves in Python; Postgres-portable, no exotic windowing.
    out_stmt = select(
        TableLineage.source_table_full_name.label("fn"),
        func.count().label("edges_out"),
        func.count(distinct(TableLineage.target_table_full_name)).label("dist_down"),
        func.count(distinct(TableLineage.entity_id)).label("dist_ent"),
        func.sum(direct_int).label("direct"),
        func.max(TableLineage.event_time).label("last_event"),
    ).where(
        TableLineage.data_origin == origin,
        TableLineage.deleted_at.is_(None),
        TableLineage.source_table_full_name.isnot(None),
    ).group_by(TableLineage.source_table_full_name)

    in_stmt = select(
        TableLineage.target_table_full_name.label("fn"),
        func.count().label("edges_in"),
        func.count(distinct(TableLineage.source_table_full_name)).label("dist_up"),
        func.count(distinct(TableLineage.entity_id)).label("dist_ent"),
        func.max(TableLineage.event_time).label("last_event"),
    ).where(
        TableLineage.data_origin == origin,
        TableLineage.deleted_at.is_(None),
        TableLineage.target_table_full_name.isnot(None),
    ).group_by(TableLineage.target_table_full_name)

    await tracker.step("Aggregating source-side edges…")
    out_rows = (await db.execute(out_stmt)).all()
    await tracker.step("Aggregating target-side edges…")
    in_rows = (await db.execute(in_stmt)).all()

    agg: dict[str, dict] = {}
    for r in out_rows:
        d = agg.setdefault(r.fn, {})
        d["edges_out"] = int(r.edges_out)
        d["distinct_downstream"] = int(r.dist_down or 0)
        d["distinct_entities"] = max(d.get("distinct_entities", 0), int(r.dist_ent or 0))
        d["last_event"] = r.last_event
        direct = int(r.direct or 0)
        d["direct_edges"] = direct
        d["indirect_edges"] = max(0, int(r.edges_out) - direct)
    for r in in_rows:
        d = agg.setdefault(r.fn, {})
        d["edges_in"] = int(r.edges_in)
        d["distinct_upstream"] = int(r.dist_up or 0)
        d["distinct_entities"] = max(d.get("distinct_entities", 0), int(r.dist_ent or 0))
        if r.last_event and (d.get("last_event") is None or r.last_event > d["last_event"]):
            d["last_event"] = r.last_event

    # 3. Bulk-insert.
    await tracker.step(f"Building {len(agg):,} rollup rows…")
    now = datetime.utcnow()
    rollups = [
        LineageRollup(
            data_origin=origin,
            full_name=fn,
            edges_in=d.get("edges_in", 0),
            edges_out=d.get("edges_out", 0),
            distinct_upstream=d.get("distinct_upstream", 0),
            distinct_downstream=d.get("distinct_downstream", 0),
            distinct_entities=d.get("distinct_entities", 0),
            direct_edges=d.get("direct_edges", 0),
            indirect_edges=d.get("indirect_edges", 0),
            last_event=d.get("last_event"),
            rebuilt_at=now,
        )
        for fn, d in agg.items()
    ]
    db.add_all(rollups)

    # 4. Headline counters for the response payload.
    total_table = (await db.execute(
        select(func.count()).select_from(TableLineage)
        .where(TableLineage.data_origin == origin, TableLineage.deleted_at.is_(None))
    )).scalar() or 0
    total_col = (await db.execute(
        select(func.count()).select_from(ColumnLineage)
        .where(ColumnLineage.data_origin == origin, ColumnLineage.deleted_at.is_(None))
    )).scalar() or 0
    total_direct = (await db.execute(
        select(func.count()).select_from(TableLineage)
        .where(
            TableLineage.data_origin == origin,
            TableLineage.deleted_at.is_(None),
            TableLineage.direct_access.is_(True),
        )
    )).scalar() or 0
    total_indirect = (await db.execute(
        select(func.count()).select_from(TableLineage)
        .where(
            TableLineage.data_origin == origin,
            TableLineage.deleted_at.is_(None),
            TableLineage.direct_access.is_(False),
        )
    )).scalar() or 0
    distinct_ents = (await db.execute(
        select(func.count(distinct(TableLineage.entity_id)))
        .where(
            TableLineage.data_origin == origin,
            TableLineage.deleted_at.is_(None),
            TableLineage.entity_id.isnot(None),
        )
    )).scalar() or 0
    last_event = (await db.execute(
        select(func.max(TableLineage.event_time))
        .where(TableLineage.data_origin == origin, TableLineage.deleted_at.is_(None))
    )).scalar()

    await db.commit()

    duration_s = round(time.time() - t0, 2)
    await tracker.finish(summary={
        "rollup_rows": len(rollups),
        "table_edges": int(total_table),
        "column_edges": int(total_col),
        "duration_seconds": duration_s,
    })
    return LineageRollupResult(
        data_origin=origin,
        rollup_rows=len(rollups),
        table_edges=int(total_table),
        column_edges=int(total_col),
        direct_edges=int(total_direct),
        indirect_edges=int(total_indirect),
        distinct_entities=int(distinct_ents),
        last_event=str(last_event) if last_event is not None else None,
        duration_seconds=duration_s,
    )
