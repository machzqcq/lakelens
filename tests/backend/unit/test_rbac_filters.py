"""Unit tests for backend/rbac_filters.py.

These cover the data-scope filter resolution semantics: admins bypass,
unrestricted system roles bypass, otherwise we union per-dimension across
the user's roles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from rbac_filters import (
    apply_billing_filters,
    apply_cluster_filters,
    apply_warehouse_filters,
    resolve_effective_filters,
)


# ---------------------------------------------------------------------------
# Stand-in classes so we don't depend on the User/Role ORM here
# ---------------------------------------------------------------------------


@dataclass
class FakeRole:
    name: str
    is_system: bool = False
    filters: Optional[dict[str, Any]] = None


class FakeAuthed:
    def __init__(self, roles: list[FakeRole], is_admin: bool = False):
        self.roles = roles
        self._is_admin = is_admin

    @property
    def role_names(self) -> set[str]:
        return {r.name for r in self.roles}

    @property
    def is_admin(self) -> bool:
        return self._is_admin


class TestResolveEffectiveFilters:
    def test_admin_bypasses_everything(self):
        admin = FakeAuthed(
            roles=[FakeRole(name="admin", is_system=True)],
            is_admin=True,
        )
        # Even if a custom role was attached, admin still bypasses
        admin.roles.append(FakeRole(name="finance", filters={"workspace_ids": ["ws-1"]}))
        assert resolve_effective_filters(admin) is None

    def test_default_user_role_is_unrestricted(self):
        # Plain `user` system role with no filters => no constraint
        authed = FakeAuthed(roles=[FakeRole(name="user", is_system=True, filters={})])
        assert resolve_effective_filters(authed) is None

    def test_no_roles_means_deny_all(self):
        # Logged in but role-less = no data
        authed = FakeAuthed(roles=[])
        result = resolve_effective_filters(authed)
        assert result == {"__deny_all__": True}

    def test_single_role_filter_passes_through(self):
        authed = FakeAuthed(
            roles=[FakeRole(name="finance", filters={"workspace_ids": ["ws-1", "ws-2"]})]
        )
        result = resolve_effective_filters(authed)
        assert result == {"workspace_ids": ["ws-1", "ws-2"]}

    def test_two_roles_union_of_workspaces(self):
        authed = FakeAuthed(
            roles=[
                FakeRole(name="finance", filters={"workspace_ids": ["ws-1"]}),
                FakeRole(name="eng",     filters={"workspace_ids": ["ws-2", "ws-3"]}),
            ]
        )
        result = resolve_effective_filters(authed)
        assert sorted(result["workspace_ids"]) == ["ws-1", "ws-2", "ws-3"]

    def test_unrestricted_role_grants_full_dim(self):
        # If any role omits a dimension, the dimension is unrestricted
        authed = FakeAuthed(
            roles=[
                FakeRole(name="finance", filters={"workspace_ids": ["ws-1"]}),
                FakeRole(name="ops",     filters={}),  # no constraint anywhere
            ]
        )
        # `ops` has empty filters; this role acts like an unrestricted custom role.
        # Multi-dim: workspace_ids should NOT appear because ops is unrestricted on it.
        result = resolve_effective_filters(authed)
        assert result is None or "workspace_ids" not in result

    def test_sku_pattern_intersection_semantics(self):
        # All roles must restrict for the pattern list to be active
        authed_all = FakeAuthed(
            roles=[
                FakeRole(name="a", filters={"sku_name_pattern": "PREMIUM%"}),
                FakeRole(name="b", filters={"sku_name_pattern": "ENTERPRISE%"}),
            ]
        )
        result = resolve_effective_filters(authed_all)
        assert sorted(result["sku_name_patterns"]) == ["ENTERPRISE%", "PREMIUM%"]

        # If any role omits pattern, no pattern restriction
        authed_any_unrestricted = FakeAuthed(
            roles=[
                FakeRole(name="a", filters={"sku_name_pattern": "PREMIUM%"}),
                FakeRole(name="b", filters={"workspace_ids": ["ws-1"]}),
            ]
        )
        result = resolve_effective_filters(authed_any_unrestricted)
        assert result is None or "sku_name_patterns" not in result


class TestApplyFilters:
    """Smoke-test the applicators on the actual SQLAlchemy stmts."""

    def _make_stmt(self, model):
        from sqlalchemy import select
        return select(model)

    def test_apply_billing_filters_no_op_when_filters_empty(self):
        from models import BillingUsage
        stmt = self._make_stmt(BillingUsage)
        out = apply_billing_filters(stmt, None)
        assert str(out) == str(stmt)  # untouched

    def test_apply_billing_filters_adds_where(self):
        from models import BillingUsage
        stmt = self._make_stmt(BillingUsage)
        out = apply_billing_filters(
            stmt,
            {"workspace_ids": ["ws-1", "ws-2"], "clouds": ["AZURE"]},
        )
        compiled = str(out)
        assert "workspace_id IN" in compiled
        assert "cloud IN" in compiled

    def test_apply_billing_filters_deny_all_yields_false_clause(self):
        from models import BillingUsage
        stmt = self._make_stmt(BillingUsage)
        out = apply_billing_filters(stmt, {"__deny_all__": True})
        # Compile to a string and verify it contains a falsy clause
        compiled = str(out.compile(compile_kwargs={"literal_binds": True}))
        # SQLAlchemy renders WHERE false as ' WHERE false' on most dialects
        assert "false" in compiled.lower() or " WHERE 0" in compiled

    def test_apply_cluster_filters(self):
        from models import Cluster
        stmt = self._make_stmt(Cluster)
        out = apply_cluster_filters(stmt, {"cluster_sources": ["JOB", "UI"]})
        assert "cluster_source IN" in str(out)

    def test_apply_warehouse_filters(self):
        from models import Warehouse
        stmt = self._make_stmt(Warehouse)
        out = apply_warehouse_filters(stmt, {"workspace_ids": ["ws-1"]})
        assert "workspace_id IN" in str(out)

    def test_sku_patterns_use_ilike(self):
        from models import BillingUsage
        stmt = self._make_stmt(BillingUsage)
        out = apply_billing_filters(
            stmt,
            {"sku_name_patterns": ["PREMIUM%", "ENTERPRISE%"]},
        )
        compiled = str(out).upper()
        # SQLAlchemy compiles ILIKE as LOWER(col) LIKE LOWER(?) on Postgres —
        # both forms are case-insensitive and equally valid here.
        assert "ILIKE" in compiled or "LIKE LOWER" in compiled
        # Two patterns => OR'd together
        assert " OR " in compiled

    def test_int_workspace_ids_still_compile_to_in(self):
        # Regression: the web client coerces numeric-looking strings to
        # numbers, so a saved role can carry int workspace_ids. They must
        # still produce WHERE ... IN against the String column (str-coerced),
        # not silently match nothing.
        from models import BillingUsage
        stmt = self._make_stmt(BillingUsage)
        out = apply_billing_filters(stmt, {"workspace_ids": [4206644426758546]})
        compiled = str(out.compile(compile_kwargs={"literal_binds": True}))
        assert "workspace_id IN" in compiled
        assert "4206644426758546" in compiled


class TestSystemRoleNeutrality:
    """Regression suite for the bug where the always-assigned 'user' system
    role made resolve_effective_filters() return None (full bypass), so any
    scoped custom role was silently cancelled."""

    def test_user_plus_scoped_custom_role_is_restricted(self):
        # THE reported bug: a real user keeps the 'user' system role AND is
        # given a scoped custom role. They must be restricted to the scope.
        authed = FakeAuthed(roles=[
            FakeRole(name="user", is_system=True, filters=None),
            FakeRole(name="ws-1-user", is_system=False,
                     filters={"workspace_ids": ["ws-1"]}),
        ])
        result = resolve_effective_filters(authed)
        assert result == {"workspace_ids": ["ws-1"]}

    def test_only_system_roles_is_unrestricted(self):
        # 'user' (and even 'admin' by name) with no custom role => no scope.
        authed = FakeAuthed(roles=[FakeRole(name="user", is_system=True)])
        assert resolve_effective_filters(authed) is None

    def test_admin_flag_still_bypasses_even_with_custom_role(self):
        authed = FakeAuthed(
            roles=[
                FakeRole(name="admin", is_system=True),
                FakeRole(name="ws-1-user", filters={"workspace_ids": ["ws-1"]}),
            ],
            is_admin=True,
        )
        assert resolve_effective_filters(authed) is None

    def test_system_role_does_not_widen_custom_union(self):
        # 'user' must not contribute an "unrestricted" vote to the per-dim
        # union — only the custom role's workspaces apply.
        authed = FakeAuthed(roles=[
            FakeRole(name="user", is_system=True, filters=None),
            FakeRole(name="a", filters={"workspace_ids": ["ws-1"]}),
            FakeRole(name="b", filters={"workspace_ids": ["ws-2"]}),
        ])
        result = resolve_effective_filters(authed)
        assert sorted(result["workspace_ids"]) == ["ws-1", "ws-2"]

    def test_custom_roles_all_empty_is_unrestricted(self):
        authed = FakeAuthed(roles=[
            FakeRole(name="user", is_system=True),
            FakeRole(name="blank", is_system=False, filters={}),
        ])
        assert resolve_effective_filters(authed) is None
