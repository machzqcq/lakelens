"""Spark Connect client singleton.

Lazy-initialized. Anything that needs to talk to Spark calls
``get_spark()`` which returns a connected SparkSession. The grpc connection
to the docker-compose `spark-connect` service is shared across requests for
the lifetime of the Python process.

Reads `SPARK_CONNECT_URL` (default `sc://spark-connect:15002`).
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_SPARK = None
_LOCK = threading.Lock()

# In-memory mirror of the Spark sub-mode that the live session was set up
# for. Kept in sync by `apply_spark_mode()`; consulted by `apply_view_mode()`
# to decide which registrar to call (JDBC views vs Delta-shadow views).
# Falls back to the env-var hint at process start.
_CURRENT_SPARK_MODE: str = "jdbc_views"


def _build_remote() -> str:
    """Build the Spark Connect remote URI for the singleton session.

    Three layers of configuration, most-specific wins:

    1. **`SPARK_CONNECT_URL`** — full override. Set this verbatim to a
       Spark Connect URI when pointing at an external Spark deployment
       (e.g. a self-managed Spark Connect cluster behind TLS, or a
       Databricks workspace's Spark Connect endpoint).
       Examples:
         sc://spark.acme.example.com:15002
         sc://spark.acme.example.com:443/;use_ssl=true;token=ABC123
    2. **`SPARK_CONNECT_HOST` + `SPARK_CONNECT_PORT`** + optional
       `SPARK_CONNECT_TOKEN` / `SPARK_CONNECT_USE_SSL` — composed URI.
       Use when you have host/port + auth as separate env vars (typical
       for secret-manager-driven deployments).
    3. **Defaults** (`spark-connect:15002`, no token, no SSL) — match
       the bundled docker-compose stack.

    The Spark Connect gRPC URI grammar appends auth params after a `/;`
    separator: `sc://host:port/;use_ssl=true;token=...`. We build that
    when the auth-bearing vars are set so the format works across
    pyspark[connect] versions.
    """
    override = os.getenv("SPARK_CONNECT_URL", "").strip()
    if override:
        return override

    host = os.getenv("SPARK_CONNECT_HOST", "spark-connect")
    port = os.getenv("SPARK_CONNECT_PORT", "15002")
    token = os.getenv("SPARK_CONNECT_TOKEN", "").strip()
    use_ssl = os.getenv("SPARK_CONNECT_USE_SSL", "").strip().lower() in ("1", "true", "yes")

    uri = f"sc://{host}:{port}"
    params: list[str] = []
    if use_ssl:
        params.append("use_ssl=true")
    if token:
        # Bearer-token auth is forwarded as a gRPC metadata header by
        # the Connect client. Do NOT log the token below — only the
        # bare URI sans params.
        params.append(f"token={token}")
    if params:
        uri = uri + "/;" + ";".join(params)
    return uri


def get_spark():
    """Return a singleton SparkSession connected via Spark Connect.

    Raises a RuntimeError with a clear message if pyspark isn't importable
    (e.g. the Spark image hasn't been deployed yet) — callers should catch
    this and surface it as a 503 / "engine unavailable".
    """
    global _SPARK
    if _SPARK is not None:
        return _SPARK
    with _LOCK:
        if _SPARK is not None:
            return _SPARK
        try:
            from pyspark.sql import SparkSession
        except ImportError as e:
            raise RuntimeError(
                "pyspark not installed. The Spark engine requires pyspark[connect] "
                "in backend/pyproject.toml — rebuild the backend image."
            ) from e

        remote = _build_remote()
        # Redact any embedded token before logging the URI.
        redacted = re.sub(r"token=[^;]+", "token=***", remote)
        logger.info("[spark] connecting to %s ...", redacted)
        spark = SparkSession.builder.remote(remote).getOrCreate()
        # Smoke test the connection so failure is loud + immediate.
        try:
            spark.sql("SELECT 1").collect()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Spark Connect at {remote} is not reachable: {e}"
            ) from e

        # Spark 4.x identifier-quoting compatibility — treat "foo" as a quoted
        # identifier (Postgres semantics) rather than a string literal so our
        # shared SQL works on both engines.
        #
        # Note: we intentionally leave `spark.sql.ansi.enabled` at its Spark 4
        # default (true). Disabling it would silently *wrap* integer overflow
        # (e.g. `100 * 1024 * 1024 * 1024` → 0) which produces wrong results
        # without an error — strictly worse than the loud ANSI error. We
        # handle overflow at the prompt level instead (system prompt instructs
        # the LLM to use BIGINT literals for byte thresholds).
        try:
            spark.conf.set("spark.sql.ansi.doubleQuotedIdentifiers", "true")
        except Exception as e:  # noqa: BLE001
            logger.warning("[spark] failed to configure session: %s", e)

        # Attach Delta tables first so the warehouse catalog is populated,
        # then register the user-facing temp views with a default view_mode
        # of 'real'. Every per-request path (Spark SQL Editor, chatbot)
        # calls apply_view_mode(authed.viewing_data_mode) before executing,
        # so this init value only matters until the first such request.
        _attach_warehouse_delta_tables(spark)
        global _CURRENT_SPARK_MODE
        _CURRENT_SPARK_MODE = _read_spark_mode_sync()
        if _CURRENT_SPARK_MODE == "materialized":
            _register_delta_shadow_views(spark, view_mode="real")
        else:
            _register_base_jdbc_views(spark, view_mode="real")

        _SPARK = spark
        logger.info(
            "[spark] Connect session ready (spark_mode=%s, view_mode=real default; will refresh per-request)",
            _CURRENT_SPARK_MODE,
        )
        return _SPARK


def _read_spark_mode_sync() -> str:
    """Read the spark_mode config in the synchronous session-init code path.

    `get_spark_mode` is async (uses the SQLAlchemy async session); we'd
    need an event loop to call it from this sync function. The simplest
    correct thing is a direct synchronous psycopg-style query — but we
    don't have a sync engine. As a robust workaround we let the caller
    set `SPARK_MODE_OVERRIDE` env var, and otherwise fall back to the
    default. The real source of truth is system_config and is re-checked
    every time the engine is switched via /api/admin/engine (the handler
    calls apply_spark_mode below to bring the session into line).
    """
    return os.getenv("SPARK_MODE_OVERRIDE", "jdbc_views").strip().lower() or "jdbc_views"


def apply_spark_mode(mode: str) -> None:
    """Bring the live Spark session in line with the requested spark sub-mode.

    Called from the /api/admin/engine handler after the mode is persisted.
    Does NOT trigger materialisation — that's a separate explicit step
    via /api/admin/materialize-postgres-to-spark.

    After this call, the next user-issued query path will go through
    `apply_view_mode()` to register either JDBC temp views (jdbc_views)
    or Delta-shadow temp views (materialized) — both with the user's
    view-mode filter baked in.
    """
    global _CURRENT_SPARK_MODE
    mode = mode if mode in ("jdbc_views", "materialized") else "jdbc_views"
    _CURRENT_SPARK_MODE = mode
    if _SPARK is None:
        return
    # Drop any stale temp views from the previous mode so the new
    # registration path starts clean. The actual registration happens
    # lazily on the next apply_view_mode() call — typical case is the
    # next chatbot or Spark SQL Editor request — so we don't need to
    # guess the user's view_mode here.
    drop_base_temp_views()
    logger.info("[spark] applied spark_mode=%s to live session (views will refresh on next query)", mode)


# Base tables that live in Postgres and are exposed to Spark via JDBC when
# spark_mode=jdbc_views (and copied into spark-warehouse as managed Delta
# tables when spark_mode=materialized).
#
# databricks_meta + the lineage tables are small-to-medium and read for
# join/lookup work, so JDBC pull-through works well. The `lineage_rollups`
# cache table is also exposed so chatbot prompts can use it for fast
# per-FQN tile counts.
_BASE_TABLES = (
    "billing_usage",
    "list_prices",
    "clusters",
    "warehouses",
    "jobs",
    "workspaces",
    "query_history",
    "databricks_meta",
    "table_lineage",
    "column_lineage",
    "lineage_rollups",
    "audit_events",
    "assistant_events",
    # system.compute.* — node pool / instance telemetry. node_timeline is
    # the highest-cardinality entry; pushdown is enabled below so LIMIT /
    # WHERE go to Postgres.
    "node_timeline",
    "warehouse_events",
    "node_types",
    "instance_events",
    "instance_pools",
)

# Query Profiler tables — written by the QI ETL. Their LOCATION depends on
# the active (engine, spark_mode) combo:
#
#   engine=duckdb                     → Postgres
#   engine=spark + spark_mode=jdbc_views   → Postgres (exposed to Spark as JDBC temp views)
#   engine=spark + spark_mode=materialized → Delta tables in spark_catalog.default
#
# In `jdbc_views` mode the registrar below adds them to the JDBC temp-view
# set so the Spark SQL Editor shows them with a `temp` badge and the
# chatbot's Spark prompt can reference them unqualified. In `materialized`
# mode they're real catalog tables and don't get registered here.
_QI_TABLES = (
    "qi_statements",
    "qi_statement_tables",
    "qi_statement_columns",
    "qi_statement_tags",
    "qi_statement_parameters",
    "qi_statement_errors",
)

# Tables that carry the standard `deleted_at` soft-delete tombstone in
# addition to `data_origin`. Used by the JDBC + Delta-shadow view
# registrars to decide whether to append `AND deleted_at IS NULL` to the
# view-mode filter. qi_* tables only have `data_origin` (they're fully
# rebuilt per partition by every ETL run, so soft-delete doesn't apply)
# and would otherwise raise UndefinedColumn at JDBC schema-introspection
# time.
_TABLES_WITH_DELETED_AT = set(_BASE_TABLES)


def _view_mode_where(table: str, view_mode: str) -> str:
    """Build the WHERE clause that scopes a temp view to the caller's
    view-mode. Always filters on data_origin; adds the deleted_at clause
    only for tables that carry it."""
    if table in _TABLES_WITH_DELETED_AT:
        return f"WHERE data_origin='{view_mode}' AND deleted_at IS NULL"
    return f"WHERE data_origin='{view_mode}'"


def _pg_jdbc_url() -> str:
    """Build the JDBC URL the Spark workers use to reach Postgres.

    The backend talks to Postgres via asyncpg over the docker network
    (host `db`). Spark workers — which may live in an entirely
    different environment when pointed at an external cluster — talk
    over JDBC and need a hostname THEY can resolve. Three overrides:

    - `SPARK_PG_HOST` / `SPARK_PG_PORT` — Postgres host:port from
      Spark's network perspective. Defaults to the docker service
      name (`db:5432`). For external Spark, set this to a hostname
      the Spark executors can reach (often a private DNS name or a
      public DNS name if Postgres is exposed).
    - `SPARK_PG_DB` — database name, defaults to `DB_NAME`.
    - `SPARK_PG_SSL` — `true` to append `?sslmode=require` to the JDBC
      URL (recommended when Spark and Postgres aren't on the same
      private network).
    """
    host = os.getenv("SPARK_PG_HOST", "db")
    port = os.getenv("SPARK_PG_PORT", "5432")
    db = os.getenv("SPARK_PG_DB", os.getenv("DB_NAME", "databricks_billing"))
    require_ssl = os.getenv("SPARK_PG_SSL", "").strip().lower() in ("1", "true", "yes")
    url = f"jdbc:postgresql://{host}:{port}/{db}"
    if require_ssl:
        url += "?sslmode=require"
    return url


def _pg_jdbc_credentials() -> tuple[str, str]:
    """Resolve the user/password Spark JDBC uses for Postgres.

    The backend's own creds (`DB_USER` / `DB_PASS`) are reused by
    default, but external Spark deployments often need separate creds —
    e.g. a read-only Postgres role provisioned just for Spark, or
    credentials surfaced from a secret manager. Provide
    `SPARK_PG_USER` / `SPARK_PG_PASS` to override.
    """
    user = os.getenv("SPARK_PG_USER", os.getenv("DB_USER", "billing_user"))
    password = os.getenv("SPARK_PG_PASS", os.getenv("DB_PASS", "billing_pass"))
    return user, password


_VALID_VIEW_MODES = ("real", "demo")


def _validate_view_mode(view_mode: str) -> str:
    """Defence in depth — JDBC's `.option('query', ...)` is a SQL string we
    embed `view_mode` into. Constrain the value to the known enum so a
    malicious header can't smuggle SQL through it."""
    m = (view_mode or "").strip().lower()
    return m if m in _VALID_VIEW_MODES else "real"


# Last applied view-mode + spark-mode the live session was refreshed with.
# Used by `apply_view_mode()` to decide if a re-registration is needed and
# to log mode flips clearly.
_CURRENT_VIEW_MODE: str = "real"


def _register_base_jdbc_views(spark, view_mode: str = "real") -> None:
    """Register each Postgres-resident base + qi_* table as a Spark temp
    view of the same name, **filtered by `view_mode` and soft-delete**.

    The JDBC reader uses `.option("query", "SELECT * FROM <t> WHERE
    data_origin='<view_mode>' AND deleted_at IS NULL")` rather than
    `.option("dbtable", <t>)`, so:

      * Real and demo rows never cross-contaminate at the Spark layer.
        Toggling view-mode in the top-right and re-running a query
        produces the right answer without the caller adding a WHERE.
      * The filter is pushed down to Postgres alongside any LIMIT /
        predicates the caller adds, so we still benefit from the
        pushdown options enabled below.
      * `view_mode` is sanitised through `_validate_view_mode` so it
        can't be used to smuggle SQL.

    Multi-user caveat: the Spark Connect session is a singleton across
    all admins. If two admins on different view-modes hit Spark at the
    same instant, the second registration shadows the first. Spark SQL
    Editor + the chatbot both re-register before each query so the
    common case (one admin at a time) is always correct.

    `qi_*` tables are registered alongside base tables — when the QI
    ETL is configured to write to Postgres (engine=duckdb OR
    engine=spark + spark_mode=jdbc_views) the temp views are populated;
    in materialized mode they shadow the Delta tables, which is exactly
    what we want so the filter still applies.
    """
    view_mode = _validate_view_mode(view_mode)
    try:
        url = _pg_jdbc_url()
        user, password = _pg_jdbc_credentials()
        registered: list[str] = []
        tables_to_register = tuple(_BASE_TABLES) + tuple(_QI_TABLES)
        for table in tables_to_register:
            # View-mode + soft-delete filter baked into the JDBC source.
            # `query` is the right knob (not `dbtable`) when we want a
            # WHERE clause: Spark wraps it in `SELECT * FROM (<query>) tab`.
            # The WHERE clause omits `deleted_at IS NULL` for qi_* tables
            # which don't have that column.
            filtered_query = (
                f"SELECT * FROM {table} {_view_mode_where(table, view_mode)}"
            )
            try:
                df = (
                    spark.read.format("jdbc")
                    .option("url", url)
                    .option("query", filtered_query)
                    .option("user", user)
                    .option("password", password)
                    .option("driver", "org.postgresql.Driver")
                    # ---- Postgres-side pushdown ---------------------------
                    # Without these, Spark pulls the WHOLE table into the
                    # executor heap before applying LIMIT / WHERE / COUNT
                    # — OOMs on table_lineage (8M+ rows on real accounts).
                    # `pushDownPredicate` defaults to true but we set it
                    # explicitly so the intent is obvious; the other three
                    # default to false.
                    .option("pushDownPredicate", "true")
                    .option("pushDownLimit",     "true")
                    .option("pushDownOffset",    "true")
                    .option("pushDownAggregate", "true")
                    # JDBC ResultSet fetch buffer. Without this the PG JDBC
                    # driver pulls every row in one round-trip and buffers
                    # in JVM memory. 10k is a sane batch for our row shapes.
                    .option("fetchsize", "10000")
                    .load()
                )
                df.createOrReplaceTempView(table)
                registered.append(table)
            except Exception as e:  # noqa: BLE001
                msg = str(e).splitlines()[0]
                logger.warning("[spark] failed to register %s via JDBC: %s", table, msg)
        if registered:
            logger.info(
                "[spark] base+qi JDBC views registered for view_mode=%s: %s",
                view_mode, ", ".join(registered),
            )
        else:
            logger.warning(
                "[spark] no base-table JDBC views registered — Spark queries "
                "against billing_usage etc. will fail. Check that the postgresql "
                "driver is in spark-connect's --packages and the `db` service "
                "is reachable on the docker network."
            )
    except Exception as e:  # noqa: BLE001 — never block session init
        logger.warning("[spark] _register_base_jdbc_views error: %s", e)


def refresh_base_views(view_mode: str = "real") -> int:
    """Re-register base JDBC views (call this if Postgres schema changes).
    Returns the count of base tables we attempted to register."""
    if _SPARK is None:
        return 0
    _register_base_jdbc_views(_SPARK, view_mode=view_mode)
    return len(_BASE_TABLES)


def _register_delta_shadow_views(spark, view_mode: str) -> None:
    """When `spark_mode=materialized`, the base tables are managed Delta
    tables in `spark_catalog.default`. To apply the view-mode filter we
    register SQL temp views with the same names that shadow the Delta
    tables AND add `WHERE data_origin='<view_mode>' AND deleted_at IS NULL`.

    Spark resolves temp views before catalog tables, so unqualified
    `SELECT * FROM billing_usage` hits the filtered view. The raw catalog
    table is still reachable via the 3-part name
    `spark_catalog.default.billing_usage` when needed.
    """
    view_mode = _validate_view_mode(view_mode)
    registered: list[str] = []
    for table in tuple(_BASE_TABLES) + tuple(_QI_TABLES):
        sql = (
            f"CREATE OR REPLACE TEMP VIEW {table} AS "
            f"SELECT * FROM spark_catalog.default.{table} "
            f"{_view_mode_where(table, view_mode)}"
        )
        try:
            spark.sql(sql)
            registered.append(table)
        except Exception as e:  # noqa: BLE001 — the Delta table may not exist yet
            msg = str(e).splitlines()[0]
            logger.warning("[spark] failed to register Delta-shadow view %s: %s", table, msg)
    if registered:
        logger.info(
            "[spark] Delta-shadow views registered for view_mode=%s: %s",
            view_mode, ", ".join(registered),
        )


def apply_view_mode(view_mode: str) -> None:
    """Bring the live Spark session in line with the calling user's view
    mode. Called per-request by the Spark SQL Editor and the chatbot's
    Spark execution path.

    Reads the active `spark_mode` from a module cache (kept in sync by
    `apply_spark_mode()`). The Spark Connect session is a singleton, so
    if two admins on different view modes hit Spark at the exact same
    instant the second call's registration wins — accepted trade-off
    for the simplicity of the design.
    """
    global _CURRENT_VIEW_MODE
    view_mode = _validate_view_mode(view_mode)
    if _SPARK is None:
        # No live session yet — get_spark() will pick up the latest
        # _CURRENT_VIEW_MODE at init. Stash the desired mode and return.
        _CURRENT_VIEW_MODE = view_mode
        return
    mode = _CURRENT_SPARK_MODE
    if mode == "materialized":
        _register_delta_shadow_views(_SPARK, view_mode)
    else:
        _register_base_jdbc_views(_SPARK, view_mode=view_mode)
    _CURRENT_VIEW_MODE = view_mode


def drop_base_temp_views() -> int:
    """Drop the JDBC-backed base + qi_* temp views. Used when switching the
    Spark sub-mode to `materialized` — after the data is copied into
    spark-warehouse as managed Delta tables, the temp views would shadow
    the new catalog tables (Spark resolves temp views before catalog).

    Returns the count of views actually dropped.
    """
    if _SPARK is None:
        return 0
    dropped = 0
    for table in tuple(_BASE_TABLES) + tuple(_QI_TABLES):
        try:
            _SPARK.catalog.dropTempView(table)
            dropped += 1
        except Exception:  # noqa: BLE001 — view might not exist, that's fine
            pass
    if dropped:
        logger.info("[spark] dropped %d base+qi temp views (mode = materialized)", dropped)
    return dropped


def materialize_postgres_tables(progress_cb=None) -> dict[str, int]:
    """Copy every Postgres-resident base + qi_* table into spark-warehouse
    as a managed Delta table in `spark_catalog.default`.

    After this runs, callers can `SELECT * FROM spark_catalog.default.<name>`
    against the Delta tables instead of round-tripping every query to
    Postgres via JDBC. Re-running overwrites in place — idempotent.

    qi_* tables are included so the materialized mode is self-consistent.
    If the QI ETL hasn't been run in jdbc_views mode yet, the qi_* tables
    are empty in Postgres — the copy still succeeds (empty Delta tables),
    and re-running the QI ETL after switching modes will fully populate
    them via the materialized write path.

    Returns {table_name: row_count}. Progress is reported via the optional
    `progress_cb(table_name, rows)` callback after each table finishes.
    """
    if _SPARK is None:
        # Force session init so callers don't have to remember the ordering.
        get_spark()
    spark = _SPARK
    assert spark is not None

    # We deliberately re-read from JDBC even if a temp view already exists;
    # writes are easier to reason about when we control the read explicitly.
    url = _pg_jdbc_url()
    user, password = _pg_jdbc_credentials()

    counts: dict[str, int] = {}
    for table in tuple(_BASE_TABLES) + tuple(_QI_TABLES):
        try:
            df = (
                spark.read.format("jdbc")
                .option("url", url)
                .option("dbtable", table)
                .option("user", user)
                .option("password", password)
                .option("driver", "org.postgresql.Driver")
                .option("fetchsize", "10000")
                .load()
            )
            # Drop any existing temp view first so saveAsTable can register
            # the catalog table cleanly without a name conflict.
            try:
                spark.catalog.dropTempView(table)
            except Exception:  # noqa: BLE001
                pass
            (
                df.write.format("delta")
                .mode("overwrite")
                .option("overwriteSchema", "true")
                .saveAsTable(f"spark_catalog.default.{table}")
            )
            # Approximate row count (count() executes a full scan but the
            # data is already in Delta now, so this is cheap.)
            row_count = spark.table(f"spark_catalog.default.{table}").count()
            counts[table] = int(row_count)
            logger.info("[spark] materialised %s → spark_catalog.default.%s (%d rows)",
                        table, table, row_count)
            if progress_cb is not None:
                try:
                    progress_cb(table, int(row_count))
                except Exception:
                    logger.warning("progress_cb failed for %s", table, exc_info=True)
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0]
            logger.warning("[spark] failed to materialise %s: %s", table, msg)
            counts[table] = -1  # sentinel — UI shows this as failed
    return counts


# Path layout (different views of the same host directory):
#   _BACKEND_WAREHOUSE_DIR — path inside the backend container (used here to
#                            list directories).
#   _SPARK_WAREHOUSE_DIR   — path inside spark-connect / spark-worker (used in
#                            the spark.read.format("delta").load() URI).
_BACKEND_WAREHOUSE_DIR = os.getenv("BACKEND_WAREHOUSE_DIR", "/app/data/spark-warehouse")
_SPARK_WAREHOUSE_DIR = os.getenv("SPARK_WAREHOUSE_DIR", "/opt/spark/spark-warehouse")


def _attach_warehouse_delta_tables(spark) -> None:
    """Auto-discover Delta tables in spark-warehouse and re-attach them.

    Spark Connect runs with an in-memory catalog by default — no Hive
    metastore — so `saveAsTable(...)` registrations are lost when the
    spark-connect container restarts, even though the underlying Delta
    files survive on the bind-mounted `data/spark-warehouse/` host folder.

    This walks the warehouse, finds every directory that contains a
    `_delta_log/`, and registers it as a managed-style table (via Delta's
    LOCATION clause) so it shows up in `spark_catalog.default` and in our
    Spark SQL Editor's table list.
    """
    try:
        from pathlib import Path
        backend_wh = Path(_BACKEND_WAREHOUSE_DIR)
        if not backend_wh.exists():
            logger.info(
                "[spark] warehouse dir %s not found from backend; "
                "skipping Delta auto-attach", _BACKEND_WAREHOUSE_DIR,
            )
            return
        registered: list[str] = []
        found: list[str] = []
        for entry in sorted(backend_wh.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "_delta_log").exists():
                continue
            name = entry.name
            found.append(name)
            spark_uri = f"{_SPARK_WAREHOUSE_DIR}/{name}"
            try:
                # `CREATE TABLE IF NOT EXISTS ... USING DELTA LOCATION ...`
                # re-attaches an existing Delta table to the catalog without
                # rewriting data. Delta infers the schema from the existing
                # `_delta_log/`. `IF NOT EXISTS` is idempotent (REPLACE would
                # require an explicit schema, which we don't have here).
                spark.sql(
                    f"CREATE TABLE IF NOT EXISTS spark_catalog.default.`{name}` "
                    f"USING DELTA LOCATION '{spark_uri}'"
                )
                registered.append(name)
            except Exception as e:  # noqa: BLE001
                msg = str(e).splitlines()[0]
                logger.warning("[spark] failed to attach Delta table %s: %s", name, msg)
        if registered:
            logger.info("[spark] Delta tables attached to spark_catalog.default: %s",
                        ", ".join(registered))
        elif found:
            logger.warning(
                "[spark] found %d Delta dir(s) but failed to attach any: %s",
                len(found), ", ".join(found),
            )
        else:
            logger.info("[spark] no Delta tables found under %s", _BACKEND_WAREHOUSE_DIR)
    except Exception as e:  # noqa: BLE001 — never block session init
        logger.warning("[spark] _attach_warehouse_delta_tables error: %s", e)


def refresh_warehouse_tables() -> int:
    """Re-scan the warehouse and re-attach all Delta tables. Useful after
    `Extract query profiler` finishes — the new tables show up immediately."""
    if _SPARK is None:
        return 0
    _attach_warehouse_delta_tables(_SPARK)
    return 1


def reset_spark() -> None:
    """Drop the cached session (test seam)."""
    global _SPARK
    if _SPARK is not None:
        try:
            _SPARK.stop()
        except Exception:  # noqa: BLE001
            pass
    _SPARK = None
