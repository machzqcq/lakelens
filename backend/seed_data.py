"""
Seed data generator for Databricks billing analysis app.

Generates ~12 months of realistic billing usage records (2025-05-01 to 2026-04-09)
with weekday/weekend patterns, monthly growth, and seasonal spikes.

Usage:
    from seed_data import seed_database
    await seed_database(async_session)
"""

import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import BillingUsage, ListPrice, Cluster, Warehouse, Job, Workspace

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = "a]1b2c3d4-e5f6-7890-abcd-ef1234567890"

# Rolling window — seed data always ends "today" and goes back roughly a
# year. Hardcoding fixed dates (e.g. 2026-04-09) meant the seed silently
# stopped overlapping the dashboard's default "last 30 days" window as
# time marched on, so users saw an empty chart on every fresh boot. The
# `today()` call below resolves at import time, which is fine because
# the module reloads with every backend container restart.
DATE_END = date.today()
DATE_START = DATE_END - timedelta(days=365)

SKU_PRICES: dict[str, float] = {
    "STANDARD_ALL_PURPOSE_COMPUTE": 0.40,
    "PREMIUM_ALL_PURPOSE_COMPUTE": 0.55,
    "STANDARD_JOBS_COMPUTE": 0.15,
    "PREMIUM_JOBS_COMPUTE": 0.30,
    "STANDARD_SQL_COMPUTE": 0.22,
    "PREMIUM_SQL_COMPUTE": 0.55,
    "SERVERLESS_SQL_COMPUTE": 0.70,
    "SERVERLESS_REAL_TIME_INFERENCE": 0.07,
    "STANDARD_DLT_CORE_COMPUTE": 0.20,
    "PREMIUM_DLT_CORE_COMPUTE": 0.36,
    "PREMIUM_DLT_ADVANCED_COMPUTE": 0.54,
    "ENTERPRISE_ALL_PURPOSE_COMPUTE": 0.65,
    "ENTERPRISE_JOBS_COMPUTE": 0.40,
    "ENTERPRISE_SQL_COMPUTE": 0.70,
}

WORKSPACES: list[dict] = [
    {"workspace_id": "ws-001", "workspace_name": "Data Engineering Prod"},
    {"workspace_id": "ws-002", "workspace_name": "Data Science Research"},
    {"workspace_id": "ws-003", "workspace_name": "Analytics Reporting"},
    {"workspace_id": "ws-004", "workspace_name": "ML Platform"},
    {"workspace_id": "ws-005", "workspace_name": "ETL Development"},
]

# Cloud distribution: AZURE 85%, AWS 15%
CLOUDS = ["AZURE"] * 85 + ["AWS"] * 15

# Billing origin product weights
BILLING_ORIGIN_PRODUCTS = {
    "JOBS": 35,
    "SQL": 25,
    "ALL_PURPOSE": 20,
    "DLT": 10,
    "SERVING": 5,
    "SERVERLESS": 5,
}
_PRODUCT_POOL: list[str] = []
for prod, weight in BILLING_ORIGIN_PRODUCTS.items():
    _PRODUCT_POOL.extend([prod] * weight)

# Usage type weights
USAGE_TYPES = {
    "COMPUTE_TIME": 70,
    "STORAGE_SPACE": 15,
    "NETWORK_BYTES": 8,
    "TOKEN": 5,
    "GPU_TIME": 2,
}
_USAGE_TYPE_POOL: list[str] = []
for ut, weight in USAGE_TYPES.items():
    _USAGE_TYPE_POOL.extend([ut] * weight)

# SKU -> billing origin product mapping (for realistic combinations)
SKU_TO_PRODUCT: dict[str, str] = {
    "STANDARD_ALL_PURPOSE_COMPUTE": "ALL_PURPOSE",
    "PREMIUM_ALL_PURPOSE_COMPUTE": "ALL_PURPOSE",
    "ENTERPRISE_ALL_PURPOSE_COMPUTE": "ALL_PURPOSE",
    "STANDARD_JOBS_COMPUTE": "JOBS",
    "PREMIUM_JOBS_COMPUTE": "JOBS",
    "ENTERPRISE_JOBS_COMPUTE": "JOBS",
    "STANDARD_SQL_COMPUTE": "SQL",
    "PREMIUM_SQL_COMPUTE": "SQL",
    "ENTERPRISE_SQL_COMPUTE": "SQL",
    "SERVERLESS_SQL_COMPUTE": "SERVERLESS",
    "SERVERLESS_REAL_TIME_INFERENCE": "SERVING",
    "STANDARD_DLT_CORE_COMPUTE": "DLT",
    "PREMIUM_DLT_CORE_COMPUTE": "DLT",
    "PREMIUM_DLT_ADVANCED_COMPUTE": "DLT",
}

