"""
Integration tests for the email/password auth flow.

The full flow we exercise:
  - register a new user → 201
  - /login is rejected until email is verified
  - /verify-email with a real DB token activates the user
  - /login then succeeds
  - /me returns the right profile
  - bad password / bad token paths all rejected
"""

import pytest
from sqlalchemy import text


pytestmark = [pytest.mark.requires_db, pytest.mark.asyncio]


async def _fetch_token_for(db_session, email: str) -> str:
    """Pluck the verification token directly from the DB (faster than parsing SES log)."""
    row = (await db_session.execute(
        text("""
            SELECT t.token FROM auth_email_verification_tokens t
            JOIN auth_users u ON u.id = t.user_id
            WHERE u.email = :e AND t.used_at IS NULL
            ORDER BY t.created_at DESC LIMIT 1
        """),
        {"e": email},
    )).first()
    assert row is not None, f"No verification token found for {email}"
    return row[0]


class TestRegistration:
    async def test_happy_path(self, client):
        import secrets
        email = f"reg{secrets.token_hex(4)}@test.local"
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "RegisterPw123!", "full_name": "Test"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == email
        assert body["verification_required"] is True

    async def test_short_password_rejected(self, client):
        resp = await client.post(
            "/api/auth/register",
            json={"email": "short@test.local", "password": "short", "full_name": "x"},
        )
        assert resp.status_code in (400, 422)

    async def test_duplicate_email_rejected(self, client, new_user):
        creds = await new_user()
        resp = await client.post(
            "/api/auth/register",
            json={"email": creds["email"], "password": "another-password-1234", "full_name": "x"},
        )
        assert resp.status_code == 409

    async def test_malformed_email_rejected(self, client):
        resp = await client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "password": "ValidPw1234!", "full_name": "x"},
        )
        assert resp.status_code in (400, 422)


class TestLoginBlocksOnUnverified:
    async def test_unverified_user_cannot_login(self, client):
        import secrets
        email = f"unv{secrets.token_hex(4)}@test.local"
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "UnverifiedPw123!", "full_name": "x"},
        )
        assert resp.status_code == 201
        # User exists but is_email_verified=False
        login = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "UnverifiedPw123!"},
        )
        assert login.status_code == 403
        assert "verif" in login.json()["detail"].lower()


class TestVerifyEmail:
    async def test_verify_then_login(self, client, db_session):
        import secrets
        email = f"vfy{secrets.token_hex(4)}@test.local"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "VerifyPw123!", "full_name": "x"},
        )
        token = await _fetch_token_for(db_session, email)

        resp = await client.get(f"/api/auth/verify-email?token={token}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        login = await client.post(
            "/api/auth/login", json={"email": email, "password": "VerifyPw123!"}
        )
        assert login.status_code == 200
        body = login.json()
        assert "access_token" in body
        assert body["user"]["email"] == email
        assert "user" in body["user"]["roles"]

    async def test_invalid_token_rejected(self, client):
        resp = await client.get("/api/auth/verify-email?token=not-a-real-token-xxxxxxxx")
        assert resp.status_code == 400

    async def test_token_cannot_be_reused(self, client, db_session):
        import secrets
        email = f"reuse{secrets.token_hex(4)}@test.local"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "ReusePw1234!", "full_name": "x"},
        )
        token = await _fetch_token_for(db_session, email)

        ok = await client.get(f"/api/auth/verify-email?token={token}")
        assert ok.status_code == 200
        second = await client.get(f"/api/auth/verify-email?token={token}")
        assert second.status_code == 400


class TestLoginAndMe:
    async def test_wrong_password_rejected(self, client, new_user):
        creds = await new_user()
        resp = await client.post(
            "/api/auth/login",
            json={"email": creds["email"], "password": "wrong"},
        )
        assert resp.status_code == 401

    async def test_unknown_email_rejected(self, client):
        resp = await client.post(
            "/api/auth/login",
            json={"email": "nobody@test.local", "password": "anything"},
        )
        assert resp.status_code == 401

    async def test_me_returns_profile(self, admin_client):
        resp = await admin_client.get("/api/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "admin@test.local"
        assert body["is_admin"] is True

    async def test_anonymous_me_rejected(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_malformed_bearer_rejected(self, client):
        resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 401


class TestDevCredentials:
    async def test_returns_creds_when_flag_set(self, client):
        # The test stack sets EXPOSE_DEV_CREDENTIALS=true
        resp = await client.get("/api/auth/dev-credentials")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "admin@test.local"
        assert body["password"] == "TestAdmin12345!"
