"""
Integration tests for the admin user/role endpoints + RBAC gating.

Non-admin users must NOT reach /api/admin/*. Admins can list/manage
users and roles; they can't lock themselves out.
"""

import secrets

import pytest


pytestmark = [pytest.mark.requires_db, pytest.mark.asyncio]


class TestAdminGate:
    async def test_anonymous_blocked(self, client):
        for path in [
            "/api/admin/users",
            "/api/admin/roles",
            "/api/admin/filter-dimensions",
        ]:
            resp = await client.get(path)
            assert resp.status_code == 401, path

    async def test_regular_user_blocked(self, user_client):
        for path in [
            "/api/admin/users",
            "/api/admin/roles",
            "/api/admin/filter-dimensions",
        ]:
            resp = await user_client.get(path)
            assert resp.status_code == 403, path

    async def test_admin_allowed(self, admin_client):
        for path in [
            "/api/admin/users",
            "/api/admin/roles",
            "/api/admin/filter-dimensions",
        ]:
            resp = await admin_client.get(path)
            assert resp.status_code == 200, path


class TestUserListing:
    async def test_list_returns_admin_at_minimum(self, admin_client):
        resp = await admin_client.get("/api/admin/users")
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.json()]
        assert "admin@test.local" in emails


class TestRoleCrud:
    async def test_list_roles_includes_system_pair(self, admin_client):
        resp = await admin_client.get("/api/admin/roles")
        roles = {r["name"]: r for r in resp.json()}
        assert "admin" in roles and "user" in roles
        assert roles["admin"]["is_system"] is True
        assert roles["user"]["is_system"] is True

    async def test_cannot_create_reserved_name(self, admin_client):
        for reserved in ("admin", "user"):
            resp = await admin_client.post(
                "/api/admin/roles",
                json={"name": reserved, "description": "x"},
            )
            assert resp.status_code == 400, f"creating reserved name '{reserved}' should fail"

    async def test_create_update_delete_custom_role(self, admin_client):
        # Create
        resp = await admin_client.post(
            "/api/admin/roles",
            json={
                "name": "test-finance",
                "description": "Finance read-only",
                "filters": {"clouds": ["AZURE"]},
            },
        )
        assert resp.status_code == 201, resp.text
        role = resp.json()
        role_id = role["id"]
        assert role["filters"] == {"clouds": ["AZURE"]}
        assert role["is_system"] is False

        # Update
        resp = await admin_client.patch(
            f"/api/admin/roles/{role_id}",
            json={"description": "updated", "filters": {"clouds": ["AWS"]}},
        )
        assert resp.status_code == 200
        assert resp.json()["filters"] == {"clouds": ["AWS"]}

        # Delete
        resp = await admin_client.delete(f"/api/admin/roles/{role_id}")
        assert resp.status_code == 204

    async def test_cannot_delete_system_role(self, admin_client):
        resp = await admin_client.get("/api/admin/roles")
        admin_role = next(r for r in resp.json() if r["name"] == "admin")
        resp = await admin_client.delete(f"/api/admin/roles/{admin_role['id']}")
        assert resp.status_code == 400

    async def test_duplicate_role_name_409(self, admin_client):
        body = {"name": "dup-role", "description": "x"}
        ok = await admin_client.post("/api/admin/roles", json=body)
        assert ok.status_code == 201
        try:
            again = await admin_client.post("/api/admin/roles", json=body)
            assert again.status_code == 409
        finally:
            await admin_client.delete(f"/api/admin/roles/{ok.json()['id']}")


class TestRoleAssignment:
    async def test_assign_unassign_role(self, admin_client, new_user):
        # Setup: a non-admin user
        creds = await new_user()
        users = (await admin_client.get("/api/admin/users")).json()
        user = next(u for u in users if u["email"] == creds["email"])
        roles = (await admin_client.get("/api/admin/roles")).json()
        admin_role = next(r for r in roles if r["name"] == "admin")

        # Assign admin
        resp = await admin_client.post(
            f"/api/admin/users/{user['id']}/roles/{admin_role['id']}"
        )
        assert resp.status_code == 200
        assert "admin" in resp.json()["roles"]

        # Re-assigning should be idempotent (200, not 409)
        resp = await admin_client.post(
            f"/api/admin/users/{user['id']}/roles/{admin_role['id']}"
        )
        assert resp.status_code == 200

        # Unassign
        resp = await admin_client.delete(
            f"/api/admin/users/{user['id']}/roles/{admin_role['id']}"
        )
        assert resp.status_code == 200
        assert "admin" not in resp.json()["roles"]

    async def test_admin_cannot_remove_own_admin_role(self, admin_client):
        me = (await admin_client.get("/api/auth/me")).json()
        roles = (await admin_client.get("/api/admin/roles")).json()
        admin_role = next(r for r in roles if r["name"] == "admin")
        resp = await admin_client.delete(
            f"/api/admin/users/{me['id']}/roles/{admin_role['id']}"
        )
        assert resp.status_code == 400


