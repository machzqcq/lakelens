"""
Data ingestion pipeline: loads extracted DataFrames (or parquet files) into Postgres.

Supports both:
  1. Direct ingestion from DataFrames (after live Databricks extraction)
  2. Ingestion from parquet files on disk (offline / pre-extracted data)
"""

import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

import pandas as pd

# Per-table progress callback signature used by Data Management to publish
# step-by-step progress to the UI. `await cb(table_name, rows_inserted)` runs
# after each table's ingest finishes.
ProgressCb = Callable[[str, int], Awaitable[None]]
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    AssistantEvent, AuditEvent,
    BillingUsage, Cluster, ColumnLineage, DatabricksMeta, Job, ListPrice,
    QueryHistory, TableLineage, Warehouse, Workspace,
    NodeTimeline, WarehouseEvent, NodeType, InstanceEvent, InstancePool,
)

logger = logging.getLogger(__name__)

# Maps DataFrame column names to SQLAlchemy model fields.
# Columns present in the DF but absent here are silently dropped.
USAGE_COLUMNS = [
    "account_id", "workspace_id", "record_id", "sku_name", "cloud",
    "usage_start_time", "usage_end_time", "usage_date", "usage_unit",
    "usage_quantity", "billing_origin_product", "usage_type", "record_type",
    "ingestion_date", "cluster_id", "warehouse_id", "instance_pool_id",
    "node_type", "job_id", "run_name", "run_as",
    "jobs_tier", "sql_tier", "dlt_tier", "is_serverless", "is_photon",
    "serving_type", "usage_usd",
]

PRICE_COLUMNS = [
    "account_id", "sku_name", "cloud", "currency_code", "usage_unit",
    "price_start_time", "price_end_time", "default_price", "effective_list_price",
]

CLUSTER_COLUMNS = [
    "account_id", "workspace_id", "cluster_id", "cluster_name", "owned_by",
    "driver_node_type", "worker_node_type", "worker_count",
    "min_autoscale_workers", "max_autoscale_workers", "dbr_version",
    "cluster_source", "data_security_mode", "create_time", "delete_time",
    "change_time",
]

WAREHOUSE_COLUMNS = [
    "account_id", "workspace_id", "warehouse_id", "warehouse_name",
    "warehouse_type", "warehouse_size", "min_clusters", "max_clusters",
    "auto_stop_minutes", "created_by", "change_time", "delete_time",
]

JOB_COLUMNS = [
    "account_id", "workspace_id", "job_id", "name", "creator_id",
    "run_as", "change_time", "delete_time",
]

WORKSPACE_COLUMNS = [
    "workspace_id", "account_id", "workspace_name", "workspace_url",
    "create_time", "status",
]

META_COLUMNS = [
    "catalog", "database", "table", "col_name", "data_type",
    "comment", "table_type", "table_owner", "table_comment", "as_of",
]

# Lineage parquet columns mirror the public Databricks `system.access.*_lineage`
# schemas. Source/target may be NULL for path-style locations.
TABLE_LINEAGE_COLUMNS = [
    "account_id", "metastore_id", "workspace_id",
    "event_time", "event_date", "record_id", "event_id",
    "source_table_full_name", "source_table_catalog", "source_table_schema",
    "source_table_name", "source_type", "source_path",
    "target_table_full_name", "target_table_catalog", "target_table_schema",
    "target_table_name", "target_type", "target_path",
    "created_by", "entity_type", "entity_id", "entity_run_id",
    "entity_metadata", "statement_id", "direct_access",
]

COLUMN_LINEAGE_COLUMNS = [
    "account_id", "metastore_id", "workspace_id",
    "event_time", "event_date", "record_id", "event_id",
    "source_table_full_name", "source_table_catalog", "source_table_schema",
    "source_table_name", "source_column_name", "source_type", "source_path",
    "target_table_full_name", "target_table_catalog", "target_table_schema",
    "target_table_name", "target_column_name", "target_type", "target_path",
    "created_by", "entity_type", "entity_id", "entity_run_id",
    "entity_metadata", "statement_id", "direct_access",
]

