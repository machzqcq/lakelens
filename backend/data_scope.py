"""Data-scope helpers — apply the `data_origin = :view_mode` and
`deleted_at IS NULL` filters that every domain read must honor.

Two layers:

1. `view_mode_from_user(user)` — pull the per-user sticky setting.
2. `apply_data_scope(query, model, view_mode)` — add WHERE clauses to a
   SQLAlchemy `select()` chain.

For raw `text()` SQL the endpoint should add the filter directly. This
module gives helpers for the SQLAlchemy-ORM style endpoints.
"""
from __future__ import annotations

from typing import Optional

from auth_utils import AuthedUser
from models import User


def view_mode_from_user(user: Optional[AuthedUser]) -> str:
    """Resolve the active view mode for this request.

    Anonymous → 'real' (read-only public dashboards default to real data).
    Authenticated → user's persisted `viewing_data_mode`.
    """
    if user is None:
        return "real"
    return getattr(user, "viewing_data_mode", None) or "real"


def apply_data_scope(query, model, view_mode: str):
    """Append `data_origin = :view_mode AND deleted_at IS NULL` to a query.

    No-op if the model doesn't have the columns (i.e. it's an auth table
    or qi_*). Safe to call on any model.
    """
    if hasattr(model, "data_origin"):
        query = query.where(model.data_origin == view_mode)
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))
    return query


# SQL fragment for `text()`-style queries. Use like:
#     sql = f"SELECT ... FROM billing_usage WHERE 1=1 {data_scope_sql('')}"
def data_scope_sql(alias: str = "") -> str:
    """Return ' AND alias.data_origin = :view_mode AND alias.deleted_at IS NULL'.

    Pass the empty string for un-aliased tables. The caller must include
    `:view_mode` in the bind-params dict.
    """
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}data_origin = :view_mode AND {prefix}deleted_at IS NULL"
