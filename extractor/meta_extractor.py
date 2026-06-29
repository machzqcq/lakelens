"""Unity Catalog metadata extractor.

Mirrors the logic in `db_helpers.get_meta_info_optimized` from the
`1. extract_meta_from_db.ipynb` notebook. For each accessible catalog,
joins INFORMATION_SCHEMA.COLUMNS to INFORMATION_SCHEMA.TABLES so we get
one row per (catalog, database, table, column) with the column type plus
the table/column comments and owner.

Output schema (pandas DataFrame):
    catalog, database, table, col_name, data_type, comment,
    table_type, table_owner, table_comment, as_of
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


_META_COLUMNS = [
    "catalog", "database", "table", "col_name", "data_type",
    "comment", "table_type", "table_owner", "table_comment", "as_of",
]


def _build_metadata_query(catalog_name: str, include_optional: bool = True) -> str:
    column_comment = "c.comment" if include_optional else "CAST(NULL AS STRING) AS comment"
    table_owner = "t.table_owner" if include_optional else "CAST(NULL AS STRING) AS table_owner"
    table_comment = "t.comment AS table_comment" if include_optional else "CAST(NULL AS STRING) AS table_comment"
    return f"""
        SELECT
            c.table_name    AS `table`,
            c.table_schema  AS `database`,
            c.table_catalog AS `catalog`,
            c.column_name   AS col_name,
            c.data_type,
            {column_comment},
            t.table_type,
            {table_owner},
            {table_comment}
        FROM `{catalog_name}`.INFORMATION_SCHEMA.COLUMNS c
        JOIN `{catalog_name}`.INFORMATION_SCHEMA.TABLES t
            ON c.table_name = t.table_name
           AND c.table_schema = t.table_schema
        WHERE c.table_schema NOT IN ('_delta_log', 'sys')
    """


def _summarize_catalog_error(exc: Exception) -> str:
    msg = str(exc)
    if "JVM stacktrace:" in msg:
        msg = msg.split("JVM stacktrace:", 1)[0].strip()
    lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
    return lines[0] if lines else exc.__class__.__name__


def _is_unresolved_optional_column_error(exc: Exception) -> bool:
    m = str(exc)
    return "UNRESOLVED_COLUMN" in m and (
        "`c`.`comment`" in m or "`t`.`table_owner`" in m or "`t`.`comment`" in m
    )


def extract_meta(
    spark,
    filter_in_catalogs: Optional[Iterable[str]] = None,
    filter_out_catalogs: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Extract Unity Catalog metadata for every accessible catalog.

    ``spark`` is a DatabricksSession (databricks-connect). All SQL runs on
    the Databricks workspace — there is no local Spark dependency here.
    """
    try:
        catalog_rows = spark.sql("SHOW CATALOGS").collect()
    except Exception as e:
        logger.exception("SHOW CATALOGS failed")
        raise RuntimeError(f"Could not list Databricks catalogs: {e}") from e

    all_catalogs = [r[0] for r in catalog_rows]
    excluded = set(filter_out_catalogs or [])
    catalogs = [c for c in all_catalogs if c not in excluded]
    if filter_in_catalogs:
        included = set(filter_in_catalogs)
        catalogs = [c for c in catalogs if c in included]

    if not catalogs:
        logger.warning("No catalogs to scan after filters; returning empty meta DataFrame")
        return pd.DataFrame(columns=_META_COLUMNS)

    df_final = None
    for cat in catalogs:
        logger.info("[meta] scanning catalog: %s", cat)
        try:
            df_cat = spark.sql(_build_metadata_query(cat, include_optional=True))
        except Exception as e:
            if _is_unresolved_optional_column_error(e):
                try:
                    df_cat = spark.sql(_build_metadata_query(cat, include_optional=False))
                except Exception as fb:
                    logger.warning("[meta] skipping catalog %s: %s", cat, _summarize_catalog_error(fb))
                    continue
            else:
                logger.warning("[meta] skipping catalog %s: %s", cat, _summarize_catalog_error(e))
                continue
        if df_final is None:
            df_final = df_cat
        else:
            df_final = df_final.unionByName(df_cat)

    if df_final is None:
        return pd.DataFrame(columns=_META_COLUMNS)

    pdf = df_final.toPandas()
    pdf["as_of"] = date.today()
    for c in _META_COLUMNS:
        if c not in pdf.columns:
            pdf[c] = None
    pdf = pdf[_META_COLUMNS]
    logger.info("[meta] extracted %d rows across %d catalog(s)", len(pdf), len(catalogs))
    return pdf
