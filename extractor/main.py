"""FastAPI surface for the Databricks extractor worker.

Endpoints:
  GET  /health        — liveness probe
  GET  /info          — show configured target (host, profile) without secrets
  POST /extract       — synchronous extract; returns the parquet paths written
                        and per-table row counts for the backend to ingest.

The backend service is the only intended client; this service has no
auth of its own (it lives on the docker-network and isn't exposed to
the host). If you ever bind it to a public port, put a token on it.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from groups import ALL_GROUPS, GROUPS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("extractor")

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Databricks Extractor",
    description="Isolated extraction worker. Pulls SQL from Databricks via databricks-connect, writes parquet snapshots to the shared data volume.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    mode: str = Field("full", description="'full' or 'incremental' — for query_history only (overrides start_date).")
    start_date: str = Field("2024-01-01", description="YYYY-MM-DD lower bound (usage + query_history).")
    end_date: Optional[str] = Field(None, description="YYYY-MM-DD upper bound (defaults to today).")
    groups: Optional[list[str]] = Field(None, description="Subset of 'billing'/'compute'/'query_history'/'meta'/'lineage'. None = all.")
    save_parquet: bool = True
    # Lineage tables can have tens of millions of rows over a wide window —
    # they're sliced on a much shorter window than billing/query_history and
    # the two tables get separate budgets because column_lineage is typically
    # 3-5x the volume of table_lineage.
    table_lineage_days_back: int = Field(
        14, ge=1, le=365,
        description="Lookback (days) for system.access.table_lineage. Default 14.",
    )
    column_lineage_days_back: int = Field(
        7, ge=1, le=365,
        description="Lookback (days) for system.access.column_lineage. Default 7.",
    )
    # Per-table lookbacks for the `audit` and `node_pool` groups. Audit
    # events and node_timeline are the high-cardinality ones; the others
    # are event logs / reference tables and can afford a wider window.
    audit_events_days_back: int = Field(
        3, ge=1, le=365,
        description="Lookback (days) for system.access.audit. Default 3 — audit is the highest-cardinality system.access table and a wide window can OOM the connect driver.",
    )
    assistant_events_days_back: int = Field(
        30, ge=1, le=365,
        description="Lookback (days) for system.access.assistant_events. Default 30 — low-volume (user-submitted prompts only), so a longer window is safe.",
    )
    node_timeline_days_back: int = Field(
        3, ge=1, le=365,
        description="Lookback (days) for system.compute.node_timeline. Default 3 — per-minute-per-instance utilization, the heaviest compute table.",
    )
    warehouse_events_days_back: int = Field(
        30, ge=1, le=365,
        description="Lookback (days) for system.compute.warehouse_events. Default 30 — modest event volume.",
    )
    instance_events_days_back: int = Field(
        14, ge=1, le=365,
        description="Lookback (days) for system.compute.node_events (surfaced as instance_events). Default 14 — modest event volume.",
    )


class ExtractResponse(BaseModel):
    tables_written: list[str] = Field(description="Tables for which a fresh parquet snapshot was written.")
    row_counts: dict[str, int] = Field(description="Row count per table extracted.")
    parquet_paths: dict[str, str] = Field(description="Container-relative paths of the written parquet files.")
    duration_seconds: float
    target: str = Field(description="Databricks host the extraction connected to.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"ok": True, "data_dir": DATA_DIR}


@app.get("/info")
def info() -> dict:
    return {
        "databricks_host": os.getenv("DATABRICKS_HOST"),
        "databricks_token_set": bool(os.getenv("DATABRICKS_TOKEN")),
        "data_dir": DATA_DIR,
        "groups": {g: list(GROUPS[g]) for g in ALL_GROUPS},
    }


@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest) -> ExtractResponse:
    if req.mode not in ("full", "incremental"):
        raise HTTPException(status_code=400, detail="mode must be 'full' or 'incremental'")
    selected = [g for g in (req.groups or list(ALL_GROUPS)) if g in GROUPS]
    if not selected:
        raise HTTPException(
            status_code=400,
            detail=f"groups must contain at least one of: {list(ALL_GROUPS)}",
        )

    host = os.getenv("DATABRICKS_HOST")
    if not host:
        raise HTTPException(
            status_code=400,
            detail="DATABRICKS_HOST is not set on the extractor service.",
        )

    # Local imports keep startup fast — databricks-connect's first import is
    # ~1.5s. If the user never hits /extract we don't pay that cost.
    from databricks_extractor import extract_all, get_databricks_session

    t0 = time.time()
    try:
        spark = get_databricks_session(host=host, token=os.getenv("DATABRICKS_TOKEN"))
    except Exception as e:
        logger.exception("Failed to open DatabricksSession")
        raise HTTPException(status_code=500, detail=f"Could not connect to Databricks: {e}")

    end_date = req.end_date or datetime.now().strftime("%Y-%m-%d")
    try:
        dataframes, paths = extract_all(
            spark,
            start_date=req.start_date,
            end_date=end_date,
            output_dir=DATA_DIR,
            save_parquet=req.save_parquet,
            groups=selected,
            table_lineage_days_back=req.table_lineage_days_back,
            column_lineage_days_back=req.column_lineage_days_back,
            audit_events_days_back=req.audit_events_days_back,
            assistant_events_days_back=req.assistant_events_days_back,
            node_timeline_days_back=req.node_timeline_days_back,
            warehouse_events_days_back=req.warehouse_events_days_back,
            instance_events_days_back=req.instance_events_days_back,
        )
    except Exception as e:
        logger.exception("extract_all failed")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")
    finally:
        try:
            spark.stop()
        except Exception:
            pass

    row_counts = {name: int(len(df)) for name, df in dataframes.items()}
    return ExtractResponse(
        tables_written=list(dataframes.keys()),
        row_counts=row_counts,
        parquet_paths=paths,
        duration_seconds=round(time.time() - t0, 2),
        target=host,
    )