# Weighted SKU selection (Jobs-heavy)
SKU_WEIGHTS: dict[str, int] = {
    "STANDARD_JOBS_COMPUTE": 15,
    "PREMIUM_JOBS_COMPUTE": 20,
    "ENTERPRISE_JOBS_COMPUTE": 8,
    "STANDARD_SQL_COMPUTE": 8,
    "PREMIUM_SQL_COMPUTE": 10,
    "ENTERPRISE_SQL_COMPUTE": 5,
    "SERVERLESS_SQL_COMPUTE": 5,
    "STANDARD_ALL_PURPOSE_COMPUTE": 6,
    "PREMIUM_ALL_PURPOSE_COMPUTE": 8,
    "ENTERPRISE_ALL_PURPOSE_COMPUTE": 3,
    "STANDARD_DLT_CORE_COMPUTE": 4,
    "PREMIUM_DLT_CORE_COMPUTE": 3,
    "PREMIUM_DLT_ADVANCED_COMPUTE": 2,
    "SERVERLESS_REAL_TIME_INFERENCE": 3,
}
_SKU_POOL: list[str] = []
for sku, weight in SKU_WEIGHTS.items():
    _SKU_POOL.extend([sku] * weight)

# Clusters
CLUSTERS: list[dict] = [
    {"cluster_id": "clst-0001", "cluster_name": "etl-daily-pipeline", "workspace_id": "ws-001",
     "driver_node_type": "Standard_DS3_v2", "worker_node_type": "Standard_DS3_v2",
     "worker_count": 4, "min_autoscale_workers": 2, "max_autoscale_workers": 8,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0002", "cluster_name": "ml-training-gpu", "workspace_id": "ws-004",
     "driver_node_type": "Standard_NC6s_v3", "worker_node_type": "Standard_NC6s_v3",
     "worker_count": 2, "min_autoscale_workers": 1, "max_autoscale_workers": 4,
     "dbr_version": "14.3.x-gpu-ml-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0003", "cluster_name": "adhoc-analytics", "workspace_id": "ws-003",
     "driver_node_type": "Standard_DS4_v2", "worker_node_type": "Standard_DS4_v2",
     "worker_count": 2, "min_autoscale_workers": 1, "max_autoscale_workers": 6,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "UI", "data_security_mode": "USER_ISOLATION"},
    {"cluster_id": "clst-0004", "cluster_name": "streaming-ingest", "workspace_id": "ws-001",
     "driver_node_type": "Standard_DS3_v2", "worker_node_type": "Standard_DS3_v2",
     "worker_count": 3, "min_autoscale_workers": 2, "max_autoscale_workers": 6,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0005", "cluster_name": "feature-engineering", "workspace_id": "ws-004",
     "driver_node_type": "Standard_DS4_v2", "worker_node_type": "Standard_DS4_v2",
     "worker_count": 4, "min_autoscale_workers": 2, "max_autoscale_workers": 10,
     "dbr_version": "14.3.x-ml-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0006", "cluster_name": "data-quality-checks", "workspace_id": "ws-001",
     "driver_node_type": "Standard_DS3_v2", "worker_node_type": "Standard_DS3_v2",
     "worker_count": 2, "min_autoscale_workers": 1, "max_autoscale_workers": 4,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0007", "cluster_name": "report-generation", "workspace_id": "ws-003",
     "driver_node_type": "Standard_DS3_v2", "worker_node_type": "Standard_DS3_v2",
     "worker_count": 2, "min_autoscale_workers": 1, "max_autoscale_workers": 4,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0008", "cluster_name": "dev-sandbox", "workspace_id": "ws-005",
     "driver_node_type": "Standard_DS3_v2", "worker_node_type": "Standard_DS3_v2",
     "worker_count": 1, "min_autoscale_workers": 1, "max_autoscale_workers": 2,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "UI", "data_security_mode": "USER_ISOLATION"},
    {"cluster_id": "clst-0009", "cluster_name": "dlt-bronze-silver", "workspace_id": "ws-001",
     "driver_node_type": "Standard_DS4_v2", "worker_node_type": "Standard_DS4_v2",
     "worker_count": 4, "min_autoscale_workers": 2, "max_autoscale_workers": 8,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "PIPELINE", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0010", "cluster_name": "dlt-gold-aggregates", "workspace_id": "ws-001",
     "driver_node_type": "Standard_DS3_v2", "worker_node_type": "Standard_DS3_v2",
     "worker_count": 3, "min_autoscale_workers": 2, "max_autoscale_workers": 6,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "PIPELINE", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0011", "cluster_name": "nlp-inference", "workspace_id": "ws-004",
     "driver_node_type": "Standard_NC6s_v3", "worker_node_type": "Standard_NC6s_v3",
     "worker_count": 1, "min_autoscale_workers": 1, "max_autoscale_workers": 3,
     "dbr_version": "14.3.x-gpu-ml-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0012", "cluster_name": "batch-scoring", "workspace_id": "ws-004",
     "driver_node_type": "Standard_DS4_v2", "worker_node_type": "Standard_DS4_v2",
     "worker_count": 4, "min_autoscale_workers": 2, "max_autoscale_workers": 8,
     "dbr_version": "14.3.x-ml-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0013", "cluster_name": "cost-optimization-test", "workspace_id": "ws-005",
     "driver_node_type": "Standard_DS3_v2", "worker_node_type": "Standard_DS3_v2",
     "worker_count": 1, "min_autoscale_workers": 1, "max_autoscale_workers": 2,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "UI", "data_security_mode": "USER_ISOLATION"},
    {"cluster_id": "clst-0014", "cluster_name": "data-migration", "workspace_id": "ws-001",
     "driver_node_type": "Standard_DS5_v2", "worker_node_type": "Standard_DS5_v2",
     "worker_count": 6, "min_autoscale_workers": 4, "max_autoscale_workers": 12,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "JOB", "data_security_mode": "SINGLE_USER"},
    {"cluster_id": "clst-0015", "cluster_name": "interactive-exploration", "workspace_id": "ws-002",
     "driver_node_type": "Standard_DS4_v2", "worker_node_type": "Standard_DS4_v2",
     "worker_count": 2, "min_autoscale_workers": 1, "max_autoscale_workers": 4,
     "dbr_version": "14.3.x-scala2.12", "cluster_source": "UI", "data_security_mode": "USER_ISOLATION"},
]

