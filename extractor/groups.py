"""Extraction group → table-list mapping.

Mirrors backend/extract/groups.py so both sides agree on what each
UI checkbox actually pulls.
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
    "node_pool":     ("node_timeline", "warehouse_events", "node_types",
                      "instance_events", "instance_pools"),
}
ALL_GROUPS: tuple[str, ...] = tuple(GROUPS.keys())


def tables_for_groups(groups: Optional[list[str] | tuple[str, ...]] = None) -> set[str]:
    selected = ALL_GROUPS if not groups else tuple(g for g in groups if g in GROUPS)
    return {t for g in selected for t in GROUPS[g]}
