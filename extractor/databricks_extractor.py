"""Databricks data extractor (isolated worker).

Same SQL contract as the legacy backend extractor — but here it runs in a
container whose only Databricks coupling is `databricks-connect`/`databricks-sdk`,
with NO pyspark==4.x in the venv (databricks-connect brings its own bundled
pyspark 3.5.x). The backend service no longer talks to Databricks directly.

The output is timestamped parquet files in /app/data (mounted to host
./data so the backend can read them). The backend is responsible for
ingesting those parquet files into Postgres.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from databricks.connect import DatabricksSession
from databricks.sdk.core import Config

from groups import ALL_GROUPS, GROUPS, tables_for_groups  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL queries (verbatim from the previous backend extractor — single source of
# truth lives here now)
# ---------------------------------------------------------------------------

USAGE_QUERY = """
WITH prices AS (
  SELECT
    COALESCE(price_end_time, DATE_ADD(CURRENT_DATE(), 1)) AS coalesced_price_end_time,
    *
  FROM system.billing.list_prices
  WHERE currency_code = 'USD'
)
SELECT
    u.account_id,
    u.workspace_id,
    u.record_id,
    u.sku_name,
    u.cloud,
    u.usage_start_time,
    u.usage_end_time,
    u.usage_date,
    u.usage_unit,
    u.usage_quantity,
    u.billing_origin_product,
    u.usage_type,
    u.record_type,
    u.ingestion_date,

    u.usage_metadata.cluster_id            AS cluster_id,
    u.usage_metadata.warehouse_id          AS warehouse_id,
    u.usage_metadata.instance_pool_id      AS instance_pool_id,
    u.usage_metadata.node_type             AS node_type,
    u.usage_metadata.job_id                AS job_id,
    u.usage_metadata.run_name              AS run_name,

    u.identity_metadata.run_as             AS run_as,

    u.product_features.jobs_tier           AS jobs_tier,
    u.product_features.sql_tier            AS sql_tier,
    u.product_features.dlt_tier            AS dlt_tier,
    u.product_features.is_serverless       AS is_serverless,
    u.product_features.is_photon           AS is_photon,
    u.product_features.serving_type        AS serving_type,

    COALESCE(u.usage_quantity * p.pricing.effective_list.default, 0) AS usage_usd

FROM system.billing.usage AS u
LEFT JOIN prices AS p
    ON u.sku_name = p.sku_name
    AND u.usage_unit = p.usage_unit
    AND u.usage_end_time BETWEEN p.price_start_time AND p.coalesced_price_end_time
WHERE u.usage_date >= '{start_date}'
  AND u.usage_date <= '{end_date}'
ORDER BY u.usage_date, u.usage_start_time
"""

LIST_PRICES_QUERY = """
SELECT
    account_id,
    sku_name,
    cloud,
    currency_code,
    usage_unit,
    price_start_time,
    price_end_time,
    pricing.default                      AS default_price,
    pricing.effective_list.default        AS effective_list_price
FROM system.billing.list_prices
WHERE currency_code = 'USD'
ORDER BY sku_name, cloud, price_start_time
"""

WORKSPACES_QUERY = """
SELECT
    workspace_id,
    account_id,
    workspace_name,
    workspace_url,
    create_time,
    status
FROM system.access.workspaces_latest
"""

QUERY_HISTORY_QUERY = """
SELECT
    statement_id, account_id, workspace_id, executed_by, executed_by_user_id,
    executed_as, executed_as_user_id, session_id, execution_status, compute,
    statement_text, statement_type, error_message, client_application, client_driver,
    total_duration_ms, waiting_for_compute_duration_ms, waiting_at_capacity_duration_ms,
    execution_duration_ms, compilation_duration_ms, total_task_duration_ms,
    result_fetch_duration_ms, start_time, end_time, update_time,
    read_partitions, pruned_files, read_files, read_rows, produced_rows,
    read_bytes, read_io_cache_percent, from_result_cache, spilled_local_bytes,
    written_bytes, shuffle_read_bytes, query_source, written_rows, written_files,
    cache_origin_statement_id, query_parameters, query_tags,
    pruned_files_bytes, read_files_bytes