# Warehouses
WAREHOUSES: list[dict] = [
    {"warehouse_id": "wh-0001", "warehouse_name": "reporting-warehouse", "warehouse_type": "PRO",
     "warehouse_size": "MEDIUM", "workspace_id": "ws-003", "min_clusters": 1, "max_clusters": 4, "auto_stop_minutes": 15},
    {"warehouse_id": "wh-0002", "warehouse_name": "bi-dashboard-wh", "warehouse_type": "PRO",
     "warehouse_size": "LARGE", "workspace_id": "ws-003", "min_clusters": 1, "max_clusters": 6, "auto_stop_minutes": 10},
    {"warehouse_id": "wh-0003", "warehouse_name": "adhoc-query-wh", "warehouse_type": "CLASSIC",
     "warehouse_size": "SMALL", "workspace_id": "ws-002", "min_clusters": 1, "max_clusters": 2, "auto_stop_minutes": 30},
    {"warehouse_id": "wh-0004", "warehouse_name": "etl-sql-wh", "warehouse_type": "PRO",
     "warehouse_size": "X_LARGE", "workspace_id": "ws-001", "min_clusters": 2, "max_clusters": 8, "auto_stop_minutes": 10},
    {"warehouse_id": "wh-0005", "warehouse_name": "serverless-analytics", "warehouse_type": "SERVERLESS",
     "warehouse_size": "MEDIUM", "workspace_id": "ws-003", "min_clusters": 1, "max_clusters": 10, "auto_stop_minutes": 5},
    {"warehouse_id": "wh-0006", "warehouse_name": "dev-testing-wh", "warehouse_type": "CLASSIC",
     "warehouse_size": "X_SMALL", "workspace_id": "ws-005", "min_clusters": 1, "max_clusters": 1, "auto_stop_minutes": 60},
    {"warehouse_id": "wh-0007", "warehouse_name": "ml-feature-serving", "warehouse_type": "SERVERLESS",
     "warehouse_size": "SMALL", "workspace_id": "ws-004", "min_clusters": 1, "max_clusters": 4, "auto_stop_minutes": 10},
    {"warehouse_id": "wh-0008", "warehouse_name": "finance-reporting-wh", "warehouse_type": "PRO",
     "warehouse_size": "LARGE", "workspace_id": "ws-003", "min_clusters": 1, "max_clusters": 4, "auto_stop_minutes": 15},
]

