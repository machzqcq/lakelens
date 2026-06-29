from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


# ---------------------------------------------------------------------------
# Every domain table (billing/compute/query) carries two isolation columns:
#   - data_origin   ('real' or 'demo') — physically separates demo from real
#                   data so the two never cross-pollute. Every load operation
#                   tags rows on insert; every read filters on the active
#                   user's `viewing_data_mode`.
#   - deleted_at    soft-delete tombstone. Reads always filter `IS NULL`.
# Logic lives in backend/data_scope.py.
# ---------------------------------------------------------------------------


class BillingUsage(Base):
    """Maps to system.billing.usage."""

    __tablename__ = "billing_usage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String)
    workspace_id: Mapped[str] = mapped_column(String)
    record_id: Mapped[str] = mapped_column(String, unique=True)
    sku_name: Mapped[str] = mapped_column(String)
    cloud: Mapped[str] = mapped_column(String)
    usage_start_time: Mapped[datetime] = mapped_column()
    usage_end_time: Mapped[datetime] = mapped_column()
    usage_date: Mapped[date] = mapped_column()
    usage_unit: Mapped[str] = mapped_column(String)
    usage_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    billing_origin_product: Mapped[str] = mapped_column(String)
    usage_type: Mapped[str] = mapped_column(String)
    record_type: Mapped[str] = mapped_column(String)
    ingestion_date: Mapped[date] = mapped_column()

    # Extracted from usage_metadata
    cluster_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    warehouse_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    node_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    run_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Extracted from identity_metadata
    run_as: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Extracted from product_features
    jobs_tier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sql_tier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    dlt_tier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_serverless: Mapped[Optional[bool]] = mapped_column(nullable=True)
    is_photon: Mapped[Optional[bool]] = mapped_column(nullable=True)
    serving_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Extracted from usage_metadata (additional)
    instance_pool_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Pre-calculated cost in USD (from Databricks: usage_quantity * pricing.effective_list.default)
    usage_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)

    # Data-isolation columns (see top of this file)
    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("ix_billing_usage_usage_date", "usage_date"),
        Index("ix_billing_usage_sku_name", "sku_name"),
        Index("ix_billing_usage_workspace_id", "workspace_id"),
        Index("ix_billing_usage_billing_origin_product", "billing_origin_product"),
        Index("ix_billing_usage_usage_type", "usage_type"),
        Index("ix_billing_usage_origin_deleted", "data_origin", "deleted_at"),
    )


