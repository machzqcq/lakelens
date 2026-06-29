"""
Data-scope filter applicator.

A custom role can carry a `filters` JSON object that constrains what data
users with that role can see. Example:

    {
        "workspace_ids":         ["ws-001", "ws-002"],
        "sku_name_pattern":      "PREMIUM%",
        "clouds":                ["AZURE"],
        "cluster_sources":       ["JOB", "UI"],
        "billing_origins":       ["JOBS", "ALL_PURPOSE"],
        "allow_query_history":   true,
        "allow_databricks_meta": true,
    }

A user inherits the UNION of allowed values across all their roles. If any
of the user's roles has no constraint on a given dimension (key absent or
empty), the user has no constraint on that dimension. Admins always bypass.

The two `allow_*` booleans are coarse-grained access toggles for the two
workspace-wide datasets (query_history / databricks_meta). They are
positive grants — only the role-builder UI sets them, and they have no
enforcement plumbing yet beyond storage and pass-through. The intent is
that an admin defines an "IT Admin" custom role that opts into them; an
upcoming change will wire the booleans into the relevant routers.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlalchemy import or_

from auth_utils import AuthedUser
from models import BillingUsage, Cluster, Job, ListPrice, QueryHistory, Warehouse, Workspace


# Filter-spec keys we understand. Order matters only for human-readable
# documentation; the apply_* helpers below read each key by name.
KNOWN_KEYS = (
    "workspace_ids",
    "sku_name_pattern",
    "clouds",
    "cluster_sources",
    "billing_origins",
    "allow_query_history",
    "allow_databricks_meta",
)


def resolve_effective_filters(authed: AuthedUser) -> Optional[dict[str, Any]]:
    """Compute the effective filter spec for an authenticated user.

    - Admins return None (bypass).
    - Only NON-system (custom) roles carry data-scope filters. The built-in
      'user'/'admin' system roles never constrain *or* unlock data on their
      own. This matters because every verified user is always granted the
      'user' role — if that role counted as "unrestricted" it would cancel
      any custom scoped role the admin assigns.
    - A user with no custom role behaves like plain 'user': unrestricted.
    - Otherwise, return the union of allowed values per key across the
      custom roles. If any custom role is unrestricted on a dimension, that
      dimension is unrestricted.
    """
    if authed.is_admin:
        return None
    if not authed.roles:
        return {"__deny_all__": True}  # logged in but role-less = no data

    # System roles ('user'/'admin') don't define data scope. admin is already
    # handled above; 'user' is just the default unrestricted grant.
    custom_roles = [r for r in authed.roles if not r.is_system]

    if not custom_roles:
        return None  # only the default 'user' role => unrestricted

    role_filters = [r.filters or {} for r in custom_roles]

    # Every custom role unrestricted (empty filters) => unrestricted.
    if all(not rf for rf in role_filters):
        return None

    effective: dict[str, Any] = {}

    # Each list-typed key: union of allowed values across roles. If ANY role
    # has it absent/empty, the dimension is unrestricted.
    for key in ("workspace_ids", "clouds", "cluster_sources", "billing_origins"):
        any_unrestricted = any(not rf.get(key) for rf in role_filters)
        if any_unrestricted:
            continue
        union: set[str] = set()
        for rf in role_filters:
            union.update(rf.get(key, []))
        if union:
            effective[key] = sorted(union)

    # sku_name_pattern: simplest semantic — if any role has no pattern, no
    # restriction. Otherwise OR the patterns by attaching them as a list.
    patterns = [rf.get("sku_name_pattern") for rf in role_filters if rf.get("sku_name_pattern")]
    if patterns and len(patterns) == len(role_filters):
        effective["sku_name_patterns"] = list(set(patterns))

    return effective or None


# ---------------------------------------------------------------------------
# Apply filters to SQLAlchemy stmts
# ---------------------------------------------------------------------------

def _as_strs(values: Iterable[Any]) -> list[str]:
    """ID/category columns are String. Filter specs may carry ints (the web
    client coerces numeric-looking strings to numbers), so normalise to str
    or the IN-clause silently matches nothing."""
    return [str(v) for v in values]


def _apply_data_scope(stmt, model, view_mode: Optional[str]):
    """Apply data-isolation filters: data_origin == view_mode AND deleted_at IS NULL.

    No-op when `view_mode is None` (admin tooling that intentionally bypasses
    scoping, e.g. Database Explorer).
    """
    if view_mode is None:
        return stmt
    if hasattr(model, "data_origin"):
        stmt = stmt.where(model.data_origin == view_mode)
    if hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))
    return stmt


def apply_billing_filters(
    stmt,
    filters: Optional[dict[str, Any]],
    view_mode: Optional[str] = None,
):
    """Apply RBAC filters + data-isolation filters to a BillingUsage stmt.

    `view_mode` (the current user's `viewing_data_mode`) is the per-user
    sticky setting for the data-isolation system. Passing None skips it.
    """
    stmt = _apply_data_scope(stmt, BillingUsage, view_mode)
    if not filters:
        return stmt
    if filters.get("__deny_all__"):
        return stmt.where(False)
    if filters.get("workspace_ids"):
        stmt = stmt.where(BillingUsage.workspace_id.in_(_as_strs(filters["workspace_ids"])))
    if filters.get("clouds"):
        stmt = stmt.where(BillingUsage.cloud.in_(_as_strs(filters["clouds"])))
    if filters.get("billing_origins"):
        stmt = stmt.where(BillingUsage.billing_origin_product.in_(_as_strs(filters["billing_origins"])))
    if filters.get("sku_name_patterns"):
        # Multiple patterns OR'd together via ILIKE
        clauses = [BillingUsage.sku_name.ilike(p) for p in filters["sku_name_patterns"]]
        stmt = stmt.where(or_(*clauses))
    return stmt


def apply_cluster_filters(
    stmt,
    filters: Optional[dict[str, Any]],
    view_mode: Optional[str] = None,
):
    stmt = _apply_data_scope(stmt, Cluster, view_mode)
    if not filters:
        return stmt
    if filters.get("__deny_all__"):
        return stmt.where(False)
    if filters.get("workspace_ids"):
        stmt = stmt.where(Cluster.workspace_id.in_(_as_strs(filters["workspace_ids"])))
    if filters.get("cluster_sources"):
        stmt = stmt.where(Cluster.cluster_source.in_(_as_strs(filters["cluster_sources"])))
    return stmt


def apply_warehouse_filters(
    stmt,
    filters: Optional[dict[str, Any]],
    view_mode: Optional[str] = None,
):
    stmt = _apply_data_scope(stmt, Warehouse, view_mode)
    if not filters:
        return stmt
    if filters.get("__deny_all__"):
        return stmt.where(False)
    if filters.get("workspace_ids"):
        stmt = stmt.where(Warehouse.workspace_id.in_(_as_strs(filters["workspace_ids"])))
    return stmt


def apply_job_filters(
    stmt,
    filters: Optional[dict[str, Any]],
    view_mode: Optional[str] = None,
):
    """Job table: only data-isolation. No RBAC dimensions today."""
    stmt = _apply_data_scope(stmt, Job, view_mode)
    if filters and filters.get("__deny_all__"):
        return stmt.where(False)
    if filters and filters.get("workspace_ids"):
        stmt = stmt.where(Job.workspace_id.in_(_as_strs(filters["workspace_ids"])))
    return stmt


def apply_workspace_filters(
    stmt,
    filters: Optional[dict[str, Any]],
    view_mode: Optional[str] = None,
):
    stmt = _apply_data_scope(stmt, Workspace, view_mode)
    if filters and filters.get("__deny_all__"):
        return stmt.where(False)
    if filters and filters.get("workspace_ids"):
        stmt = stmt.where(Workspace.workspace_id.in_(_as_strs(filters["workspace_ids"])))
    return stmt


def apply_list_price_filters(
    stmt,
    filters: Optional[dict[str, Any]],
    view_mode: Optional[str] = None,
):
    """list_prices has no RBAC dimensions — just data isolation."""
    return _apply_data_scope(stmt, ListPrice, view_mode)


def apply_query_history_filters(
    stmt,
    filters: Optional[dict[str, Any]],
    view_mode: Optional[str] = None,
):
    stmt = _apply_data_scope(stmt, QueryHistory, view_mode)
    if filters and filters.get("__deny_all__"):
        return stmt.where(False)
    if filters and filters.get("workspace_ids"):
        stmt = stmt.where(QueryHistory.workspace_id.in_(_as_strs(filters["workspace_ids"])))
    return stmt


# Convenience: pull the view-mode string for a stmt straight from an AuthedUser.
def view_mode_of(authed: Optional[AuthedUser]) -> str:
    """Return the user's `viewing_data_mode` ('real' default)."""
    if authed is None:
        return "real"
    return authed.viewing_data_mode or "real"


# ---------------------------------------------------------------------------
# Distinct-values endpoint helper (used by the role-builder UI)
# ---------------------------------------------------------------------------

def filter_dimensions() -> list[str]:
    """Return the keys the role-builder UI knows how to populate."""
    return list(KNOWN_KEYS)