FROM system.query.history
WHERE start_time >= TIMESTAMP'{start_date}'
  AND start_time <  TIMESTAMP'{end_date}' + INTERVAL 1 DAY
"""

CLUSTERS_QUERY = """
SELECT
    account_id, workspace_id, cluster_id, cluster_name, owned_by,
    driver_node_type, worker_node_type, worker_count,
    min_autoscale_workers, max_autoscale_workers, dbr_version,
    cluster_source, data_security_mode, create_time, delete_time, change_time
FROM system.compute.clusters
"""

WAREHOUSES_QUERY = """
SELECT
    account_id, workspace_id, warehouse_id, warehouse_name,
    warehouse_type, warehouse_size, min_clusters, max_clusters,
    auto_stop_minutes, created_by, change_time, delete_time
FROM system.compute.warehouses
"""

JOBS_QUERY = """
SELECT
    account_id, workspace_id, job_id, name, creator_id,
    run_as, change_time, delete_time
FROM system.lakeflow.jobs
"""

# ---------------------------------------------------------------------------
# Lineage queries — schema from https://docs.databricks.com/aws/en/admin/
# system-tables/lineage. The `entity_metadata` STRUCT is JSON-encoded inline
# so the parquet/Postgres pipeline doesn't have to track nested types. IDs
# cast to STRING for parquet portability.
#
# entity_type values: NOTEBOOK | JOB | PIPELINE | DASHBOARD_V3 |
#                     DBSQL_DASHBOARD (deprecated) | DBSQL_QUERY | NULL
# *_type values:      TABLE | PATH | VIEW | MATERIALIZED_VIEW |
#                     METRIC_VIEW | STREAMING_TABLE
# direct_access:      true = directly referenced; false = intermediate dep.
# event class:        source NOT NULL + target NULL → read-only
#                     target NOT NULL + source NULL → write-only
#                     both NOT NULL                  → read-write
# Retention:          ~1 year rolling.
# ---------------------------------------------------------------------------
_LINEAGE_COMMON_COLS = """
    CAST(account_id    AS STRING) AS account_id,
    CAST(metastore_id  AS STRING) AS metastore_id,
    CAST(workspace_id  AS STRING) AS workspace_id,
    event_time,
    event_date,
    CAST(record_id     AS STRING) AS record_id,
    CAST(event_id      AS STRING) AS event_id,
    source_table_full_name,
    source_table_catalog,
    source_table_schema,
    source_table_name,
    source_type,
    source_path,
    target_table_full_name,
    target_table_catalog,
    target_table_schema,
    target_table_name,
    target_type,
    target_path,
    created_by,
    entity_type,
    CAST(entity_id     AS STRING) AS entity_id,
    CAST(entity_run_id AS STRING) AS entity_run_id,
    -- entity_metadata is a STRUCT. .toPandas() will surface it as a nested
    -- Row/dict; ingest._to_jsonable flattens it to plain Python dicts before
    -- the asyncpg JSON write.
    entity_metadata,
    CAST(statement_id  AS STRING) AS statement_id,
    direct_access
"""

TABLE_LINEAGE_QUERY = f"""
SELECT
{_LINEAGE_COMMON_COLS}
FROM system.access.table_lineage
WHERE event_date >= DATE'{{start_date}}'
  AND event_date <= DATE'{{end_date}}'
"""

COLUMN_LINEAGE_QUERY = f"""
SELECT
{_LINEAGE_COMMON_COLS.replace('source_type,', 'source_column_name, source_type,').replace('target_type,', 'target_column_name, target_type,')}
FROM system.access.column_lineage
WHERE event_date >= DATE'{{start_date}}'
  AND event_date <= DATE'{{end_date}}'