class ListPrice(Base):
    """Maps to system.billing.list_prices."""

    __tablename__ = "list_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String)
    sku_name: Mapped[str] = mapped_column(String)
    cloud: Mapped[str] = mapped_column(String)
    currency_code: Mapped[str] = mapped_column(String)
    usage_unit: Mapped[str] = mapped_column(String)
    price_start_time: Mapped[datetime] = mapped_column()
    price_end_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    default_price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    effective_list_price: Mapped[Decimal] = mapped_column(Numeric(20, 6))

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class Cluster(Base):
    """Maps to system.compute.clusters."""

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String)
    workspace_id: Mapped[str] = mapped_column(String)
    cluster_id: Mapped[str] = mapped_column(String)
    cluster_name: Mapped[str] = mapped_column(String)
    owned_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    driver_node_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    worker_node_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    worker_count: Mapped[Optional[int]] = mapped_column(nullable=True)
    min_autoscale_workers: Mapped[Optional[int]] = mapped_column(nullable=True)
    max_autoscale_workers: Mapped[Optional[int]] = mapped_column(nullable=True)
    dbr_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cluster_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    data_security_mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    create_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    delete_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    change_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class Warehouse(Base):
    """Maps to system.compute.warehouses."""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String)
    workspace_id: Mapped[str] = mapped_column(String)
    warehouse_id: Mapped[str] = mapped_column(String)
    warehouse_name: Mapped[str] = mapped_column(String)
    warehouse_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    warehouse_size: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    min_clusters: Mapped[Optional[int]] = mapped_column(nullable=True)
    max_clusters: Mapped[Optional[int]] = mapped_column(nullable=True)
    auto_stop_minutes: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    change_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    delete_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class Workspace(Base):
    """Workspace-id → human-readable name lookup.

    Source of truth: system.access.workspaces_latest in Databricks. For demo
    seed data, populated from seed_data.WORKSPACES. Either source may be
    absent for a given workspace_id seen in billing_usage — in that case the
    row may exist with workspace_name=NULL, and consumers should fall back
    to displaying workspace_id.
    """

    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    workspace_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    workspace_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    create_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class QueryHistory(Base):
    """Maps to system.query.history.

    Saved verbatim from Databricks for ad-hoc querying via the Database
    Explorer; not yet consumed by any analytics endpoint. STRUCT/MAP source
    columns (compute, query_source, query_parameters, query_tags) are
    serialized to JSON for portability.
    """

    __tablename__ = "query_history"

    statement_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    executed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    executed_by_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    executed_as: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    executed_as_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    execution_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    compute: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # statement_text can be very large (multi-statement scripts); use TEXT.
    statement_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    statement_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_application: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    client_driver: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # All LONG (int64) columns from Spark — BIGINT in Postgres.
    total_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    waiting_for_compute_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    waiting_at_capacity_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    execution_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    compilation_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_task_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    result_fetch_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    start_time: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    update_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    read_partitions: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pruned_files: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_files: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_rows: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    produced_rows: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # read_io_cache_percent is 0-100 (BYTE in source), but keeping it consistent.
    read_io_cache_percent: Mapped[Optional[int]] = mapped_column(nullable=True)
    from_result_cache: Mapped[Optional[bool]] = mapped_column(nullable=True)
    spilled_local_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    written_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    shuffle_read_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    written_rows: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    written_files: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pruned_files_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_files_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    query_source: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    query_parameters: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    query_tags: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    cache_origin_statement_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class Job(Base):
    """Maps to system.lakeflow.jobs."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String)
    workspace_id: Mapped[str] = mapped_column(String)
    job_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    creator_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    run_as: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    change_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    delete_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class DatabricksMeta(Base):
    """Unity Catalog metadata snapshot — one row per (catalog, database, table, column).

    Populated by `extract/meta_extractor.get_meta_info_optimized` (which reuses
    the same SQL as `db_helpers.get_meta_info_optimized` from the notebook).
    Drives the Meta Explorer page.
    """

    __tablename__ = "databricks_meta"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    catalog: Mapped[str] = mapped_column(String, index=True)
    db_schema: Mapped[str] = mapped_column("database", String, index=True)
    table_name: Mapped[str] = mapped_column("table_name", String, index=True)
    col_name: Mapped[str] = mapped_column(String, index=True)
    data_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    table_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    table_owner: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    table_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    as_of: Mapped[Optional[date]] = mapped_column(nullable=True, index=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class TableLineage(Base):
    """Edges from `system.access.table_lineage`.

    Schema mirrors the published Databricks contract. One row per lineage edge
    a statement emitted. Notable semantics:

      - `record_id` is the per-row PK. `event_id` may be shared across rows
        that originated from the same statement (one query → many rows).
      - `source_*` OR `target_*` can be NULL — that's how Databricks encodes
        the event class:
            source NOT NULL + target NULL  → read-only
            source NULL + target NOT NULL  → write-only
            both NOT NULL                  → read-write
      - `direct_access=true` = source/target were referenced directly by the
        query. False = intermediate dependency surfaced by lineage analysis.
      - `entity_metadata` is a STRUCT in Databricks; we store it as JSON.
        Fields: job_info{job_id, job_run_id}, dlt_pipeline_info{dlt_pipeline_id,
        dlt_update_id}, notebook_id, dashboard_id, legacy_dashboard_id,
        sql_query_id, genie_space_id, alert_id. Any number may be populated.
      - Retention in `system.access.*` is 1 year (rolling). For longer history
        use Catalog Explorer or the lineage API.
    """

    __tablename__ = "table_lineage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    metastore_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_time: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    event_date: Mapped[Optional[date]] = mapped_column(nullable=True, index=True)

    # Databricks-issued IDs — record_id is per-row unique, event_id may repeat.
    record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=False)
    event_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    source_table_full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    source_table_catalog:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    source_table_schema:    Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_table_name:      Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # TABLE | PATH | VIEW | MATERIALIZED_VIEW | METRIC_VIEW | STREAMING_TABLE
    source_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    target_table_full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    target_table_catalog:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    target_table_schema:    Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_table_name:      Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # same enum as source_type
    target_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # WHO drove the lineage event. Real Databricks enum:
    #   NOTEBOOK, JOB, PIPELINE, DASHBOARD_V3, DBSQL_DASHBOARD (deprecated),
    #   DBSQL_QUERY, or NULL when no Databricks entity (e.g., JDBC).
    created_by:     Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    entity_type:    Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    entity_id:      Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_run_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    statement_id:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    direct_access:  Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, index=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("ix_table_lineage_src_tgt", "source_table_full_name", "target_table_full_name"),
        Index("ix_table_lineage_origin_deleted", "data_origin", "deleted_at"),
    )


class ColumnLineage(Base):
    """Edges from `system.access.column_lineage`.

    Same shape as `TableLineage` with `source_column_name` / `target_column_name`
    added. Notable: column_lineage does NOT capture events that have no source
    (e.g., `INSERT VALUES`), so write-only edges are absent here.
    """

    __tablename__ = "column_lineage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    metastore_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_time: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    event_date: Mapped[Optional[date]] = mapped_column(nullable=True, index=True)
    record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    event_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    source_table_full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    source_table_catalog:   Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_table_schema:    Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_table_name:      Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_column_name:     Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    source_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    target_table_full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    target_table_catalog:   Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_table_schema:    Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_table_name:      Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_column_name:     Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by:    Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_type:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    entity_id:     Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    statement_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    direct_access: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, index=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("ix_column_lineage_src_tgt", "source_table_full_name", "target_table_full_name"),
        Index("ix_column_lineage_origin_deleted", "data_origin", "deleted_at"),
    )


class AuditEvent(Base):
    """Rows from `system.access.audit` — every account/workspace audit event
    Databricks emits (login, table-grant, notebook-export, SQL warehouse
    starts, …). Per Databricks' published schema.

    Storage notes:
      * `user_identity`, `request_params`, `response`, `identity_metadata`
        are STRUCT / MAP in Databricks; we land them as JSON.
      * `audit_level` is the small enum (`ACCOUNT_LEVEL` /
        `WORKSPACE_LEVEL`); for account-level rows the workspace_id is
        recorded by Databricks as `0` so we keep it as String for
        portability.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    version:      Mapped[Optional[str]] = mapped_column(String, nullable=True)
    event_time:   Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    event_date:   Mapped[Optional[date]] = mapped_column(nullable=True, index=True)

    source_ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    user_agent:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    session_id:        Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # user_identity STRUCT — also exposed split for cheap GROUP BY on email.
    user_identity:        Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    user_identity_email:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    service_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    action_name:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    request_id:   Mapped[Optional[str]] = mapped_column(String, nullable=True)
    request_params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    response:                Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    response_status_code:    Mapped[Optional[int]] = mapped_column(nullable=True, index=True)
    response_error_message:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    audit_level:       Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_id:          Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    identity_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("ix_audit_service_action", "service_name", "action_name"),
        Index("ix_audit_origin_deleted", "data_origin", "deleted_at"),
    )