# Jobs
JOBS: list[dict] = [
    {"job_id": "job-0001", "name": "daily_etl_pipeline", "workspace_id": "ws-001", "schedule": "0 2 * * *"},
    {"job_id": "job-0002", "name": "ml_model_training", "workspace_id": "ws-004", "schedule": "0 6 * * 1"},
    {"job_id": "job-0003", "name": "report_generation", "workspace_id": "ws-003", "schedule": "0 7 * * 1-5"},
    {"job_id": "job-0004", "name": "data_quality_monitor", "workspace_id": "ws-001", "schedule": "0 3 * * *"},
    {"job_id": "job-0005", "name": "feature_store_refresh", "workspace_id": "ws-004", "schedule": "0 4 * * *"},
    {"job_id": "job-0006", "name": "batch_inference_scoring", "workspace_id": "ws-004", "schedule": "0 8 * * *"},
    {"job_id": "job-0007", "name": "dlt_bronze_ingestion", "workspace_id": "ws-001", "schedule": "*/30 * * * *"},
    {"job_id": "job-0008", "name": "dlt_silver_transform", "workspace_id": "ws-001", "schedule": "0 * * * *"},
    {"job_id": "job-0009", "name": "dlt_gold_aggregation", "workspace_id": "ws-001", "schedule": "0 5 * * *"},
    {"job_id": "job-0010", "name": "customer_churn_prediction", "workspace_id": "ws-004", "schedule": "0 9 * * 1"},
    {"job_id": "job-0011", "name": "sales_dashboard_refresh", "workspace_id": "ws-003", "schedule": "0 6 * * 1-5"},
    {"job_id": "job-0012", "name": "log_archive_cleanup", "workspace_id": "ws-001", "schedule": "0 1 * * 0"},
    {"job_id": "job-0013", "name": "ab_test_analysis", "workspace_id": "ws-002", "schedule": "0 10 * * 1-5"},
    {"job_id": "job-0014", "name": "data_catalog_sync", "workspace_id": "ws-001", "schedule": "0 0 * * *"},
    {"job_id": "job-0015", "name": "cost_usage_report", "workspace_id": "ws-003", "schedule": "0 8 1 * *"},
    {"job_id": "job-0016", "name": "streaming_checkpoint_compact", "workspace_id": "ws-001", "schedule": "0 2 * * 0"},
    {"job_id": "job-0017", "name": "nlp_text_extraction", "workspace_id": "ws-004", "schedule": "0 3 * * 1-5"},
    {"job_id": "job-0018", "name": "dev_integration_tests", "workspace_id": "ws-005", "schedule": "0 22 * * 1-5"},
    {"job_id": "job-0019", "name": "weekly_data_export", "workspace_id": "ws-001", "schedule": "0 4 * * 5"},
    {"job_id": "job-0020", "name": "anomaly_detection_pipeline", "workspace_id": "ws-004", "schedule": "0 */6 * * *"},
]

USERS: list[str] = [
    "pradeep.macharla@company.com",
    "sarah.chen@company.com",
    "james.wilson@company.com",
    "maria.garcia@company.com",
    "david.kumar@company.com",
    "lisa.johnson@company.com",
    "michael.zhang@company.com",
    "emily.brown@company.com",
    "raj.patel@company.com",
    "anna.kowalski@company.com",
]