AUDIT_COLUMNS = [
    "account_id", "workspace_id", "version", "event_time", "event_date",
    "source_ip_address", "user_agent", "session_id",
    "user_identity", "user_identity_email",
    "service_name", "action_name", "request_id", "request_params",
    "response", "response_status_code", "response_error_message",
    "audit_level", "event_id", "identity_metadata",
]

ASSISTANT_EVENT_COLUMNS = [
    "event_id", "account_id", "workspace_id", "event_time", "event_date",
    "user_agent", "initiated_by",
]

# system.compute.* — node pool / instance telemetry columns. The disk_free
# and event_details / preloaded_spark_versions cols are JSON-ified during
# extract; the loader normalizes them via _to_jsonable below.
NODE_TIMELINE_COLUMNS = [
    "account_id", "workspace_id", "cluster_id", "instance_id",
    "start_time", "end_time", "event_date", "driver", "node_type",
    "cpu_user_percent", "cpu_system_percent", "cpu_wait_percent",
    "mem_used_percent", "mem_swap_percent",
    "network_sent_bytes", "network_received_bytes",
    "disk_free_bytes_per_mount_point",
]

WAREHOUSE_EVENTS_COLUMNS = [
    "account_id", "workspace_id", "warehouse_id",
    "event_type", "cluster_count", "event_time", "event_date",
]

NODE_TYPES_COLUMNS = [
    "account_id", "node_type", "core_count", "memory_mb",
    "gpu_count", "category",
]

INSTANCE_EVENTS_COLUMNS = [
    "account_id", "workspace_id", "cluster_id", "instance_id",
    "instance_pool_id", "event_type", "event_time", "event_date",
    "node_type", "event_details",
]

INSTANCE_POOLS_COLUMNS = [
    "account_id", "workspace_id", "instance_pool_id", "instance_pool_name",
    "node_type", "min_idle_instances", "max_capacity",
    "idle_instance_autotermination_minutes", "enable_elastic_disk",
    "preloaded_spark_versions",
    "create_time", "delete_time", "change_time",
]


QUERY_HISTORY_COLUMNS = [
    "statement_id", "account_id", "workspace_id",
    "executed_by", "executed_by_user_id", "executed_as", "executed_as_user_id",
    "session_id", "execution_status", "compute",
    "statement_text", "statement_type", "error_message",
    "client_application", "client_driver",
    "total_duration_ms", "waiting_for_compute_duration_ms",
    "waiting_at_capacity_duration_ms", "execution_duration_ms",
    "compilation_duration_ms", "total_task_duration_ms",
    "result_fetch_duration_ms",
    "start_time", "end_time", "update_time",
    "read_partitions", "pruned_files", "read_files", "read_rows",
    "produced_rows", "read_bytes", "read_io_cache_percent",
    "from_result_cache", "spilled_local_bytes", "written_bytes",
    "shuffle_read_bytes", "written_rows", "written_files",
    "cache_origin_statement_id", "query_source", "query_parameters",
    "query_tags", "pruned_files_bytes", "read_files_bytes",
]

BATCH_SIZE = 2000


def _safe_columns(df: pd.DataFrame, expected: list[str]) -> pd.DataFrame:
    """Keep only columns that exist in both the DF and the expected list."""
    present = [c for c in expected if c in df.columns]
    return df[present].copy()


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """Replace NaN/NaT with None for clean Postgres insertion.

    asyncpg cannot handle pandas NaT or numpy NaN - they must be Python None.
    """
    # Convert ALL columns to object dtype first to avoid NaT issues
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            # Convert timestamps: keep valid ones as Python datetime, NaT -> None
            df[col] = df[col].apply(lambda x: x.to_pydatetime() if pd.notna(x) else None)
        elif pd.api.types.is_bool_dtype(df[col]):
            df[col] = df[col].apply(lambda x: bool(x) if pd.notna(x) else None)
        elif pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].apply(lambda x: x if pd.notna(x) else None)
        else:
            df[col] = df[col].where(df[col].notna(), None)
    return df


def _sanitize_record(record: dict) -> dict:
    """Ensure no pandas NaT/NaN values survive into asyncpg."""
    return {k: (None if pd.isna(v) else v) if not isinstance(v, (str, bool, int, list, dict)) else v
            for k, v in record.items()}