class AssistantEvent(Base):
    """Rows from `system.access.assistant_events` — user-submitted Databricks
    Assistant / Genie Code interactions. Per Databricks' published schema.

    The table only records *user-submitted* interactions; autocomplete and
    safety checks are intentionally excluded upstream.
    """

    __tablename__ = "assistant_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id:     Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    account_id:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_time:   Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    event_date:   Mapped[Optional[date]] = mapped_column(nullable=True, index=True)
    user_agent:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    initiated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


# ---------------------------------------------------------------------------
# system.compute.* — node pool / instance telemetry. node_timeline is the
# heavyweight (per-minute timeseries); the rest are events or reference.
# All share the same `data_origin` / `deleted_at` isolation pattern.
# ---------------------------------------------------------------------------


class NodeTimeline(Base):
    """Rows from `system.compute.node_timeline` — per-minute instance
    utilization snapshots. Highest-cardinality compute table; the extractor
    chunks by 3-day window and the JDBC reader uses pushdown options to
    keep result sets bounded on the Spark side.
    """

    __tablename__ = "node_timeline"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    cluster_id:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    instance_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    start_time:   Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    end_time:     Mapped[Optional[datetime]] = mapped_column(nullable=True)
    event_date:   Mapped[Optional[date]] = mapped_column(nullable=True, index=True)
    driver:       Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    node_type:    Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    cpu_user_percent:   Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    cpu_system_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    cpu_wait_percent:   Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    mem_used_percent:   Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    mem_swap_percent:   Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    network_sent_bytes:     Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    network_received_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    disk_free_bytes_per_mount_point: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("ix_node_timeline_origin_deleted", "data_origin", "deleted_at"),
        Index("ix_node_timeline_cluster_time", "cluster_id", "start_time"),
    )


