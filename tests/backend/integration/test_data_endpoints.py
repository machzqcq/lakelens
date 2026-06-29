"""
Integration tests for the data endpoints + the RBAC data-scope filter.

We exercise the heaviest /billing/* + /compute/* endpoints, then verify
that a custom role's filter actually narrows the visible workspaces.
"""

import pytest


pytestmark = [pytest.mark.requires_db, pytest.mark.asyncio]


class TestAuthGate:
    async def test_anonymous_blocked_on_data_endpoints(self, client):
        for path in [
            "/api/billing/usage-summary",
            "/api/billing/by-sku",
            "/api/billing/by-workspace",
            "/api/billing/by-cloud",
            "/api/billing/daily-trend",
            "/api/compute/clusters",
            "/api/compute/warehouses",
            "/api/analytics/kpi-summary?start_date=2026-04-01&end_date=2026-05-01",
        ]:
            resp = await client.get(path)
            assert resp.status_code == 401, path


class TestBillingShape:
    async def test_usage_summary_returns_data(self, admin_client):
        resp = await admin_client.get("/api/billing/usage-summary?group_by=day")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body and isinstance(body["data"], list)
        if body["data"]:
            row = body["data"][0]
            for k in ("period", "total_usage", "total_cost"):
                assert k in row

    async def test_by_sku_groups_by_sku_name(self, admin_client):
        resp = await admin_client.get("/api/billing/by-sku")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body.get("data"), list)
        for row in body["data"]:
            assert "label" in row and "total_cost" in row

    async def test_invalid_group_by_rejected(self, admin_client):
        resp = await admin_client.get("/api/billing/usage-summary?group_by=decade")
        assert resp.status_code in (400, 422)