"""


# system.access.audit — every account/workspace audit event Databricks emits
# (login, table-grant, notebook-export, SQL warehouse start, …). We surface
# the user_identity.email split column for cheap GROUP BY and pre-extract
# response.status_code / response.error_message for KPI tiles. Other nested
# fields stay as JSON via to_json(...). NOTE: the public Databricks docs
# write these inner fields in camelCase (`statusCode`, `errorMessage`) but
# the actual struct in `system.access.audit` exposes them in snake_case —
# selecting the camelCase names raises `FIELD_NOT_FOUND`.
AUDIT_QUERY = """
SELECT
    CAST(account_id   AS STRING) AS account_id,
    CAST(workspace_id AS STRING) AS workspace_id,
    version,
    event_time,
    event_date,
    source_ip_address,
    user_agent,
    session_id,
    to_json(user_identity)     AS user_identity,
    user_identity.email        AS user_identity_email,
    service_name,
    action_name,
    request_id,
    to_json(request_params)    AS request_params,
    to_json(response)          AS response,
    response.status_code       AS response_status_code,
    response.error_message     AS response_error_message,
    audit_level,
    event_id,
    to_json(identity_metadata) AS identity_metadata
FROM system.access.audit
WHERE event_date >= DATE'{start_date}'
  AND event_date <= DATE'{end_date}'
"""

# system.access.assistant_events — user-submitted Databricks Assistant /
# Genie Code interactions. Schema is minimal; autocomplete and safety
# checks are excluded upstream.
ASSISTANT_EVENTS_QUERY = """
SELECT
    CAST(event_id     AS STRING) AS event_id,
    CAST(account_id   AS STRING) AS account_id,
    CAST(workspace_id AS STRING) AS workspace_id,
    event_time,
    CAST(event_date   AS DATE)   AS event_date,
    user_agent,
    initiated_by
FROM system.access.assistant_events
WHERE event_date >= DATE'{start_date}'
  AND event_date <= DATE'{end_date}'
"""


# ---------------------------------------------------------------------------
# system.compute.* — node pool / instance telemetry
# ---------------------------------------------------------------------------

# system.compute.node_timeline — per-minute instance utilization. The
# highest-cardinality system table in the compute schema — a busy account
# easily produces tens of millions of rows per day. We aggressively chunk
# by start_time date and pre-extract the numeric utilization fields. The
# disk_free_bytes MAP gets to_json'd for portability.
NODE_TIMELINE_QUERY = """
SELECT
    CAST(account_id   AS STRING) AS account_id,
    CAST(workspace_id AS STRING) AS workspace_id,
    CAST(cluster_id   AS STRING) AS cluster_id,
    CAST(instance_id  AS STRING) AS instance_id,
    start_time,
    end_time,
    CAST(start_time AS DATE) AS event_date,
    driver,
    node_type,
    cpu_user_percent,
    cpu_system_percent,
    cpu_wait_percent,
    mem_used_percent,
    mem_swap_percent,
    network_sent_bytes,
    network_received_bytes,
    to_json(disk_free_bytes_per_mount_point) AS disk_free_bytes_per_mount_point
FROM system.compute.node_timeline
WHERE CAST(start_time AS DATE) >= DATE'{start_date}'
  AND CAST(start_time AS DATE) <= DATE'{end_date}'
"""

# system.compute.warehouse_events — SQL warehouse lifecycle events
# (STARTING, RUNNING, STOPPED, SCALED_UP, SCALED_DOWN, …). Modest volume;
# weekly chunks are plenty.
WAREHOUSE_EVENTS_QUERY = """
SELECT
    CAST(account_id   AS STRING) AS account_id,
    CAST(workspace_id AS STRING) AS workspace_id,
    CAST(warehouse_id AS STRING) AS warehouse_id,
    event_type,
    cluster_count,
    event_time,
    CAST(event_time AS DATE) AS event_date
FROM system.compute.warehouse_events
WHERE CAST(event_time AS DATE) >= DATE'{start_date}'
  AND CAST(event_time AS DATE) <= DATE'{end_date}'