class WarehouseEvent(Base):
    """Rows from `system.compute.warehouse_events` — SQL warehouse
    lifecycle events (STARTING, RUNNING, STOPPED, SCALED_UP/DOWN, …).
    """

    __tablename__ = "warehouse_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id:    Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    workspace_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    warehouse_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_type:    Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    cluster_count: Mapped[Optional[int]] = mapped_column(nullable=True)
    event_time:    Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    event_date:    Mapped[Optional[date]] = mapped_column(nullable=True, index=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("ix_warehouse_events_origin_deleted", "data_origin", "deleted_at"),
    )


class NodeType(Base):
    """Rows from `system.compute.node_types` — reference catalog of every
    node type Databricks exposes (i3.xlarge, Standard_DS3_v2, …) with cpu /
    memory / gpu specs. Reference table — full-replaced on every extract.
    """

    __tablename__ = "node_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    node_type:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    core_count: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    memory_mb:  Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    gpu_count:  Mapped[Optional[int]] = mapped_column(nullable=True)
    category:   Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class InstanceEvent(Base):
    """Rows from `system.compute.node_events` — VM/node-level lifecycle
    events. Surfaced as `instance_events` everywhere downstream to match
    the Databricks UI label. `event_details` is the upstream STRUCT, kept
    as JSON.
    """

    __tablename__ = "instance_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id:        Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    workspace_id:      Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    cluster_id:        Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    instance_id:       Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    instance_pool_id:  Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_type:        Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    event_time:        Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    event_date:        Mapped[Optional[date]] = mapped_column(nullable=True, index=True)
    node_type:         Mapped[Optional[str]] = mapped_column(String, nullable=True)
    event_details:     Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("ix_instance_events_origin_deleted", "data_origin", "deleted_at"),
    )


class InstancePool(Base):
    """Rows from `system.compute.instance_pools` — instance pool catalog
    (min/max capacity, idle-termination behavior, preloaded Spark versions).
    Reference table; full-replaced on every extract.
    """

    __tablename__ = "instance_pools"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id:       Mapped[Optional[str]] = mapped_column(String, nullable=True)
    workspace_id:     Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    instance_pool_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    instance_pool_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    node_type:        Mapped[Optional[str]] = mapped_column(String, nullable=True)
    min_idle_instances: Mapped[Optional[int]] = mapped_column(nullable=True)
    max_capacity:     Mapped[Optional[int]] = mapped_column(nullable=True)
    idle_instance_autotermination_minutes: Mapped[Optional[int]] = mapped_column(nullable=True)
    enable_elastic_disk: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    preloaded_spark_versions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    create_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    delete_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    change_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)


