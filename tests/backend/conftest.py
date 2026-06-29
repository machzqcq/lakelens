"""
Shared pytest fixtures.

Unit tests (``unit/``) don't use any of these — they're pure-logic tests.
Integration tests (``integration/``) use:

  - ``client``        unauthenticated httpx AsyncClient pointing at the live
                      backend in the test docker stack
  - ``admin_client``  pre-authenticated as the bootstrap admin
  - ``new_user``      factory that registers + verifies a fresh user
  - ``db_engine``     direct async SQLAlchemy engine for the test DB
                      (useful for inserting verification tokens / fixtures)
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import AsyncGenerator, Callable

# Make the backend importable no matter where pytest is invoked from.
# We look for a directory containing models.py — try a few candidates:
#   1. ../../backend (the standard host layout)
#   2. /app (the container layout — flat, no backend/ subdir)
#   3. any parent that has a models.py at any nesting up to 5 levels
_here = Path(__file__).resolve().parent
_candidates = [
    _here / ".." / ".." / "backend",            # tests/backend/../../backend
    Path("/app"),                                # container layout
]
for parent in [_here.parent, _here.parent.parent, _here.parent.parent.parent]:
    _candidates.append(parent / "backend")

for c in _candidates:
    try:
        if (c / "models.py").is_file():
            sys.path.insert(0, str(c.resolve()))
            break
    except OSError:
        continue

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# These point at the test stack from docker-compose.test.yml.
BACKEND_URL = os.getenv("TEST_BACKEND_URL", "http://localhost:58000")
DB_URL = os.getenv(
    "TEST_DB_URL",
    "postgresql+asyncpg://test_user:test_pass@localhost:55432/dbx_cost_test",
)

ADMIN_EMAIL = os.getenv("TEST_ADMIN_EMAIL", "admin@test.local")
ADMIN_PASSWORD = os.getenv("TEST_ADMIN_PASSWORD", "TestAdmin12345!")


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Direct DB engine. Use sparingly; prefer the HTTP API."""
    engine = create_async_engine(DB_URL, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    Session = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        yield s


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Anonymous HTTP client. No Authorization header."""
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=20.0) as c:
        yield c


@pytest_asyncio.fixture
async def admin_token(client: httpx.AsyncClient) -> str:
    """JWT for the bootstrap admin."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"admin login failed: {resp.status_code} {resp.text}"
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def admin_client(admin_token: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client pre-authed as admin."""
    async with httpx.AsyncClient(
        base_url=BACKEND_URL,
        timeout=20.0,
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def new_user(client: httpx.AsyncClient, db_engine) -> Callable:
    """Factory: register + verify a unique user; returns a ready-to-login dict."""

    async def _create(*, password: str = "PerUserPw123!", admin: bool = False) -> dict:
        email = f"u{secrets.token_hex(4)}@test.local"
        # Register
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "full_name": "Test User"},
        )
        assert resp.status_code == 201, f"register failed: {resp.status_code} {resp.text}"

        # Force-verify by flipping the DB flag (faster than parsing the SES
        # log link). Email verification is exercised separately in
        # test_auth_flow.py.
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker

        Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            await session.execute(
                text("UPDATE auth_users SET is_email_verified = TRUE WHERE email = :e"),
                {"e": email},
            )
            if admin:
                await session.execute(
                    text("""
                        INSERT INTO auth_user_roles (user_id, role_id)
                        SELECT u.id, r.id
                        FROM auth_users u, auth_roles r
                        WHERE u.email = :e AND r.name = 'admin'
                          AND NOT EXISTS (
                              SELECT 1 FROM auth_user_roles ur
                              WHERE ur.user_id = u.id AND ur.role_id = r.id
                          )
                    """),
                    {"e": email},
                )
            await session.commit()

        return {"email": email, "password": password}

    return _create


@pytest_asyncio.fixture
async def user_token(client: httpx.AsyncClient, new_user) -> str:
    creds = await new_user()
    resp = await client.post(
        "/api/auth/login",
        json={"email": creds["email"], "password": creds["password"]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def user_client(user_token: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client pre-authed as a regular (non-admin) user."""
    async with httpx.AsyncClient(
        base_url=BACKEND_URL,
        timeout=20.0,
        headers={"Authorization": f"Bearer {user_token}"},
    ) as c:
        yield c