async def _bulk_insert(
    session: AsyncSession,
    model,
    records: list[dict],
    data_origin: str = "real",
) -> int:
    """Insert records in batches. Stamps `data_origin` on every row so the
    isolation system can filter. Returns count inserted."""
    total = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = [_sanitize_record(r) for r in records[i : i + BATCH_SIZE]]
        for rec in batch:
            rec.setdefault("data_origin", data_origin)
        await session.execute(model.__table__.insert(), batch)
        total += len(batch)
        if total % 10_000 < BATCH_SIZE:
            logger.info("  ... %d records inserted", total)
    return total


async def ingest_list_prices(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest list_prices DataFrame into Postgres scoped to `data_origin`.

    `replace=True` only deletes rows with the matching data_origin — it does
    NOT touch the other partition. Demo and real never cross-pollute.
    """
    logger.info("Ingesting %d list_prices records (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, PRICE_COLUMNS))

    if replace:
        await session.execute(delete(ListPrice).where(ListPrice.data_origin == data_origin))

    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, ListPrice, records, data_origin=data_origin)
    logger.info("Ingested %d list_prices records (origin=%s)", count, data_origin)
    return count


async def ingest_usage(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = False,
    data_origin: str = "real",
) -> int:
    """Ingest billing_usage DataFrame into Postgres scoped to `data_origin`.

    `replace=True` only deletes rows with the matching data_origin — demo and
    real partitions stay isolated. Append mode deduplicates within the same
    partition by record_id.
    """
    logger.info("Ingesting %d usage records (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, USAGE_COLUMNS))

    if replace:
        await session.execute(
            delete(BillingUsage).where(BillingUsage.data_origin == data_origin)
        )
        records = df.to_dict(orient="records")
    else:
        # Deduplicate within the same data_origin partition.
        existing_result = await session.execute(
            select(BillingUsage.record_id)
            .where(BillingUsage.data_origin == data_origin)
        )
        existing_ids = {r[0] for r in existing_result.all()}
        new_df = df[~df["record_id"].isin(existing_ids)]
        logger.info(
            "  %d new records (skipping %d existing in origin=%s)",
            len(new_df), len(df) - len(new_df), data_origin,
        )
        records = new_df.to_dict(orient="records")

    count = await _bulk_insert(session, BillingUsage, records, data_origin=data_origin)
    logger.info("Ingested %d usage records (origin=%s)", count, data_origin)
    return count


async def ingest_clusters(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest clusters DataFrame scoped to `data_origin`."""
    logger.info("Ingesting %d cluster records (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, CLUSTER_COLUMNS))
    if replace:
        await session.execute(delete(Cluster).where(Cluster.data_origin == data_origin))
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, Cluster, records, data_origin=data_origin)
    logger.info("Ingested %d cluster records (origin=%s)", count, data_origin)
    return count


async def ingest_warehouses(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest warehouses DataFrame scoped to `data_origin`."""
    logger.info("Ingesting %d warehouse records (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, WAREHOUSE_COLUMNS))
    if replace:
        await session.execute(delete(Warehouse).where(Warehouse.data_origin == data_origin))
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, Warehouse, records, data_origin=data_origin)
    logger.info("Ingested %d warehouse records (origin=%s)", count, data_origin)
    return count


async def ingest_jobs(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest jobs DataFrame scoped to `data_origin`."""
    logger.info("Ingesting %d job records (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, JOB_COLUMNS))
    if replace:
        await session.execute(delete(Job).where(Job.data_origin == data_origin))
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, Job, records, data_origin=data_origin)
    logger.info("Ingested %d job records (origin=%s)", count, data_origin)
    return count


async def ingest_workspaces(
    session: AsyncSession,
    df: pd.DataFrame,
    data_origin: str = "real",
) -> int:
    """Upsert workspaces from the extracted DataFrame.

    Uses Postgres ON CONFLICT to keep existing names if a re-extract returns
    a NULL — never overwrites a real name with NULL. Stamps data_origin on
    newly-inserted rows (existing rows keep their own origin).
    """
    if df is None or df.empty:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    logger.info("Upserting %d workspace records (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, WORKSPACE_COLUMNS))
    records = [_sanitize_record(r) for r in df.to_dict(orient="records")]
    # cast ids to string for consistency with billing_usage.workspace_id
    for r in records:
        if r.get("workspace_id") is not None:
            r["workspace_id"] = str(r["workspace_id"])
        r.setdefault("data_origin", data_origin)

    stmt = pg_insert(Workspace).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Workspace.workspace_id],
        set_={
            "account_id":     func.coalesce(stmt.excluded.account_id,     Workspace.account_id),
            "workspace_name": func.coalesce(stmt.excluded.workspace_name, Workspace.workspace_name),
            "workspace_url":  func.coalesce(stmt.excluded.workspace_url,  Workspace.workspace_url),
            "create_time":    func.coalesce(stmt.excluded.create_time,    Workspace.create_time),
            "status":         func.coalesce(stmt.excluded.status,         Workspace.status),
        },
    )
    await session.execute(stmt)
    logger.info("Upserted %d workspace records (origin=%s)", len(records), data_origin)
    return len(records)


def _to_jsonable(v):
    """Coerce Spark Row / numpy array / pandas NA into plain JSON-friendly Python.

    Recurses through dicts and lists so nested numpy types (e.g. an
    np.ndarray of strings inside query_source) are flattened. Used by
    ingest_query_history for the STRUCT/MAP columns that round-trip
    through parquet — pyarrow preserves the structure but not the
    Python-native types.
    """
    import numpy as np

    if v is None:
        return None
    # pandas NA / NaT
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "asDict"):
        return _to_jsonable(v.asDict(recursive=True))
    if isinstance(v, np.ndarray):
        return [_to_jsonable(x) for x in v.tolist()]
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _to_jsonable(val) for k, val in v.items()}
    if isinstance(v, (np.generic,)):
        return v.item()
    return v