"""

# system.compute.node_types — reference catalog of every node type
# (i3.xlarge, Standard_DS3_v2, …) with cpu / memory / gpu specs. No date
# bound — small reference table; we full-replace on every extract.
#
# NOTE: the public Databricks `system.compute.node_types` schema today is
# {account_id, node_type, core_count, memory_mb, gpu_count} — there is NO
# `category` column on real accounts (Spark rejects the SELECT with
# UNRESOLVED_COLUMN). We SELECT a NULL placeholder so the parquet column
# survives the round-trip and the downstream model / ingest / dashboard
# stays unchanged; demo data populates `category` directly.
NODE_TYPES_QUERY = """
SELECT
    CAST(account_id AS STRING) AS account_id,
    node_type,
    core_count,
    memory_mb,
    gpu_count,
    CAST(NULL AS STRING) AS category
FROM system.compute.node_types
"""

# system.compute.node_events — VM/node-level lifecycle events. The user-
# facing label is `instance_events` (matches the Databricks UI's "instance
# events" panel) but the system-table name is node_events. We rename the
# extract output to `instance_events` so downstream consumers see one
# unified name. event_details is a STRUCT — JSON-ified for portability.
INSTANCE_EVENTS_QUERY = """
SELECT
    CAST(account_id        AS STRING) AS account_id,
    CAST(workspace_id      AS STRING) AS workspace_id,
    CAST(cluster_id        AS STRING) AS cluster_id,
    CAST(instance_id       AS STRING) AS instance_id,
    CAST(instance_pool_id  AS STRING) AS instance_pool_id,
    event_type,
    event_time,
    CAST(event_time AS DATE) AS event_date,
    node_type,
    to_json(event_details) AS event_details
FROM system.compute.node_events
WHERE CAST(event_time AS DATE) >= DATE'{start_date}'
  AND CAST(event_time AS DATE) <= DATE'{end_date}'
"""

# system.compute.instance_pools — instance pool catalog. Reference table,
# no date bound, full-replace on every extract.
INSTANCE_POOLS_QUERY = """
SELECT
    CAST(account_id        AS STRING) AS account_id,
    CAST(workspace_id      AS STRING) AS workspace_id,
    CAST(instance_pool_id  AS STRING) AS instance_pool_id,
    instance_pool_name,
    node_type,
    min_idle_instances,
    max_capacity,
    idle_instance_autotermination_minutes,
    enable_elastic_disk,
    preloaded_spark_versions,
    create_time,
    delete_time,
    change_time
