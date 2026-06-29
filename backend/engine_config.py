"""Runtime engine configuration for the Query Intel pipeline.

Exposes a tiny API for the rest of the app to ask "are we on DuckDB or Spark?"
without needing to know about the SystemConfig table.

Two keys are stored in Postgres `system_config`:

  * ``query_intel_engine`` — `'duckdb'` (default) or `'spark'`.
  * ``spark_mode`` — only relevant when engine = `'spark'`. Values:
      - `'jdbc_views'` (default): base Postgres tables exposed as session
        temp views via JDBC. Reference unqualified. Fast to switch on/off.
      - `'materialized'`: base tables COPIED into `spark_catalog.default`
        as managed Delta tables in spark-warehouse. Reference with the
        3-part name `spark_catalog.default.<table>`. Faster reads, no
        Postgres round-trip — at the cost of a one-time copy.

Changing the engine / mode affects:
  * extract/query_intel.py — where qi_* gets written on extract.
  * routers/query_intel.py — where Query Intel pages read from.
  * routers/chat.py        — which dialect prompts + execution path.
  * routers/spark_sql.py   — what shows up in the Spark SQL Editor.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SystemConfig

EngineName = Literal["duckdb", "spark"]
DEFAULT_ENGINE: EngineName = "duckdb"
ENGINE_KEY = "query_intel_engine"

SparkMode = Literal["jdbc_views", "materialized"]
DEFAULT_SPARK_MODE: SparkMode = "jdbc_views"
SPARK_MODE_KEY = "spark_mode"


async def get_engine(db: AsyncSession) -> EngineName:
    """Return the active Query Intel engine ('duckdb' or 'spark').

    Falls back to 'duckdb' when the row is missing or has an unknown value
    so the app stays usable if Spark services aren't deployed.
    """
    row = (await db.execute(
        select(SystemConfig).where(SystemConfig.key == ENGINE_KEY)
    )).scalar_one_or_none()
    if row is None:
        return DEFAULT_ENGINE
    value = (row.value or "").strip().lower()
    return value if value in ("duckdb", "spark") else DEFAULT_ENGINE


async def set_engine(db: AsyncSession, engine: EngineName) -> EngineName:
    """Persist the active engine and return the stored value."""
    if engine not in ("duckdb", "spark"):
        raise ValueError(f"Unknown engine: {engine!r}; must be 'duckdb' or 'spark'.")
    row = (await db.execute(
        select(SystemConfig).where(SystemConfig.key == ENGINE_KEY)
    )).scalar_one_or_none()
    if row is None:
        db.add(SystemConfig(key=ENGINE_KEY, value=engine))
    else:
        row.value = engine
    await db.commit()
    return engine


async def get_spark_mode(db: AsyncSession) -> SparkMode:
    """Return the active Spark sub-mode ('jdbc_views' or 'materialized').

    Only meaningful when engine=='spark'. Falls back to 'jdbc_views' on
    missing / unknown values so the app stays in the cheaper-to-revert
    configuration by default.
    """
    row = (await db.execute(
        select(SystemConfig).where(SystemConfig.key == SPARK_MODE_KEY)
    )).scalar_one_or_none()
    if row is None:
        return DEFAULT_SPARK_MODE
    value = (row.value or "").strip().lower()
    return value if value in ("jdbc_views", "materialized") else DEFAULT_SPARK_MODE


async def set_spark_mode(db: AsyncSession, mode: SparkMode) -> SparkMode:
    """Persist the active Spark sub-mode and return the stored value.

    Switching modes does NOT copy data — the actual copy is triggered by
    POST /api/admin/materialize-postgres-to-spark. Switching `materialized`
    → `jdbc_views` simply re-registers the JDBC temp views and stops
    relying on the materialised Delta tables.
    """
    if mode not in ("jdbc_views", "materialized"):
        raise ValueError(f"Unknown spark_mode: {mode!r}; must be 'jdbc_views' or 'materialized'.")
    row = (await db.execute(
        select(SystemConfig).where(SystemConfig.key == SPARK_MODE_KEY)
    )).scalar_one_or_none()
    if row is None:
        db.add(SystemConfig(key=SPARK_MODE_KEY, value=mode))
    else:
        row.value = mode
    await db.commit()
    return mode