class LineageRollup(Base):
    """Materialized aggregates over table_lineage, populated by the Transform
    section's Lineage tasks. One row per (data_origin, full_name).

    Lets the dashboards render KPI tiles and "top tables" lists without
    re-aggregating millions of edges on every page load. Rebuilt in-place
    on every Transform run.
    """

    __tablename__ = "lineage_rollups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)
    full_name:   Mapped[str] = mapped_column(String, nullable=False, index=True)

    edges_in:        Mapped[int] = mapped_column(default=0)  # rows where full_name is target
    edges_out:       Mapped[int] = mapped_column(default=0)  # rows where full_name is source
    distinct_upstream:   Mapped[int] = mapped_column(default=0)
    distinct_downstream: Mapped[int] = mapped_column(default=0)
    distinct_entities:   Mapped[int] = mapped_column(default=0)
    direct_edges:    Mapped[int] = mapped_column(default=0)  # direct_access = true
    indirect_edges:  Mapped[int] = mapped_column(default=0)  # direct_access = false
    last_event:      Mapped[Optional[datetime]] = mapped_column(nullable=True)
    rebuilt_at:      Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("data_origin", "full_name", name="uq_lineage_rollup_origin_fn"),
    )


# ---------------------------------------------------------------------------
# Query Intel (qi_*) — derived from query_history via the ETL in
# backend/extract/query_intel.py. Kept in a separate namespace so the
# raw query_history table stays untouched. Rebuilt on every "Extract
# query intel" button click.
# ---------------------------------------------------------------------------