# Node types for clusters
NODE_TYPES = [
    "Standard_DS3_v2",
    "Standard_DS4_v2",
    "Standard_DS5_v2",
    "Standard_NC6s_v3",
    "Standard_E4ds_v4",
    "Standard_L8s_v2",
    "i3.xlarge",
    "m5.2xlarge",
]

# Quarter-end months for seasonal spikes
QUARTER_END_MONTHS = {6, 9, 12, 3}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _months_since_start(d: date) -> float:
    """Return fractional months elapsed since DATE_START."""
    return (d.year - DATE_START.year) * 12 + (d.month - DATE_START.month) + (d.day / 30.0)


def _daily_record_count(d: date) -> int:
    """Determine how many usage records to generate for a given date."""
    base = random.randint(50, 100)

    # Weekend reduction
    if d.weekday() >= 5:
        base = base // random.randint(2, 3)

    # Monthly growth: ~5% compounding per month
    months = _months_since_start(d)
    growth_factor = 1.05 ** months
    base = int(base * growth_factor)

    # Quarter-end spike: +20-40%
    if d.month in QUARTER_END_MONTHS and d.day >= 20:
        base = int(base * random.uniform(1.20, 1.40))

    return max(base, 10)


def _pick_sku() -> str:
    return random.choice(_SKU_POOL)


def _pick_usage_type() -> str:
    return random.choice(_USAGE_TYPE_POOL)


def _pick_workspace() -> dict:
    return random.choice(WORKSPACES)


def _pick_cloud() -> str:
    return random.choice(CLOUDS)


def _pick_cluster(ws_id: str) -> Optional[dict]:
    candidates = [c for c in CLUSTERS if c["workspace_id"] == ws_id]
    if not candidates:
        candidates = CLUSTERS
    return random.choice(candidates)


def _pick_warehouse(ws_id: str) -> Optional[dict]:
    candidates = [w for w in WAREHOUSES if w["workspace_id"] == ws_id]
    if not candidates:
        candidates = WAREHOUSES
    return random.choice(candidates)


def _pick_job(ws_id: str) -> Optional[dict]:
    candidates = [j for j in JOBS if j["workspace_id"] == ws_id]
    if not candidates:
        candidates = JOBS
    return random.choice(candidates)


def _usage_quantity_for_type(usage_type: str) -> float:
    """Generate a realistic usage quantity based on usage type."""
    if usage_type == "COMPUTE_TIME":
        return round(random.uniform(1.0, 500.0), 4)
    elif usage_type == "STORAGE_SPACE":
        return round(random.uniform(0.5, 50.0), 4)
    elif usage_type == "NETWORK_BYTES":
        return round(random.uniform(0.5, 30.0), 4)
    elif usage_type == "TOKEN":
        return round(random.uniform(0.5, 100.0), 4)
    elif usage_type == "GPU_TIME":
        return round(random.uniform(5.0, 300.0), 4)
    return round(random.uniform(0.5, 500.0), 4)


