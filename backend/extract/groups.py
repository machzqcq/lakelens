"""Extraction group → table-list mapping.

Mirrored verbatim in extractor/groups.py — both sides agree on what each
UI checkbox actually pulls. The backend no longer has any Databricks
SDK installed; extraction lives in the dedicated extractor service.
"""
from __future__ import annotations

from typing import Optional


GROUPS: dict[str, tuple[str, ...]] = {
    "billing":       ("billing_usage", "list_prices"),
    "compute":       ("clusters", "warehouses", "jobs", "workspaces"),
    "query_history": ("query_history",),
    "meta":          ("databricks_meta",),
    "lineage":       ("table_lineage", "column_lineage"),
    "audit":         ("audit_events", "assistant_events"),
    # system.compute.* telemetry — node-level utilization, warehouse and
    # instance lifecycle events, plus the reference catalogs for node types
    # and instance pools. node_timeline is high-cardinality (chunked weekly
    # in the extractor) and inherits the `node_pool_days_back` window.
    "node_pool":     ("node_timeline", "warehouse_events", "node_types",
                      "instance_events", "instance_pools"),
}
ALL_GROUPS: tuple[str, ...] = tuple(GROUPS.keys())


def tables_for_groups(groups: Optional[list[str] | tuple[str, ...]] = None) -> set[str]:
    """Resolve a list of group names to the flat set of table names involved.

    Passing None or an empty list returns the full set (default = pull
    everything, matching the pre-checkbox behavior).
    """
    selected = ALL_GROUPS if not groups else tuple(g for g in groups if g in GROUPS)
    return {t for g in selected for t in GROUPS[g]}