class TestUserCreation:
    async def test_non_admin_cannot_create_user(self, user_client):
        resp = await user_client.post(
            "/api/admin/users",
            json={"email": "x@test.local", "password": "Passw0rd123!"},
        )
        assert resp.status_code == 403

    async def test_admin_creates_verified_user_who_can_login(self, admin_client, client):
        email = f"made{secrets.token_hex(4)}@test.local"
        pw = "MadeByAdmin123!"
        resp = await admin_client.post(
            "/api/admin/users",
            json={"email": email, "password": pw, "full_name": "Made User"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        uid = body["id"]
        try:
            assert body["is_email_verified"] is True
            assert body["roles"] == ["user"]
            # No email loop needed — immediate login works.
            login = await client.post(
                "/api/auth/login", json={"email": email, "password": pw}
            )
            assert login.status_code == 200, login.text
        finally:
            await admin_client.delete(f"/api/admin/users/{uid}")

    async def test_create_with_extra_role_and_duplicate_rejected(self, admin_client):
        role = (await admin_client.post(
            "/api/admin/roles",
            json={"name": f"r{secrets.token_hex(3)}", "filters": {"clouds": ["AZURE"]}},
        )).json()
        email = f"scoped{secrets.token_hex(4)}@test.local"
        created = await admin_client.post(
            "/api/admin/users",
            json={"email": email, "password": "Scoped123!!", "role_ids": [role["id"]]},
        )
        assert created.status_code == 201, created.text
        uid = created.json()["id"]
        try:
            assert set(created.json()["roles"]) == {"user", role["name"]}
            dup = await admin_client.post(
                "/api/admin/users",
                json={"email": email, "password": "Scoped123!!"},
            )
            assert dup.status_code == 409
        finally:
            await admin_client.delete(f"/api/admin/users/{uid}")
            await admin_client.delete(f"/api/admin/roles/{role['id']}")


class TestDbExplorer:
    async def test_gating(self, client, user_client, admin_client):
        assert (await client.get("/api/admin/db/objects")).status_code == 401
        assert (await user_client.get("/api/admin/db/objects")).status_code == 403
        assert (await admin_client.get("/api/admin/db/objects")).status_code == 200

    async def test_objects_shape(self, admin_client):
        objs = (await admin_client.get("/api/admin/db/objects")).json()
        assert isinstance(objs, list) and objs
        sample = objs[0]
        for k in ("schema_name", "name", "kind", "approx_rows", "columns"):
            assert k in sample
        # The auth tables live in the operational DB and must be visible.
        names = {o["name"] for o in objs}
        assert "auth_users" in names

    async def test_select_query_runs(self, admin_client):
        resp = await admin_client.post(
            "/api/admin/db/query",
            json={"sql": "SELECT 1 AS one, 'hi' AS greeting"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["columns"] == ["one", "greeting"]
        assert body["rows"] == [{"one": 1, "greeting": "hi"}]
        assert body["truncated"] is False

    @pytest.mark.parametrize("sql,needle", [
        ("UPDATE auth_users SET email='x'", "Only SELECT"),
        ("DROP TABLE auth_users", "Only SELECT"),
        ("SELECT 1; SELECT 2", "Multiple statements"),
        ("SET statement_timeout = 0", "Only SELECT"),
    ])
    async def test_unsafe_rejected_400(self, admin_client, sql, needle):
        resp = await admin_client.post("/api/admin/db/query", json={"sql": sql})
        assert resp.status_code == 400, f"{sql!r} -> {resp.status_code}"
        assert needle.lower() in resp.json()["detail"].lower()

    async def test_row_cap_enforced(self, admin_client):
        resp = await admin_client.post(
            "/api/admin/db/query",
            json={"sql": "SELECT g FROM generate_series(1, 50) g", "max_rows": 10},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["row_count"] == 10
        assert body["truncated"] is True


class TestFilterDimensions:
    async def test_returns_known_keys(self, admin_client):
        resp = await admin_client.get("/api/admin/filter-dimensions")
        assert resp.status_code == 200
        body = resp.json()
        for k in ["workspace_ids", "clouds", "billing_origins", "cluster_sources", "sku_names"]:
            assert k in body
            assert isinstance(body[k], list)