def _generate_usage_record(usage_date: date) -> dict:
    """Build a single BillingUsage row dict for the given date."""
    ws = _pick_workspace()
    sku_name = _pick_sku()
    billing_origin_product = SKU_TO_PRODUCT[sku_name]
    usage_type = _pick_usage_type()
    cloud = _pick_cloud()
    usage_qty = _usage_quantity_for_type(usage_type)
    price = SKU_PRICES[sku_name]

    # Time window: random start hour, 1-8 hour duration
    start_hour = random.randint(0, 23)
    start_minute = random.choice([0, 15, 30, 45])
    duration_hours = random.randint(1, 8)
    usage_start = datetime(usage_date.year, usage_date.month, usage_date.day,
                           start_hour, start_minute, 0)
    usage_end = usage_start + timedelta(hours=duration_hours)

    # Determine associated resource
    cluster_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    job_id: Optional[str] = None
    run_name: Optional[str] = None
    node_type: Optional[str] = None
    run_as: Optional[str] = random.choice(USERS)

    if billing_origin_product in ("JOBS", "DLT"):
        cluster = _pick_cluster(ws["workspace_id"])
        cluster_id = cluster["cluster_id"]
        node_type = cluster["worker_node_type"]
        job = _pick_job(ws["workspace_id"])
        job_id = job["job_id"]
        run_name = job["name"]
    elif billing_origin_product in ("SQL", "SERVERLESS"):
        warehouse = _pick_warehouse(ws["workspace_id"])
        warehouse_id = warehouse["warehouse_id"]
    elif billing_origin_product == "ALL_PURPOSE":
        cluster = _pick_cluster(ws["workspace_id"])
        cluster_id = cluster["cluster_id"]
        node_type = cluster["worker_node_type"]
    elif billing_origin_product == "SERVING":
        node_type = random.choice(NODE_TYPES[:4])

    # Derive product_features from SKU name
    is_serverless = "SERVERLESS" in sku_name
    is_photon = billing_origin_product in ("SQL", "SERVERLESS") or random.random() < 0.3
    jobs_tier = sku_name.split("_")[0] if billing_origin_product == "JOBS" else None
    sql_tier = sku_name.split("_")[0] if billing_origin_product in ("SQL", "SERVERLESS") else None
    dlt_tier = sku_name.split("_")[0] if billing_origin_product == "DLT" else None
    serving_type = "MODEL_SERVING" if billing_origin_product == "SERVING" else None

    # Pre-compute usage_usd the same way the Databricks USAGE_QUERY does:
    # quantity * effective_list_price. The seed knows the SKU price, so we
    # multiply directly here instead of joining list_prices at insert time.
    # Without this every dashboard tile that sums `usage_usd` reads 0 even
    # though `usage_quantity` is correct — that's the "5.3M DBUs but $0
    # total cost" symptom users saw on first boot.
    usage_usd = Decimal(str(usage_qty)) * Decimal(str(price))

    return {
        "account_id": ACCOUNT_ID,
        "workspace_id": ws["workspace_id"],
        "record_id": str(uuid.uuid4()),
        "sku_name": sku_name,
        "cloud": cloud,
        "usage_start_time": usage_start,
        "usage_end_time": usage_end,
        "usage_date": usage_date,
        "usage_unit": "DBU",
        "usage_quantity": Decimal(str(usage_qty)),
        "billing_origin_product": billing_origin_product,
        "usage_type": usage_type,
        "record_type": "ORIGINAL",
        "ingestion_date": usage_date,
        "cluster_id": cluster_id,
        "warehouse_id": warehouse_id,
        "instance_pool_id": None,
        "node_type": node_type,
        "job_id": job_id,
        "run_name": run_name,
        "run_as": run_as,
        "jobs_tier": jobs_tier,
        "sql_tier": sql_tier,
        "dlt_tier": dlt_tier,
        "is_serverless": is_serverless,
        "is_photon": is_photon,
        "serving_type": serving_type,
        "usage_usd": usage_usd,
        # Every seed row is synthetic / demo. Stamp the partition explicitly
        # so the view-mode toggle works as expected — without this every
        # seeded row defaulted to 'real' and the Demo view showed nothing.
        "data_origin": "demo",
    }


# ---------------------------------------------------------------------------
# Seeding functions
# ---------------------------------------------------------------------------

BATCH_SIZE = 2000


async def _seed_list_prices(session: AsyncSession) -> None:
    """Insert list price rows for every SKU."""
    print("[seed] Inserting list prices ...")
    rows = []
    effective = datetime(2025, 1, 1)
    for sku_name, price in SKU_PRICES.items():
        for cloud in ("AZURE", "AWS"):
            rows.append(ListPrice(
                account_id=ACCOUNT_ID,
                sku_name=sku_name,
                cloud=cloud,
                currency_code="USD",
                usage_unit="DBU",
                price_start_time=effective,
                price_end_time=None,
                default_price=Decimal(str(price)),
                effective_list_price=Decimal(str(price)),
                data_origin="demo",
            ))
    session.add_all(rows)
    await session.flush()
    print(f"[seed]   -> {len(rows)} list price rows inserted.")


async def _seed_clusters(session: AsyncSession) -> None:
    """Insert cluster rows."""
    print("[seed] Inserting clusters ...")
    rows = []
    for c in CLUSTERS:
        rows.append(Cluster(
            account_id=ACCOUNT_ID,
            workspace_id=c["workspace_id"],
            cluster_id=c["cluster_id"],
            cluster_name=c["cluster_name"],
            owned_by=random.choice(USERS),
            driver_node_type=c["driver_node_type"],
            worker_node_type=c["worker_node_type"],
            worker_count=c["worker_count"],
            min_autoscale_workers=c["min_autoscale_workers"],
            max_autoscale_workers=c["max_autoscale_workers"],
            dbr_version=c["dbr_version"],
            cluster_source=c["cluster_source"],
            data_security_mode=c["data_security_mode"],
            create_time=datetime(2025, 4, 1),
            data_origin="demo",
        ))
    session.add_all(rows)
    await session.flush()
    print(f"[seed]   -> {len(rows)} cluster rows inserted.")