class TestComputeShape:
    async def test_list_clusters_paginates(self, admin_client):
        resp = await admin_client.get("/api/compute/clusters?page=1&page_size=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1 and body["page_size"] == 5
        assert isinstance(body["data"], list) and len(body["data"]) <= 5

    async def test_list_clusters_sort_by_cpu(self, admin_client):
        resp = await admin_client.get(
            "/api/compute/clusters?sort_by=total_vcpus&sort_order=desc&page_size=10"
        )
        assert resp.status_code == 200
        vcpus = [c.get("total_vcpus") for c in resp.json()["data"] if c.get("total_vcpus") is not None]
        assert vcpus == sorted(vcpus, reverse=True)


class TestRbacDataScope:
    """End-to-end: a custom data-scoped role actually narrows results."""

    async def _setup_scoped_user(self, admin_client, new_user, cloud: str,
                                  *, keep_user_role: bool = True):
        """Create a fresh user + custom role with `clouds=[<cloud>]`.

        By default we KEEP the always-assigned 'user' system role — that is
        the realistic configuration and the exact scenario of the bug where
        the 'user' role used to cancel the custom scope. Pass
        keep_user_role=False to also exercise the role-stripped path.
        """
        creds = await new_user()

        role_resp = await admin_client.post(
            "/api/admin/roles",
            json={
                "name": f"only-{cloud.lower()}-{id(creds) % 100000}",
                "description": f"Only {cloud}",
                "filters": {"clouds": [cloud]},
            },
        )
        assert role_resp.status_code == 201, role_resp.text
        role_id = role_resp.json()["id"]

        users = (await admin_client.get("/api/admin/users")).json()
        user = next(u for u in users if u["email"] == creds["email"])

        if not keep_user_role:
            roles = (await admin_client.get("/api/admin/roles")).json()
            user_role = next(r for r in roles if r["name"] == "user")
            await admin_client.delete(
                f"/api/admin/users/{user['id']}/roles/{user_role['id']}"
            )

        assigned = await admin_client.post(
            f"/api/admin/users/{user['id']}/roles/{role_id}"
        )
        assert assigned.status_code == 200
        return creds, role_id, user["id"]

    async def test_scoped_role_narrows_clouds(self, client, admin_client, new_user):
        # Establish the universe: what clouds does the admin see?
        admin_sku = await admin_client.get("/api/billing/by-cloud")
        admin_clouds = {row["label"] for row in admin_sku.json()["data"]}
        if not admin_clouds:
            pytest.skip("no billing data in test DB")

        target_cloud = next(iter(admin_clouds))
        # keep_user_role=True (default): the user still holds 'user' — this
        # is the exact bug scenario. Scoping must still apply.
        creds, role_id, uid = await self._setup_scoped_user(
            admin_client, new_user, target_cloud
        )

        try:
            login = await client.post(
                "/api/auth/login",
                json={"email": creds["email"], "password": creds["password"]},
            )
            token = login.json()["access_token"]
            hdr = {"Authorization": f"Bearer {token}"}

            # Sanity: the scoped user really does still have the 'user' role.
            me = await client.get("/api/auth/me", headers=hdr)
            assert "user" in me.json()["roles"]

            # Billing endpoint is scoped.
            by_cloud = await client.get("/api/billing/by-cloud", headers=hdr)
            assert by_cloud.status_code == 200
            scoped_clouds = {row["label"] for row in by_cloud.json()["data"]}
            assert scoped_clouds.issubset({target_cloud}), (
                f"scoped user saw {scoped_clouds}, expected ⊆ {{{target_cloud}}}"
            )

            # Analytics endpoint (service-layer path) is scoped too: the
            # per-workspace heatmap must not exceed what by-workspace shows.
            ws_resp = await client.get("/api/billing/by-workspace", headers=hdr)
            scoped_ws = {r["label"] for r in ws_resp.json()["data"]}
            matrix = await client.get(
                "/api/analytics/cost-breakdown-matrix", headers=hdr
            )
            assert matrix.status_code == 200
            matrix_ws = set(matrix.json().get("workspaces", []))
            assert matrix_ws.issubset(scoped_ws or matrix_ws), (
                f"analytics matrix workspaces {matrix_ws} exceeded scoped {scoped_ws}"
            )

            # SKU & Billing-Origin page: top-N pivot endpoints must also be
            # scoped — workspaces appearing as columns can't exceed the
            # scoped set returned by /billing/by-workspace.
            so_pivot = await client.get(
                "/api/analytics/sku-origin/sku-workspace-matrix", headers=hdr
            )
            assert so_pivot.status_code == 200
            so_ws = set(so_pivot.json().get("cols", []))
            assert so_ws.issubset(scoped_ws or so_ws), (
                f"sku-origin pivot workspaces {so_ws} exceeded scoped {scoped_ws}"
            )
        finally:
            await admin_client.delete(f"/api/admin/users/{uid}")
            await admin_client.delete(f"/api/admin/roles/{role_id}")


class TestSkuOriginEndpoints:
    """Smoke + shape tests for the new SKU & Billing-Origin analytics page."""

    async def test_anonymous_blocked(self, client):
        for path in [
            "/api/analytics/sku-origin/treemap",
            "/api/analytics/sku-origin/sku-leaderboard",
            "/api/analytics/sku-origin/origin-leaderboard",
            "/api/analytics/sku-origin/sku-workspace-matrix",
            "/api/analytics/sku-origin/origin-workspace-matrix",
            "/api/analytics/sku-origin/sku-identity",
            "/api/analytics/sku-origin/origin-identity",
            "/api/analytics/sku-origin/concentration",
            "/api/analytics/sku-origin/trend",
            "/api/analytics/sku-origin/serverless-share",
        ]:
            resp = await client.get(path)
            assert resp.status_code == 401, path

    async def test_admin_can_load_each_panel(self, admin_client):
        endpoints_and_keys = [
            ("/api/analytics/sku-origin/treemap", "items"),
            ("/api/analytics/sku-origin/sku-leaderboard", "data"),
            ("/api/analytics/sku-origin/origin-leaderboard", "data"),
            ("/api/analytics/sku-origin/sku-workspace-matrix", "cells"),
            ("/api/analytics/sku-origin/origin-workspace-matrix", "cells"),
            ("/api/analytics/sku-origin/sku-identity", "cells"),
            ("/api/analytics/sku-origin/origin-identity", "cells"),
            ("/api/analytics/sku-origin/serverless-share", "data"),
        ]
        for path, key in endpoints_and_keys:
            r = await admin_client.get(path)
            assert r.status_code == 200, f"{path}: {r.text[:200]}"
            assert key in r.json(), f"{path} missing key {key}"

        # Concentration: two named sections.
        r = await admin_client.get("/api/analytics/sku-origin/concentration")
        assert r.status_code == 200
        body = r.json()
        assert "by_origin" in body and "by_sku" in body

        # Trend: stacked-by-workspace shape.
        r = await admin_client.get("/api/analytics/sku-origin/trend")
        assert r.status_code == 200
        body = r.json()
        for k in ("workspaces", "points", "total"):
            assert k in body, f"trend missing {k}"

    async def test_drilldown_requires_exactly_one_filter(self, admin_client):
        # 0 filters: 400
        r = await admin_client.get("/api/analytics/sku-origin/drilldown")
        assert r.status_code == 400
        # 2 filters: 400
        r = await admin_client.get(
            "/api/analytics/sku-origin/drilldown",
            params={"sku_name": "X", "billing_origin": "Y"},
        )
        assert r.status_code == 400

    async def test_drilldown_with_real_sku_returns_full_shape(self, admin_client):
        # Pick the top SKU from the leaderboard.
        lb = (await admin_client.get("/api/analytics/sku-origin/sku-leaderboard")).json()
        if not lb.get("data"):
            pytest.skip("no billing data in test DB")
        sku = lb["data"][0]["sku_name"]

        r = await admin_client.get(
            "/api/analytics/sku-origin/drilldown",
            params={"sku_name": sku},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["target_kind"] == "sku"
        assert body["target"] == sku
        for k in ("trend", "top_workspaces", "top_identities",
                  "null_identity_cost", "related_owners"):
            assert k in body