class QiStatement(Base):
    """One row per query — the flat, denormalized view of query_history.

    This is the table 90% of analytical questions hit directly. Foreign-key
    style detail (table refs, columns, tags, parameters, errors) lives in
    the sibling qi_statement_* tables.
    """

    __tablename__ = "qi_statements"

    # Composite PK with data_origin so the same Databricks statement_id can
    # appear in both the 'real' and 'demo' partitions side-by-side. Without
    # this, a user who ran the QI ETL before data_origin existed (every row
    # defaulting to 'real') and then re-runs the demo ETL hits a PK
    # violation — the demo insert collides with the stale 'real'-tagged
    # rows because the legacy PK was statement_id alone.
    statement_id: Mapped[str] = mapped_column(String, primary_key=True)

    # --- Identity ---
    account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    executed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    executed_by_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    executed_as: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    executed_as_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    is_delegated: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    principal_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # human|service|unknown

    # --- Compute (flat from compute struct) ---
    compute_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    warehouse_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    cluster_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- Statement metadata ---
    statement_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    execution_status: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    statement_text_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # first 2 KB
    statement_text_length: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    statement_text_sha1: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    normalized_sql_hash: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    is_sql: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # parsed as SQL successfully
    has_select_star: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_cross_join: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_cte: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_subquery: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_window: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_describe_or_show: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_dml: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_ddl: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_grant_revoke: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_parameterized: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # --- Client ---
    client_application: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    client_driver: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    client_driver_family: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # JDBC/ODBC/PyConnector/...
    client_driver_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- Source attribution (flat from query_source struct) ---
    source_category: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)  # JOB|PIPELINE|NOTEBOOK|DASHBOARD|ALERT|SQL_QUERY|GENIE|AD_HOC
    job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    job_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    job_task_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pipeline_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    update_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notebook_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    dashboard_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    legacy_dashboard_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    alert_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sql_query_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    genie_space_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    # --- Latency (verbatim from struct) ---
    total_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    waiting_for_compute_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    waiting_at_capacity_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    execution_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    compilation_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_task_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    result_fetch_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # --- Time / temporal ---
    start_time: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    update_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(nullable=True, index=True)
    start_hour: Mapped[Optional[int]] = mapped_column(nullable=True)  # 0-23
    start_day_of_week: Mapped[Optional[int]] = mapped_column(nullable=True)  # 0=Mon
    is_off_hours: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_weekend: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # --- IO (verbatim) ---
    read_partitions: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pruned_files: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_files: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_rows: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    produced_rows: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_io_cache_percent: Mapped[Optional[int]] = mapped_column(nullable=True)
    from_result_cache: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    spilled_local_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    written_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    shuffle_read_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    written_rows: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    written_files: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pruned_files_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_files_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # --- Derived metrics (precomputed for fast filters) ---
    pruning_ratio: Mapped[Optional[float]] = mapped_column(Numeric(8, 4), nullable=True)  # 0..1
    selectivity_ratio: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)  # produced/read
    waiting_pct: Mapped[Optional[float]] = mapped_column(Numeric(8, 4), nullable=True)  # 0..1
    compile_pct: Mapped[Optional[float]] = mapped_column(Numeric(8, 4), nullable=True)  # 0..1
    is_full_scan: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # heuristic: big read, small return
    is_expensive: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # heuristic: top 1% duration or bytes
    is_cache_hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # mirrors from_result_cache
    cache_origin_statement_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- Outcome ---
    error_category: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sqlstate: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- Project-attribution helpers ---
    project_keywords: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    # Flat catalog/schema lists, populated alongside qi_statement_tables, for
    # cheap "queries that touched catalog X" filters without a JOIN.
    catalogs_touched: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    schemas_touched: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    tables_touched: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)

    # View-mode isolation. Stamped by the QI ETL based on the source parquet
    # file_prefix ('demo_' → 'demo', else 'real'). The qi_runner injects a
    # `data_origin = '<view_mode>'` filter into every SQL it runs, so all
    # Query Intel endpoints honour the caller's view-mode toggle.
    # Also part of the composite primary key (see statement_id above).
    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", primary_key=True)

    # All needed indexes are already declared via index=True on the columns
    # themselves; adding them again here would clash on default names.


class QiStatementTable(Base):
    """Tables referenced by a statement, with the role they played in it."""

    __tablename__ = "qi_statement_tables"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement_id: Mapped[str] = mapped_column(String, index=True)
    catalog: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    db_schema: Mapped[Optional[str]] = mapped_column("schema", String, nullable=True, index=True)
    table_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    fully_qualified: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)  # read|write|cte|reference
    is_system_table: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_temp: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)


class QiStatementColumn(Base):
    """Columns referenced and how they were used."""

    __tablename__ = "qi_statement_columns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement_id: Mapped[str] = mapped_column(String, index=True)
    column_name: Mapped[str] = mapped_column(String, index=True)
    table_hint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String)  # select|where|groupby|orderby|join|having|aggregate

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)


class QiStatementTag(Base):
    """Flattened query_tags: one row per (statement_id, tag_key)."""

    __tablename__ = "qi_statement_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement_id: Mapped[str] = mapped_column(String, index=True)
    tag_key: Mapped[str] = mapped_column(String, index=True)
    tag_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)


class QiStatementParameter(Base):
    """Flattened query_parameters: one row per named parameter."""

    __tablename__ = "qi_statement_parameters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement_id: Mapped[str] = mapped_column(String, index=True)
    param_name: Mapped[str] = mapped_column(String, index=True)
    param_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    param_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", index=True)


class QiStatementError(Base):
    """Normalized error metadata for FAILED statements (1:1 with qi_statements where status=FAILED)."""

    __tablename__ = "qi_statement_errors"

    # Composite PK (statement_id, data_origin) — mirrors qi_statements so
    # the same statement_id can have an error row in both partitions.
    statement_id: Mapped[str] = mapped_column(String, primary_key=True)
    error_category: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    sqlstate: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referenced_object: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    referenced_user: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    data_origin: Mapped[str] = mapped_column(String(8), nullable=False, default="real", primary_key=True)