async def _seed_warehouses(session: AsyncSession) -> None:
    """Insert warehouse rows."""
    print("[seed] Inserting warehouses ...")
    rows = []
    for w in WAREHOUSES:
        rows.append(Warehouse(
            account_id=ACCOUNT_ID,
            workspace_id=w["workspace_id"],
            warehouse_id=w["warehouse_id"],
            warehouse_name=w["warehouse_name"],
            warehouse_type=w["warehouse_type"],
            warehouse_size=w["warehouse_size"],
            min_clusters=w["min_clusters"],
            max_clusters=w["max_clusters"],
            auto_stop_minutes=w["auto_stop_minutes"],
            created_by=random.choice(USERS),
            data_origin="demo",
        ))
    session.add_all(rows)
    await session.flush()
    print(f"[seed]   -> {len(rows)} warehouse rows inserted.")


async def _seed_jobs(session: AsyncSession) -> None:
    """Insert job rows."""
    print("[seed] Inserting jobs ...")
    rows = []
    for j in JOBS:
        rows.append(Job(
            account_id=ACCOUNT_ID,
            workspace_id=j["workspace_id"],
            job_id=j["job_id"],
            name=j["name"],
            creator_id=random.choice(USERS),
            run_as=random.choice(USERS),
            data_origin="demo",
        ))
    session.add_all(rows)
    await session.flush()
    print(f"[seed]   -> {len(rows)} job rows inserted.")


async def _seed_billing_usage(session: AsyncSession) -> None:
    """Generate and bulk-insert daily billing usage records."""
    print("[seed] Generating billing usage records ...")

    current = DATE_START
    total_inserted = 0
    batch: list[BillingUsage] = []

    while current <= DATE_END:
        n_records = _daily_record_count(current)
        for _ in range(n_records):
            row_dict = _generate_usage_record(current)
            batch.append(BillingUsage(**row_dict))

        current += timedelta(days=1)

        # Flush in batches for performance
        if len(batch) >= BATCH_SIZE:
            session.add_all(batch)
            await session.flush()
            total_inserted += len(batch)
            if total_inserted % 5000 < BATCH_SIZE:
                print(f"[seed]   -> {total_inserted:,} usage records inserted ...")
            batch = []

    # Final remaining batch
    if batch:
        session.add_all(batch)
        await session.flush()
        total_inserted += len(batch)

    print(f"[seed]   -> {total_inserted:,} total billing usage records inserted.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def _seed_workspaces(session: AsyncSession) -> None:
    print(f"[seed] Seeding {len(WORKSPACES)} workspaces ...")
    session.add_all([
        Workspace(
            workspace_id=w["workspace_id"],
            workspace_name=w["workspace_name"],
            status="ACTIVE",
            data_origin="demo",
        )
        for w in WORKSPACES
    ])


async def seed_database(session: AsyncSession) -> None:
    """
    Populate the database with realistic sample Databricks billing data.

    Checks whether data already exists and skips seeding if so.
    """
    # Guard: skip if data already exists
    result = await session.execute(select(func.count()).select_from(BillingUsage))
    existing_count = result.scalar() or 0
    if existing_count > 0:
        print(f"[seed] Database already contains {existing_count:,} billing usage records. Skipping seed.")
        return

    print("[seed] ============================================")
    print("[seed] Starting database seed ...")
    print(f"[seed] Date range: {DATE_START} to {DATE_END}")
    print("[seed] ============================================")

    random.seed(42)  # reproducible data

    await _seed_workspaces(session)
    await _seed_list_prices(session)
    await _seed_clusters(session)
    await _seed_warehouses(session)
    await _seed_jobs(session)
    await _seed_billing_usage(session)

    await session.commit()

    print("[seed] ============================================")
    print("[seed] Seed complete!")
    print("[seed] ============================================")