_QH_JSON_COLUMNS = ("compute", "query_source", "query_parameters", "query_tags")


async def ingest_query_history(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = False,
    data_origin: str = "real",
) -> int:
    """Ingest system.query.history rows scoped to `data_origin`.

    Deduplicates on statement_id (PK) within the same data_origin. `replace=True`
    only deletes rows matching `data_origin` — demo and real partitions stay
    isolated.
    """
    if df is None or df.empty:
        return 0
    logger.info("Ingesting %d query_history records (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, QUERY_HISTORY_COLUMNS))

    for col in _QH_JSON_COLUMNS:
        if col in df.columns:
            df[col] = df[col].map(_to_jsonable)

    if replace:
        await session.execute(
            delete(QueryHistory).where(QueryHistory.data_origin == data_origin)
        )
        records = df.to_dict(orient="records")
    else:
        existing_result = await session.execute(
            select(QueryHistory.statement_id).where(QueryHistory.data_origin == data_origin)
        )
        existing_ids = {r[0] for r in existing_result.all()}
        new_df = df[~df["statement_id"].isin(existing_ids)]
        logger.info(
            "  %d new query_history records (skipping %d existing in origin=%s)",
            len(new_df), len(df) - len(new_df), data_origin,
        )
        records = new_df.to_dict(orient="records")

    count = await _bulk_insert(session, QueryHistory, records, data_origin=data_origin)
    logger.info("Ingested %d query_history records (origin=%s)", count, data_origin)
    return count


async def ingest_meta(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest the Databricks meta snapshot into Postgres scoped to `data_origin`.

    Source columns: catalog, database, table, col_name, data_type, comment,
    table_type, table_owner, table_comment, as_of. The model maps `table` →
    column `table_name` (so we rewrite that key); `database` is already the
    correct column name (the Python attribute alias is `db_schema`, but
    `_bulk_insert` calls `model.__table__.insert()` which keys on column
    names) so we pass it through unchanged.
    """
    if df is None or df.empty:
        logger.info("Meta DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d meta rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, META_COLUMNS))

    # Snapshots fully replace the partition — meta is a "current state"
    # capture, not a stream. Append mode is supported but typically the
    # caller passes replace=True.
    if replace:
        await session.execute(
            delete(DatabricksMeta).where(DatabricksMeta.data_origin == data_origin)
        )

    raw_records = df.to_dict(orient="records")
    records: list[dict] = []
    for r in raw_records:
        rec = dict(r)
        # Source parquet column is named `table` (from the SQL alias); the
        # model column is `table_name`. Rename it. The other model attribute
        # `db_schema` is a Python alias whose underlying column is literally
        # `database` — and `_bulk_insert` goes through
        # `model.__table__.insert()`, which keys on COLUMN names not
        # attribute names. So we keep the `database` key as-is; renaming it
        # to `db_schema` would silently drop the value and trigger
        # `null value in column "database" violates not-null constraint`.
        if "table" in rec:
            rec["table_name"] = rec.pop("table")
        records.append(rec)

    count = await _bulk_insert(session, DatabricksMeta, records, data_origin=data_origin)
    logger.info("Ingested %d meta rows (origin=%s)", count, data_origin)
    return count


async def ingest_table_lineage(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest system.access.table_lineage rows scoped to `data_origin`.

    Lineage is a "current snapshot of recent activity" — we always
    full-replace the partition rather than dedupe by record_id (the upstream
    sliding window means the same record_id won't reappear anyway).
    `entity_metadata` is normalized to a JSON dict before insert.
    """
    if df is None or df.empty:
        logger.info("table_lineage DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d table_lineage rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, TABLE_LINEAGE_COLUMNS))
    if "entity_metadata" in df.columns:
        df["entity_metadata"] = df["entity_metadata"].map(_to_jsonable)
    if replace:
        await session.execute(
            delete(TableLineage).where(TableLineage.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, TableLineage, records, data_origin=data_origin)
    logger.info("Ingested %d table_lineage rows (origin=%s)", count, data_origin)
    return count


async def ingest_column_lineage(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest system.access.column_lineage rows scoped to `data_origin`.

    Note: Databricks' column_lineage does NOT include events without a source
    (e.g., `INSERT VALUES`), so write-only edges that exist in table_lineage
    will be absent from this partition.
    """
    if df is None or df.empty:
        logger.info("column_lineage DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d column_lineage rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, COLUMN_LINEAGE_COLUMNS))
    if "entity_metadata" in df.columns:
        df["entity_metadata"] = df["entity_metadata"].map(_to_jsonable)
    if replace:
        await session.execute(
            delete(ColumnLineage).where(ColumnLineage.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, ColumnLineage, records, data_origin=data_origin)
    logger.info("Ingested %d column_lineage rows (origin=%s)", count, data_origin)
    return count


async def ingest_audit(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest system.access.audit rows scoped to `data_origin`.

    Full-replace within the partition — audit volume rolls into Postgres on
    every extract and is rebuilt fresh.
    """
    if df is None or df.empty:
        logger.info("audit DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d audit rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, AUDIT_COLUMNS))
    for col in ("user_identity", "request_params", "response", "identity_metadata"):
        if col in df.columns:
            df[col] = df[col].map(_to_jsonable)
    if replace:
        await session.execute(
            delete(AuditEvent).where(AuditEvent.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, AuditEvent, records, data_origin=data_origin)
    logger.info("Ingested %d audit rows (origin=%s)", count, data_origin)
    return count


async def ingest_assistant_events(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    """Ingest system.access.assistant_events rows scoped to `data_origin`."""
    if df is None or df.empty:
        logger.info("assistant_events DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d assistant_events rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, ASSISTANT_EVENT_COLUMNS))
    if replace:
        await session.execute(
            delete(AssistantEvent).where(AssistantEvent.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, AssistantEvent, records, data_origin=data_origin)
    logger.info("Ingested %d assistant_events rows (origin=%s)", count, data_origin)
    return count


# ---------------------------------------------------------------------------
# system.compute.* ingest — node pool / instance telemetry. All full-replace
# on the partition; the per-table date window is enforced upstream by the
# extractor's `node_pool_days_back` knob.
# ---------------------------------------------------------------------------

async def ingest_node_timeline(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    if df is None or df.empty:
        logger.info("node_timeline DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d node_timeline rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, NODE_TIMELINE_COLUMNS))
    if "disk_free_bytes_per_mount_point" in df.columns:
        df["disk_free_bytes_per_mount_point"] = df["disk_free_bytes_per_mount_point"].map(_to_jsonable)
    if replace:
        await session.execute(
            delete(NodeTimeline).where(NodeTimeline.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, NodeTimeline, records, data_origin=data_origin)
    logger.info("Ingested %d node_timeline rows (origin=%s)", count, data_origin)
    return count


async def ingest_warehouse_events(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    if df is None or df.empty:
        logger.info("warehouse_events DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d warehouse_events rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, WAREHOUSE_EVENTS_COLUMNS))
    if replace:
        await session.execute(
            delete(WarehouseEvent).where(WarehouseEvent.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, WarehouseEvent, records, data_origin=data_origin)
    logger.info("Ingested %d warehouse_events rows (origin=%s)", count, data_origin)
    return count


async def ingest_node_types(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    if df is None or df.empty:
        logger.info("node_types DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d node_types rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, NODE_TYPES_COLUMNS))
    if replace:
        await session.execute(
            delete(NodeType).where(NodeType.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, NodeType, records, data_origin=data_origin)
    logger.info("Ingested %d node_types rows (origin=%s)", count, data_origin)
    return count


async def ingest_instance_events(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    if df is None or df.empty:
        logger.info("instance_events DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d instance_events rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, INSTANCE_EVENTS_COLUMNS))
    if "event_details" in df.columns:
        df["event_details"] = df["event_details"].map(_to_jsonable)
    if replace:
        await session.execute(
            delete(InstanceEvent).where(InstanceEvent.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, InstanceEvent, records, data_origin=data_origin)
    logger.info("Ingested %d instance_events rows (origin=%s)", count, data_origin)
    return count


async def ingest_instance_pools(
    session: AsyncSession,
    df: pd.DataFrame,
    replace: bool = True,
    data_origin: str = "real",
) -> int:
    if df is None or df.empty:
        logger.info("instance_pools DataFrame empty — skipping ingest")
        return 0
    logger.info("Ingesting %d instance_pools rows (origin=%s) ...", len(df), data_origin)
    df = _clean_df(_safe_columns(df, INSTANCE_POOLS_COLUMNS))
    if "preloaded_spark_versions" in df.columns:
        df["preloaded_spark_versions"] = df["preloaded_spark_versions"].map(_to_jsonable)
    if replace:
        await session.execute(
            delete(InstancePool).where(InstancePool.data_origin == data_origin)
        )
    records = df.to_dict(orient="records")
    count = await _bulk_insert(session, InstancePool, records, data_origin=data_origin)
    logger.info("Ingested %d instance_pools rows (origin=%s)", count, data_origin)
    return count


async def backfill_workspace_stubs(session: AsyncSession) -> int:
    """Insert stub rows (name=NULL) for every workspace_id present in
    billing_usage that doesn't yet have a Workspace row. This way the UI
    always has *something* to look up, and admins can fill in the name
    later via the Database Explorer."""
    rows = (await session.execute(
        select(BillingUsage.workspace_id)
        .distinct()
        .where(BillingUsage.workspace_id.isnot(None))
    )).all()
    seen_ids = {str(r[0]) for r in rows}
    if not seen_ids:
        return 0
    existing = {
        r[0] for r in (await session.execute(select(Workspace.workspace_id))).all()
    }
    missing = sorted(seen_ids - existing)
    if not missing:
        return 0
    session.add_all([Workspace(workspace_id=wid) for wid in missing])
    logger.info("Backfilled %d workspace stub rows (name=NULL)", len(missing))
    return len(missing)


async def ingest_all(
    session: AsyncSession,
    dataframes: dict[str, pd.DataFrame],
    replace: bool = False,
    data_origin: str = "real",
    progress_cb: Optional["ProgressCb"] = None,
) -> dict[str, int]:
    """Ingest all extracted DataFrames into Postgres scoped to `data_origin`.

    `replace=True` only deletes rows matching the same data_origin — demo and
    real partitions never cross-pollute.

    `progress_cb`, when provided, is called with (table_name, rows_inserted)
    after each table finishes ingesting. Used by Data Management to publish
    per-table progress to the UI.
    """
    counts: dict[str, int] = {}

    async def _track(name: str, n: int) -> None:
        if progress_cb is not None:
            try:
                await progress_cb(name, int(n))
            except Exception:
                logger.warning("progress_cb failed for %s", name, exc_info=True)

    if "list_prices" in dataframes:
        counts["list_prices"] = await ingest_list_prices(
            session, dataframes["list_prices"], replace=True, data_origin=data_origin
        )
        await _track("list_prices", counts["list_prices"])

    if "clusters" in dataframes:
        counts["clusters"] = await ingest_clusters(
            session, dataframes["clusters"], replace=True, data_origin=data_origin
        )
        await _track("clusters", counts["clusters"])

    if "warehouses" in dataframes:
        counts["warehouses"] = await ingest_warehouses(
            session, dataframes["warehouses"], replace=True, data_origin=data_origin
        )
        await _track("warehouses", counts["warehouses"])

    if "jobs" in dataframes:
        counts["jobs"] = await ingest_jobs(
            session, dataframes["jobs"], replace=True, data_origin=data_origin
        )
        await _track("jobs", counts["jobs"])

    if "billing_usage" in dataframes:
        counts["billing_usage"] = await ingest_usage(
            session, dataframes["billing_usage"], replace=replace, data_origin=data_origin
        )
        await _track("billing_usage", counts["billing_usage"])

    if "workspaces" in dataframes:
        counts["workspaces"] = await ingest_workspaces(
            session, dataframes["workspaces"], data_origin=data_origin
        )
        await _track("workspaces", counts["workspaces"])
    counts["workspace_stubs"] = await backfill_workspace_stubs(session)

    if "query_history" in dataframes:
        counts["query_history"] = await ingest_query_history(
            session, dataframes["query_history"], replace=replace, data_origin=data_origin
        )
        await _track("query_history", counts["query_history"])

    # Unity Catalog meta — snapshot table; always full-replace on the partition.
    if "databricks_meta" in dataframes:
        counts["databricks_meta"] = await ingest_meta(
            session, dataframes["databricks_meta"], replace=True, data_origin=data_origin
        )
        await _track("databricks_meta", counts["databricks_meta"])

    # Lineage tables — always full-replace on the partition.
    if "table_lineage" in dataframes:
        counts["table_lineage"] = await ingest_table_lineage(
            session, dataframes["table_lineage"], replace=True, data_origin=data_origin
        )
        await _track("table_lineage", counts["table_lineage"])
    if "column_lineage" in dataframes:
        counts["column_lineage"] = await ingest_column_lineage(
            session, dataframes["column_lineage"], replace=True, data_origin=data_origin
        )
        await _track("column_lineage", counts["column_lineage"])

    # Audit + assistant_events — full-replace on the partition.
    if "audit_events" in dataframes:
        counts["audit_events"] = await ingest_audit(
            session, dataframes["audit_events"], replace=True, data_origin=data_origin
        )
        await _track("audit_events", counts["audit_events"])
    if "assistant_events" in dataframes:
        counts["assistant_events"] = await ingest_assistant_events(
            session, dataframes["assistant_events"], replace=True, data_origin=data_origin
        )
        await _track("assistant_events", counts["assistant_events"])

    # system.compute.* — full-replace per partition. Reference tables
    # (node_types, instance_pools) load every time the group is selected.
    if "node_timeline" in dataframes:
        counts["node_timeline"] = await ingest_node_timeline(
            session, dataframes["node_timeline"], replace=True, data_origin=data_origin
        )
        await _track("node_timeline", counts["node_timeline"])
    if "warehouse_events" in dataframes:
        counts["warehouse_events"] = await ingest_warehouse_events(
            session, dataframes["warehouse_events"], replace=True, data_origin=data_origin
        )
        await _track("warehouse_events", counts["warehouse_events"])
    if "node_types" in dataframes:
        counts["node_types"] = await ingest_node_types(
            session, dataframes["node_types"], replace=True, data_origin=data_origin
        )
        await _track("node_types", counts["node_types"])
    if "instance_events" in dataframes:
        counts["instance_events"] = await ingest_instance_events(
            session, dataframes["instance_events"], replace=True, data_origin=data_origin
        )
        await _track("instance_events", counts["instance_events"])
    if "instance_pools" in dataframes:
        counts["instance_pools"] = await ingest_instance_pools(
            session, dataframes["instance_pools"], replace=True, data_origin=data_origin
        )
        await _track("instance_pools", counts["instance_pools"])

    await session.commit()
    return counts


async def ingest_from_parquet(
    session: AsyncSession,
    data_dir: str = "data",
    replace: bool = False,
    file_prefix: str = "",
    data_origin: str = "real",
    tables: Optional[list[str]] = None,
    progress_cb: Optional[ProgressCb] = None,
) -> dict[str, int]:
    """Load the most recent parquet files via the storage layer and ingest into Postgres.

    For DATA_STORE=local, ``data_dir`` is honored. For cloud backends it's
    ignored and files are read from the configured bucket.

    ``file_prefix`` lets callers target a parallel set of files (e.g.
    ``"demo_"`` matches ``demo_billing_usage_*.parquet``). When set, the
    cloud-store branch is skipped — demo files live on local disk only.

    ``tables`` restricts which parquet files to read. When None (default),
    all known tables are attempted. Used after a partial extract — the
    backend passes the exact list the extractor just refreshed so we don't
    re-ingest stale snapshots for groups the user didn't ask for.
    """
    import storage  # local import to avoid module-load circulars

    dataframes: dict[str, pd.DataFrame] = {}

    _all_parquet_tables = [
        "billing_usage", "list_prices", "clusters", "warehouses", "jobs",
        "workspaces", "query_history", "databricks_meta",
        "table_lineage", "column_lineage",
        "audit_events", "assistant_events",
        "node_timeline", "warehouse_events", "node_types",
        "instance_events", "instance_pools",
    ]
    parquet_tables = [t for t in _all_parquet_tables if (tables is None or t in tables)]

    # When a prefix is provided (demo mode) we always read from local disk —
    # demo snapshots aren't published to cloud storage.
    if storage.backing_store() == "local" or file_prefix:
        data_path = Path(data_dir)
        if not data_path.exists():
            logger.warning("Data directory %s does not exist", data_dir)
            return {}
        for table_name in parquet_tables:
            pattern = f"{file_prefix}{table_name}_*.parquet"
            files = sorted(data_path.glob(pattern), reverse=True)
            # Real-data ingest must never pick up demo_*.parquet files. The
            # glob `billing_usage_*.parquet` is already anchored so it won't
            # match `demo_billing_usage_*.parquet`, but filter explicitly so
            # the guarantee can't drift if the pattern ever changes.
            if not file_prefix:
                files = [f for f in files if not f.name.startswith("demo_")]
            if files:
                logger.info("Loading %s from %s", table_name, files[0])
                dataframes[table_name] = pd.read_parquet(files[0])
            elif table_name not in (
                "workspaces", "query_history",
                "table_lineage", "column_lineage",
                "audit_events", "assistant_events",
                "node_timeline", "warehouse_events", "node_types",
                "instance_events", "instance_pools",
            ):
                logger.warning("No parquet file found for %s in %s", pattern, data_dir)
    else:
        # Cloud: use storage.latest_parquet to find the URI, then read it.
        for table_name in parquet_tables:
            uri = storage.latest_parquet(table_name)
            # Same defense as the local branch — never load demo snapshots
            # when the caller asked for real data.
            if uri and Path(uri).name.startswith("demo_"):
                uri = None
            if uri:
                logger.info("Loading %s from %s", table_name, uri)
                dataframes[table_name] = storage.read_parquet(uri)
            elif table_name not in (
                "workspaces", "query_history",
                "table_lineage", "column_lineage",
                "audit_events", "assistant_events",
                "node_timeline", "warehouse_events", "node_types",
                "instance_events", "instance_pools",
            ):
                logger.warning("No parquet file found for %s in %s store", table_name, storage.backing_store())

    if not dataframes:
        logger.warning("No parquet files found to ingest")
        return {}

    return await ingest_all(
        session, dataframes,
        replace=replace, data_origin=data_origin,
        progress_cb=progress_cb,
    )