FROM system.compute.instance_pools
"""


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def get_databricks_session(
    host: Optional[str] = None,
    token: Optional[str] = None,
    profile: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> DatabricksSession:
    host = host or os.getenv("DATABRICKS_HOST")
    token = token or os.getenv("DATABRICKS_TOKEN")
    profile = profile or os.getenv("DATABRICKS_CONFIG_PROFILE", "DEFAULT")
    cluster_id = cluster_id or os.getenv("DATABRICKS_CLUSTER_ID")

    config_kwargs: dict = {}
    if host:
        config_kwargs["host"] = host
    else:
        config_kwargs["profile"] = profile

    if host and token:
        config_kwargs["token"] = token
        config_kwargs["auth_type"] = "pat"
    else:
        os.environ.pop("DATABRICKS_TOKEN", None)
        config_kwargs["auth_type"] = "external-browser"

    db_config = Config(**config_kwargs)
    if cluster_id:
        db_config.cluster_id = cluster_id
    else:
        db_config.serverless_compute_id = "auto"

    spark = DatabricksSession.builder.sdkConfig(db_config).getOrCreate()
    logger.info("Connected to Databricks at %s", host or profile)
    return spark


# ---------------------------------------------------------------------------
# Per-table extractors
# ---------------------------------------------------------------------------

def extract_usage(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    logger.info("[usage] %s → %s", start_date, end_date)
    df = spark.sql(USAGE_QUERY.format(start_date=start_date, end_date=end_date)).toPandas()
    df["usage_quantity"] = pd.to_numeric(df["usage_quantity"], errors="coerce")
    df["usage_date"] = pd.to_datetime(df["usage_date"]).dt.date
    df["ingestion_date"] = pd.to_datetime(df["ingestion_date"]).dt.date
    for col in ["is_serverless", "is_photon"]:
        if col in df.columns:
            df[col] = df[col].astype("boolean")
    logger.info("[usage] %d rows", len(df))
    return df


def extract_list_prices(spark) -> pd.DataFrame:
    df = spark.sql(LIST_PRICES_QUERY).toPandas()
    df["default_price"] = pd.to_numeric(df["default_price"], errors="coerce")
    df["effective_list_price"] = pd.to_numeric(df["effective_list_price"], errors="coerce")
    logger.info("[list_prices] %d rows", len(df))
    return df


def extract_clusters(spark) -> pd.DataFrame:
    df = spark.sql(CLUSTERS_QUERY).toPandas()
    logger.info("[clusters] %d rows", len(df))
    return df


def extract_warehouses(spark) -> pd.DataFrame:
    df = spark.sql(WAREHOUSES_QUERY).toPandas()
    logger.info("[warehouses] %d rows", len(df))
    return df


def extract_jobs(spark) -> pd.DataFrame:
    df = spark.sql(JOBS_QUERY).toPandas()
    logger.info("[jobs] %d rows", len(df))
    return df


def extract_workspaces(spark) -> pd.DataFrame:
    df = spark.sql(WORKSPACES_QUERY).toPandas()
    logger.info("[workspaces] %d rows", len(df))
    return df


def _extract_lineage_chunked(
    spark,
    *,
    label: str,
    sql_template: str,
    start_date: str,
    end_date: str,
    chunk_days: int = 7,
) -> pd.DataFrame:
    """Pull a lineage table week-by-week, concatenating each pandas chunk.

    Lineage system tables can carry tens of millions of rows over a 2-year
    window. Collecting the whole range into the driver via a single
    `.toPandas()` is the documented OOM path. We loop by `chunk_days`
    (default 7 days) so each `.toPandas()` is bounded and the driver heap
    can release between chunks.
    """
    sd = datetime.strptime(start_date, "%Y-%m-%d").date()
    ed = datetime.strptime(end_date,   "%Y-%m-%d").date()
    if ed < sd:
        sd, ed = ed, sd
    total_days = (ed - sd).days + 1
    logger.info("[%s] %s → %s (%d day(s), %d-day chunks)", label, sd, ed, total_days, chunk_days)

    frames: list[pd.DataFrame] = []
    cur = sd
    total_rows = 0
    while cur <= ed:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), ed)
        sql = sql_template.format(start_date=cur.isoformat(), end_date=chunk_end.isoformat())
        try:
            df = spark.sql(sql).toPandas()
        except Exception as e:
            logger.warning("[%s] chunk %s..%s failed: %s", label, cur, chunk_end, e)
            cur = chunk_end + timedelta(days=1)
            continue
        if "event_date" in df.columns:
            df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
        total_rows += len(df)
        if len(df):
            frames.append(df)
        logger.info("[%s]   %s..%s -> %d rows (cumulative %d)",
                    label, cur, chunk_end, len(df), total_rows)
        cur = chunk_end + timedelta(days=1)

    if not frames:
        # Return an empty DataFrame with the expected columns so downstream
        # type-checks don't trip on `df.columns`.
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    logger.info("[%s] %d rows total", label, len(out))
    return out


def extract_table_lineage(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    return _extract_lineage_chunked(
        spark, label="table_lineage",
        sql_template=TABLE_LINEAGE_QUERY,
        start_date=start_date, end_date=end_date,
    )


def extract_column_lineage(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    # Column lineage is the larger of the two — chunk more aggressively.
    return _extract_lineage_chunked(
        spark, label="column_lineage",
        sql_template=COLUMN_LINEAGE_QUERY,
        start_date=start_date, end_date=end_date,
        chunk_days=3,
    )


def extract_audit(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    # Audit volumes can rival query_history on busy accounts — chunk weekly
    # so each .toPandas() stays bounded.
    return _extract_lineage_chunked(
        spark, label="audit",
        sql_template=AUDIT_QUERY,
        start_date=start_date, end_date=end_date,
        chunk_days=7,
    )


def extract_assistant_events(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    # Assistant events are low-volume (only user-submitted prompts); no chunking needed.
    logger.info("[assistant_events] %s → %s", start_date, end_date)
    df = spark.sql(ASSISTANT_EVENTS_QUERY.format(start_date=start_date, end_date=end_date)).toPandas()
    if "event_date" in df.columns:
        df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
    logger.info("[assistant_events] %d rows", len(df))
    return df


# ---------------------------------------------------------------------------
# system.compute.* extractors
# ---------------------------------------------------------------------------

def extract_node_timeline(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    """system.compute.node_timeline — per-minute utilization timeseries.
    Highest-cardinality compute table by a wide margin (Arrow batches can
    easily OOM the connect driver on a wide window). 3-day chunks."""
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    return _extract_lineage_chunked(
        spark, label="node_timeline",
        sql_template=NODE_TIMELINE_QUERY,
        start_date=start_date, end_date=end_date,
        chunk_days=3,
    )


def extract_warehouse_events(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    """system.compute.warehouse_events — SQL warehouse lifecycle. Weekly
    chunks like audit; volume is modest."""
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    return _extract_lineage_chunked(
        spark, label="warehouse_events",
        sql_template=WAREHOUSE_EVENTS_QUERY,
        start_date=start_date, end_date=end_date,
        chunk_days=7,
    )


def extract_node_types(spark) -> pd.DataFrame:
    """system.compute.node_types — node-type reference catalog. Small,
    no date bound, one-shot query."""
    logger.info("[node_types] extracting reference catalog")
    df = spark.sql(NODE_TYPES_QUERY).toPandas()
    logger.info("[node_types] %d rows", len(df))
    return df


def extract_instance_events(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    """system.compute.node_events — VM lifecycle events. Renamed to
    instance_events downstream to match the Databricks UI label."""
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    return _extract_lineage_chunked(
        spark, label="instance_events",
        sql_template=INSTANCE_EVENTS_QUERY,
        start_date=start_date, end_date=end_date,
        chunk_days=7,
    )


def extract_instance_pools(spark) -> pd.DataFrame:
    """system.compute.instance_pools — instance pool catalog. Reference
    table, one-shot query."""
    logger.info("[instance_pools] extracting catalog")
    df = spark.sql(INSTANCE_POOLS_QUERY).toPandas()
    logger.info("[instance_pools] %d rows", len(df))
    return df


def extract_query_history(spark, start_date: str, end_date: Optional[str]) -> pd.DataFrame:
    import json
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    logger.info("[query_history] %s → %s", start_date, end_date)
    df = spark.sql(QUERY_HISTORY_QUERY.format(start_date=start_date, end_date=end_date)).toPandas()

    def _to_jsonable(v):
        if v is None:
            return None
        if hasattr(v, "asDict"):
            return v.asDict(recursive=True)
        if isinstance(v, (dict, list)):
            return v
        try:
            return json.loads(json.dumps(v, default=str))
        except Exception:
            return str(v)

    for col in ("compute", "query_source", "query_parameters", "query_tags"):
        if col in df.columns:
            df[col] = df[col].map(_to_jsonable)

    for col in ("workspace_id", "account_id", "executed_by_user_id", "executed_as_user_id"):
        if col in df.columns:
            df[col] = df[col].astype("object").where(df[col].notna(), None)
            df[col] = df[col].map(lambda v: None if v is None else str(v))

    logger.info("[query_history] %d rows", len(df))
    return df


# ---------------------------------------------------------------------------
# Parquet sink (local-only — relies on the shared /app/data volume the backend
# also mounts, so each name_<date>.parquet shows up in the backend's view).
# ---------------------------------------------------------------------------

def save_to_parquet(df: pd.DataFrame, name: str, output_dir: str = "/app/data") -> str:
    ts = datetime.now().strftime("%Y-%m-%d")
    filename = f"{name}_{ts}.parquet"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / filename
    df.attrs = {}
    df.to_parquet(path, index=False)
    logger.info("Saved %s (%d rows) to %s", name, len(df), path)
    return str(path)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def extract_all(
    spark,
    start_date: str = "2024-01-01",
    end_date: Optional[str] = None,
    output_dir: str = "/app/data",
    save_parquet: bool = True,
    groups: Optional[list[str] | tuple[str, ...]] = None,
    table_lineage_days_back: int = 14,
    column_lineage_days_back: int = 7,
    # Per-table lookbacks for the time-bounded tables in the `audit` and
    # `node_pool` groups. node_types + instance_pools are reference tables
    # (no date bound) and don't take a knob.
    audit_events_days_back: int = 3,
    assistant_events_days_back: int = 30,
    node_timeline_days_back: int = 3,
    warehouse_events_days_back: int = 30,
    instance_events_days_back: int = 14,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Extract the requested groups; optionally save parquet snapshots.

    Returns (dataframes, parquet_paths) — both keyed by table_name. A table
    will be missing from both dicts if it was filtered out or its extraction
    raised a tolerated error (e.g. no SELECT grant on system.query.history).
    """
    wanted = tables_for_groups(groups)
    results: dict[str, pd.DataFrame] = {}

    if "billing_usage" in wanted:
        results["billing_usage"] = extract_usage(spark, start_date, end_date)
    if "list_prices" in wanted:
        results["list_prices"] = extract_list_prices(spark)
    if "clusters" in wanted:
        results["clusters"] = extract_clusters(spark)
    if "warehouses" in wanted:
        results["warehouses"] = extract_warehouses(spark)
    if "jobs" in wanted:
        results["jobs"] = extract_jobs(spark)
    if "workspaces" in wanted:
        try:
            results["workspaces"] = extract_workspaces(spark)
        except Exception as e:
            logger.warning("Skipping workspace metadata (%s)", e)
    if "query_history" in wanted:
        try:
            results["query_history"] = extract_query_history(spark, start_date, end_date)
        except Exception as e:
            logger.warning("Skipping query history (%s)", e)
    if "databricks_meta" in wanted:
        try:
            from meta_extractor import extract_meta
            target = os.getenv("DATABRICKS_HOST") or "<unknown>"
            logger.info("[meta] starting Unity Catalog crawl via Databricks workspace: %s", target)
            results["databricks_meta"] = extract_meta(spark)
        except Exception as e:
            logger.warning("Skipping databricks_meta (%s)", e)

    # Lineage tables are tolerated to be missing — system.access.table_lineage /
    # column_lineage require Unity Catalog AND the account-level system schema
    # to be enabled. We skip cleanly rather than failing the whole extract.
    #
    # Each lineage table has its own (much shorter) window than the wider
    # [start_date, end_date] used by billing/query_history. column_lineage is
    # typically 3-5x the volume of table_lineage, so its default budget is
    # narrower (1 week vs 2 weeks).
    if "table_lineage" in wanted or "column_lineage" in wanted:
        eff_end = end_date or datetime.now().strftime("%Y-%m-%d")
        eff_end_d = datetime.strptime(eff_end, "%Y-%m-%d").date()

        def _narrow(days_back: int) -> str:
            start = (eff_end_d - timedelta(days=max(1, days_back) - 1)).isoformat()
            # Don't widen beyond the caller-supplied start_date.
            return start_date if start_date > start else start

        if "table_lineage" in wanted:
            tl_start = _narrow(table_lineage_days_back)
            logger.info(
                "[table_lineage] window %s..%s (%d days back)",
                tl_start, eff_end, table_lineage_days_back,
            )
            try:
                results["table_lineage"] = extract_table_lineage(spark, tl_start, eff_end)
            except Exception as e:
                logger.warning("Skipping table_lineage (%s)", e)
        if "column_lineage" in wanted:
            cl_start = _narrow(column_lineage_days_back)
            logger.info(
                "[column_lineage] window %s..%s (%d days back)",
                cl_start, eff_end, column_lineage_days_back,
            )
            try:
                results["column_lineage"] = extract_column_lineage(spark, cl_start, eff_end)
            except Exception as e:
                logger.warning("Skipping column_lineage (%s)", e)

    # Audit + assistant_events — also tolerated-fail (some accounts don't
    # expose the access schema). Each gets its own (much shorter than the
    # billing window) lookback because audit volume can rival query_history
    # on busy accounts and assistant_events tends to be low-volume.
    if "audit_events" in wanted or "assistant_events" in wanted:
        eff_end = end_date or datetime.now().strftime("%Y-%m-%d")
        eff_end_d = datetime.strptime(eff_end, "%Y-%m-%d").date()

        def _narrow(days_back: int) -> str:
            start = (eff_end_d - timedelta(days=max(1, days_back) - 1)).isoformat()
            return start_date if start_date > start else start

        if "audit_events" in wanted:
            au_start = _narrow(audit_events_days_back)
            logger.info(
                "[audit_events] window %s..%s (%d days back)",
                au_start, eff_end, audit_events_days_back,
            )
            try:
                results["audit_events"] = extract_audit(spark, au_start, eff_end)
            except Exception as e:
                logger.warning("Skipping audit_events (%s)", e)
        if "assistant_events" in wanted:
            ae_start = _narrow(assistant_events_days_back)
            logger.info(
                "[assistant_events] window %s..%s (%d days back)",
                ae_start, eff_end, assistant_events_days_back,
            )
            try:
                results["assistant_events"] = extract_assistant_events(spark, ae_start, eff_end)
            except Exception as e:
                logger.warning("Skipping assistant_events (%s)", e)

    # system.compute.* node pool / instance telemetry. Each time-bounded
    # table gets its own lookback knob — node_timeline is per-minute and
    # heaviest (3d default); warehouse_events / instance_events are event
    # logs with lighter cardinality so they can afford 30d / 14d. node_types
    # + instance_pools are reference tables (no date bound) and ignore any
    # window — extracted unconditionally when in `wanted`.
    _NODE_POOL_TABLES = (
        "node_timeline", "warehouse_events",
        "node_types", "instance_events", "instance_pools",
    )
    if any(t in wanted for t in _NODE_POOL_TABLES):
        eff_end = end_date or datetime.now().strftime("%Y-%m-%d")
        eff_end_d = datetime.strptime(eff_end, "%Y-%m-%d").date()

        def _np_narrow(days_back: int) -> str:
            start = (eff_end_d - timedelta(days=max(1, days_back) - 1)).isoformat()
            return start_date if start_date > start else start

        if "node_timeline" in wanted:
            nt_start = _np_narrow(node_timeline_days_back)
            logger.info(
                "[node_timeline] window %s..%s (%d days back)",
                nt_start, eff_end, node_timeline_days_back,
            )
            try:
                results["node_timeline"] = extract_node_timeline(spark, nt_start, eff_end)
            except Exception as e:
                logger.warning("Skipping node_timeline (%s)", e)
        if "warehouse_events" in wanted:
            we_start = _np_narrow(warehouse_events_days_back)
            logger.info(
                "[warehouse_events] window %s..%s (%d days back)",
                we_start, eff_end, warehouse_events_days_back,
            )
            try:
                results["warehouse_events"] = extract_warehouse_events(spark, we_start, eff_end)
            except Exception as e:
                logger.warning("Skipping warehouse_events (%s)", e)
        if "instance_events" in wanted:
            ie_start = _np_narrow(instance_events_days_back)
            logger.info(
                "[instance_events] window %s..%s (%d days back)",
                ie_start, eff_end, instance_events_days_back,
            )
            try:
                results["instance_events"] = extract_instance_events(spark, ie_start, eff_end)
            except Exception as e:
                logger.warning("Skipping instance_events (%s)", e)
        if "node_types" in wanted:
            try:
                results["node_types"] = extract_node_types(spark)
            except Exception as e:
                logger.warning("Skipping node_types (%s)", e)
        if "instance_pools" in wanted:
            try:
                results["instance_pools"] = extract_instance_pools(spark)
            except Exception as e:
                logger.warning("Skipping instance_pools (%s)", e)

    paths: dict[str, str] = {}
    if save_parquet:
        for name, df in results.items():
            paths[name] = save_to_parquet(df, name, output_dir)

    return results, paths