class SystemConfig(Base):
    """Single-row key/value config table. Holds the query-intel engine
    choice (and any other future runtime settings)."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class QiExtractRun(Base):
    """Audit log for each 'Extract query intel' button click."""

    __tablename__ = "qi_extract_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    source_file: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rows_processed: Mapped[int] = mapped_column(default=0)
    statements_inserted: Mapped[int] = mapped_column(default=0)
    tables_extracted: Mapped[int] = mapped_column(default=0)
    columns_extracted: Mapped[int] = mapped_column(default=0)
    tags_extracted: Mapped[int] = mapped_column(default=0)
    params_extracted: Mapped[int] = mapped_column(default=0)
    errors_extracted: Mapped[int] = mapped_column(default=0)
    parse_failures: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")  # running|success|failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Background jobs — long-running operations (extracts, loads, deletes,
# query intel ETL) live here so progress survives page reloads, navigation,
# and container restarts (the latter just marks 'running' rows as 'lost' at
# startup). Powered by backend/background_jobs.py.
# ---------------------------------------------------------------------------


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)  # 'load-demo' / 'load-real' / 'extract-query-intel' / 'soft-delete' / 'hard-delete' / 'incremental-load' / ...
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")  # queued|running|success|failed|canceled|lost
    progress_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)  # 0.00–100.00
    current_step: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_steps: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    params_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    # Cancellation request flag. The runner checks this between steps and
    # exits cleanly when set. Distinct from `status='canceled'`, which is
    # the terminal status after acknowledgement.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class IngestCursor(Base):
    """High-watermark cursor per (table, origin) for incremental loads.

    `Incremental Load` reads only rows with update_time > max_update_time
    (and tie-breaks on the table's natural key when timestamps collide).
    """

    __tablename__ = "ingest_cursors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(64), index=True)
    data_origin: Mapped[str] = mapped_column(String(8), default="real")
    max_update_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    max_record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    rows_ingested: Mapped[int] = mapped_column(BigInteger, default=0)

    __table_args__ = (
        UniqueConstraint("table_name", "data_origin", name="uq_ingest_cursor_table_origin"),
    )


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

class User(Base):
    """Application user account. Identified by email; password_hash is null for OAuth-only users."""

    __tablename__ = "auth_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-user sticky view mode for the data isolation system. 'real' (default)
    # or 'demo'. Drives the data_origin filter on every domain read and the
    # yellow banner on the frontend.
    viewing_data_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="real")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class Role(Base):
    """RBAC role. is_system=True for built-in admin/user; custom roles store data-scope filters."""

    __tablename__ = "auth_roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # Data-scope filter spec, e.g.:
    #   {"workspace_ids": ["ws-001"], "sku_name_pattern": "PREMIUM%", "clouds": ["AZURE"], ...}
    # Empty dict / null = no data restriction (admin behavior).
    filters: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Feature-grant matrix: a list of feature keys (from features_registry.py)
    # the role grants. NULL means "all features" — used by system roles and
    # by custom roles created before the column existed. Empty list = no
    # features granted (the role still attaches but unlocks nothing).
    features: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class UserRole(Base):
    """Many-to-many: users ↔ roles."""

    __tablename__ = "auth_user_roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("auth_roles.id", ondelete="CASCADE"), index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )


class OAuthAccount(Base):
    """Links a User to a third-party identity (google/microsoft/github)."""

    __tablename__ = "auth_oauth_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # google | microsoft | github
    provider_user_id: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )


class EmailVerificationToken(Base):
    """One-time tokens for email verification."""

    __tablename__ = "auth_email_verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column()
    used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


