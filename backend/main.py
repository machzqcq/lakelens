"""Databricks Billing Analytics API -- FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # loads .env from cwd (or parent dirs)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from database import async_session, init_db
from models import BillingUsage, Role, User, UserRole
from routers import analytics, auth, billing, chat, compute
from routers.admin import router as admin_router
from routers.admin_users import router as admin_users_router
from routers.data_ops import router as data_ops_router
from routers.db_explorer import router as db_explorer_router
from routers.features import state_router as features_state_router
from routers.audit import router as audit_router
from routers.node_pool import router as node_pool_router
from routers.meta_explorer import router as meta_explorer_router
from routers.metadata import router as metadata_router
from routers.query_intel import router as query_intel_router
from routers.sku_origin import router as sku_origin_router
from routers.spark_sql import router as spark_sql_router
from schemas import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _auto_populate() -> None:
    """Populate the database on startup with DEMO data only.

    Design rule: auto-populate is for first-boot ergonomics. The user should
    be able to log in and immediately see a working dashboard with demo
    numbers. Anything that touches REAL data — local parquet ingest OR a
    live Databricks extract — is an explicit user action via
    Admin → Data Management once they're logged in.

    Why no auto-parquet-ingest:
      * Hard-delete + restart should NOT silently re-load real data the
        admin just wiped. Today's behaviour was the opposite — parquet
        snapshots on disk would re-inflate the DB on every boot.
      * Booting a brand-new install with `data/` populated from a previous
        deployment shouldn't conflate that data with the new env.

    Why no auto-Databricks-extract:
      * Extracts cost money (Spark cluster time + SQL warehouse usage)
        and take minutes. Triggering one on every container restart is
        a footgun. The legacy `AUTO_EXTRACT=true` opt-in is also removed.

    Net behaviour: if `billing_usage` is empty on boot, seed demo data.
    If it already has rows, leave it alone. Anything richer is initiated
    from the UI.
    """
    async with async_session() as session:
        result = await session.execute(
            select(func.count()).select_from(BillingUsage)
        )
        count = result.scalar() or 0
        if count > 0:
            logger.info("Database already has %d usage records. Skipping auto-populate.", count)
            return

    logger.info("Empty database — seeding demo data so the user can log in to a working app. "
                "Real data (parquet ingest or Databricks extract) is a separate, explicit "
                "action under Admin → Data Management.")
    from seed_data import seed_database

    async with async_session() as session:
        await seed_database(session)
    logger.info("Demo seed complete.")


async def _seed_auth_defaults() -> None:
    """Create the system 'admin'/'user' roles and the bootstrap admin if missing."""
    from auth_utils import hash_password

    async with async_session() as session:
        # System roles
        existing_names = {
            r for (r,) in (await session.execute(select(Role.name).where(Role.is_system == True))).all()  # noqa: E712
        }
        for name, desc in [
            ("admin", "Full access incl. user/role management. Bypasses data-scope filters."),
            ("user", "Default role for verified users. Read-only access to billing data."),
        ]:
            if name not in existing_names:
                session.add(Role(name=name, description=desc, is_system=True, filters={}))
                logger.info("[auth] Seeded system role: %s", name)
        await session.commit()

        # Bootstrap admin
        admin_email = os.getenv("DEFAULT_ADMIN_EMAIL", "").strip().lower()
        admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "").strip()
        if not admin_email or not admin_password:
            logger.info(
                "[auth] DEFAULT_ADMIN_EMAIL/DEFAULT_ADMIN_PASSWORD not set — "
                "no bootstrap admin created. Use /api/auth/register and assign admin role manually."
            )
            return

        existing = (await session.execute(select(User).where(User.email == admin_email))).scalar_one_or_none()
        if existing is None:
            user = User(
                email=admin_email,
                password_hash=hash_password(admin_password),
                full_name="Bootstrap Admin",
                is_active=True,
                is_email_verified=True,
            )
            session.add(user)
            await session.flush()
            admin_role = (await session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
            session.add(UserRole(user_id=user.id, role_id=admin_role.id))
            await session.commit()
            logger.info("[auth] Created bootstrap admin: %s", admin_email)
        else:
            # Make sure they have the admin role
            already = (await session.execute(
                select(UserRole).join(Role, Role.id == UserRole.role_id)
                .where(UserRole.user_id == existing.id, Role.name == "admin")
            )).scalar_one_or_none()
            if already is None:
                admin_role = (await session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
                session.add(UserRole(user_id=existing.id, role_id=admin_role.id))
                await session.commit()
                logger.info("[auth] Granted admin role to existing user %s", admin_email)


async def _ensure_workspace_stubs() -> None:
    """Make sure every workspace_id present in billing_usage has a Workspace
    row. Idempotent — only inserts the missing ones with workspace_name=NULL
    so the UI can show the id and admins can fill in names via the Database
    Explorer (UPDATE workspaces SET workspace_name=… WHERE workspace_id=…)."""
    from extract.ingest import backfill_workspace_stubs
    async with async_session() as session:
        added = await backfill_workspace_stubs(session)
        if added:
            await session.commit()
            logger.info("[workspaces] Backfilled %d stub rows", added)


async def _add_data_isolation_columns() -> None:
    """One-shot startup migration: ensure data_origin + deleted_at columns
    exist on every domain table. PG ≥ 9.6 supports ADD COLUMN IF NOT EXISTS,
    so this is idempotent and safe to run on every boot."""
    from sqlalchemy import text
    statements = [
        # billing_usage
        "ALTER TABLE billing_usage ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE billing_usage ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_billing_usage_data_origin ON billing_usage (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_billing_usage_deleted_at ON billing_usage (deleted_at)",
        # list_prices
        "ALTER TABLE list_prices ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE list_prices ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_list_prices_data_origin ON list_prices (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_list_prices_deleted_at ON list_prices (deleted_at)",
        # clusters
        "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_clusters_data_origin ON clusters (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_clusters_deleted_at ON clusters (deleted_at)",
        # warehouses
        "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_warehouses_data_origin ON warehouses (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_warehouses_deleted_at ON warehouses (deleted_at)",
        # jobs
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_jobs_data_origin ON jobs (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_jobs_deleted_at ON jobs (deleted_at)",
        # workspaces
        "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_workspaces_data_origin ON workspaces (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_workspaces_deleted_at ON workspaces (deleted_at)",
        # query_history
        "ALTER TABLE query_history ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE query_history ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_query_history_data_origin ON query_history (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_query_history_deleted_at ON query_history (deleted_at)",
        # auth_users — viewing_data_mode
        "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS viewing_data_mode VARCHAR(8) NOT NULL DEFAULT 'real'",
        # databricks_meta — Unity Catalog snapshot
        "ALTER TABLE databricks_meta ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE databricks_meta ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_databricks_meta_origin_deleted ON databricks_meta (data_origin, deleted_at)",
        # auth_roles — feature-grant matrix attached per role
        "ALTER TABLE auth_roles ADD COLUMN IF NOT EXISTS features JSON NULL",
        # feature_flags table is retired in favour of per-role feature grants
        "DROP TABLE IF EXISTS feature_flags",
        # table_lineage / column_lineage — both inherit the standard isolation columns
        "ALTER TABLE table_lineage  ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE table_lineage  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "ALTER TABLE column_lineage ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE column_lineage ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        # Schema-alignment columns added after initial lineage shipment.
        "ALTER TABLE table_lineage  ADD COLUMN IF NOT EXISTS metastore_id VARCHAR NULL",
        "ALTER TABLE table_lineage  ADD COLUMN IF NOT EXISTS record_id VARCHAR NULL",
        "ALTER TABLE table_lineage  ADD COLUMN IF NOT EXISTS event_id VARCHAR NULL",
        "ALTER TABLE table_lineage  ADD COLUMN IF NOT EXISTS direct_access BOOLEAN NULL",
        "ALTER TABLE table_lineage  ADD COLUMN IF NOT EXISTS entity_metadata JSON NULL",
        "CREATE INDEX IF NOT EXISTS ix_table_lineage_event_id ON table_lineage (event_id)",
        "CREATE INDEX IF NOT EXISTS ix_table_lineage_direct_access ON table_lineage (direct_access)",
        "ALTER TABLE column_lineage ADD COLUMN IF NOT EXISTS metastore_id VARCHAR NULL",
        "ALTER TABLE column_lineage ADD COLUMN IF NOT EXISTS record_id VARCHAR NULL",
        "ALTER TABLE column_lineage ADD COLUMN IF NOT EXISTS event_id VARCHAR NULL",
        "ALTER TABLE column_lineage ADD COLUMN IF NOT EXISTS direct_access BOOLEAN NULL",
        "ALTER TABLE column_lineage ADD COLUMN IF NOT EXISTS entity_metadata JSON NULL",
        "CREATE INDEX IF NOT EXISTS ix_column_lineage_event_id ON column_lineage (event_id)",
        # audit_events / assistant_events — inherit the standard isolation columns
        "ALTER TABLE audit_events     ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE audit_events     ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "ALTER TABLE assistant_events ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE assistant_events ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_audit_events_origin_deleted ON audit_events (data_origin, deleted_at)",
        "CREATE INDEX IF NOT EXISTS ix_assistant_events_origin_deleted ON assistant_events (data_origin, deleted_at)",
        # system.compute.* node_pool tables — same isolation pattern.
        "ALTER TABLE node_timeline    ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE node_timeline    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "ALTER TABLE warehouse_events ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE warehouse_events ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "ALTER TABLE node_types       ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE node_types       ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "ALTER TABLE instance_events  ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE instance_events  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        "ALTER TABLE instance_pools   ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE instance_pools   ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
        # qi_* — Query Profiler tables. Added data_origin so the ETL can
        # write both real and demo partitions side-by-side and run_qi can
        # filter by the caller's view-mode (see qi_runner._inject_view_mode).
        # No deleted_at — these are fully rebuilt per partition by every
        # ETL run, so soft-delete semantics don't apply.
        "ALTER TABLE qi_statements         ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE qi_statement_tables   ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE qi_statement_columns  ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE qi_statement_tags     ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE qi_statement_parameters ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "ALTER TABLE qi_statement_errors   ADD COLUMN IF NOT EXISTS data_origin VARCHAR(8) NOT NULL DEFAULT 'real'",
        "CREATE INDEX IF NOT EXISTS ix_qi_statements_data_origin         ON qi_statements         (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_qi_statement_tables_data_origin   ON qi_statement_tables   (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_qi_statement_columns_data_origin  ON qi_statement_columns  (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_qi_statement_tags_data_origin     ON qi_statement_tags     (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_qi_statement_parameters_data_origin ON qi_statement_parameters (data_origin)",
        "CREATE INDEX IF NOT EXISTS ix_qi_statement_errors_data_origin   ON qi_statement_errors   (data_origin)",
        # Upgrade qi_statements / qi_statement_errors PK from
        # (statement_id) → (statement_id, data_origin). Idempotent: only
        # runs the swap when the existing PK does NOT yet include
        # data_origin. Required so the demo and real partitions can hold
        # rows with the same statement_id without colliding — the symptom
        # was the demo ETL crashing with `duplicate key value violates
        # unique constraint qi_statements_pkey` on accounts that had
        # rows from a pre-`data_origin` ETL run.
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.table_constraints tc
                WHERE tc.table_name = 'qi_statements'
                  AND tc.constraint_type = 'PRIMARY KEY'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.key_column_usage kcu
                JOIN information_schema.table_constraints tc
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = 'qi_statements'
                  AND tc.constraint_type = 'PRIMARY KEY'
                  AND kcu.column_name = 'data_origin'
            ) THEN
                EXECUTE 'ALTER TABLE qi_statements DROP CONSTRAINT '
                        || (SELECT constraint_name FROM information_schema.table_constraints
                            WHERE table_name = 'qi_statements' AND constraint_type = 'PRIMARY KEY');
                ALTER TABLE qi_statements ADD PRIMARY KEY (statement_id, data_origin);
            END IF;
            IF EXISTS (
                SELECT 1
                FROM information_schema.table_constraints tc
                WHERE tc.table_name = 'qi_statement_errors'
                  AND tc.constraint_type = 'PRIMARY KEY'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.key_column_usage kcu
                JOIN information_schema.table_constraints tc
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = 'qi_statement_errors'
                  AND tc.constraint_type = 'PRIMARY KEY'
                  AND kcu.column_name = 'data_origin'
            ) THEN
                EXECUTE 'ALTER TABLE qi_statement_errors DROP CONSTRAINT '
                        || (SELECT constraint_name FROM information_schema.table_constraints
                            WHERE table_name = 'qi_statement_errors' AND constraint_type = 'PRIMARY KEY');
                ALTER TABLE qi_statement_errors ADD PRIMARY KEY (statement_id, data_origin);
            END IF;
        END $$
        """,
    ]
    async with async_session() as session:
        for stmt in statements:
            await session.execute(text(stmt))
        await session.commit()
    logger.info("[migration] data-isolation columns ensured on all domain tables.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle handler."""
    await init_db()
    await _add_data_isolation_columns()
    await _seed_auth_defaults()
    await _auto_populate()
    await _ensure_workspace_stubs()
    # Reap jobs that were 'running' when the container last died.
    from background_jobs import reap_orphan_jobs
    await reap_orphan_jobs()
    yield


app = FastAPI(
    title="Databricks Billing Analytics API",
    description=(
        "REST API for analyzing Databricks billing data. "
        "Supports live extraction from Databricks, parquet file ingestion, "
        "or demo seed data for development."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS -- allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)            # public: register, login, oauth
app.include_router(billing.router)
app.include_router(compute.router)
app.include_router(analytics.router)
app.include_router(sku_origin_router)
app.include_router(metadata_router)
app.include_router(chat.router)
app.include_router(admin_router)
app.include_router(query_intel_router)     # Query Intel scenarios
app.include_router(meta_explorer_router)   # Unity Catalog metadata browser
app.include_router(audit_router)           # system.access.audit + assistant_events dashboards
app.include_router(node_pool_router)       # system.compute.* node pool / instance telemetry
app.include_router(data_ops_router)        # data isolation, deletes, jobs, view-mode
app.include_router(admin_users_router)     # admin-only: user/role management
app.include_router(db_explorer_router)     # admin-only: postgres explorer
app.include_router(spark_sql_router)       # admin-only: Spark SQL editor over spark-warehouse
app.include_router(features_state_router)  # auth-only: per-user feature state computed from roles


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Basic health-check endpoint."""
    return HealthResponse(status="ok", version=app.version)
