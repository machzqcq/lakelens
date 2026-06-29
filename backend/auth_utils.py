"""
Auth utilities: password hashing, JWT, email sending (SES with dev fallback),
FastAPI dependencies for current-user and admin gating.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Role, User, UserRole

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (env-driven)
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me-please-256-bit-secret")
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "24"))

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:3000")

# AWS SES — if any of these are missing we fall back to logging the link
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
SES_FROM_EMAIL = os.getenv("SES_FROM_EMAIL")


# ---------------------------------------------------------------------------
# Password hashing (bcrypt directly — passlib's bcrypt detection breaks on
# bcrypt 4.x because it dropped __about__.__version__)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """bcrypt-hash a password. Truncates to 72 bytes per bcrypt's limit."""
    if not password:
        raise ValueError("Password must not be empty")
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check. Returns False on any malformed hash."""
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, email: str, extra: Optional[dict[str, Any]] = None) -> str:
    """Issue an HS256-signed JWT for the user."""
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_TTL_HOURS)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")


# ---------------------------------------------------------------------------
# Verification tokens
# ---------------------------------------------------------------------------

def new_verification_token() -> str:
    """48-byte URL-safe token (~64 chars)."""
    return secrets.token_urlsafe(48)


# ---------------------------------------------------------------------------
# Email (AWS SES with dev fallback)
# ---------------------------------------------------------------------------

def send_verification_email(to_email: str, verify_link: str) -> None:
    """Send a verification email via SES if configured, else log the link."""
    subject = "Verify your email - Databricks Billing Dashboard"
    text_body = (
        f"Welcome!\n\n"
        f"Please verify your email by visiting:\n{verify_link}\n\n"
        f"The link expires in 24 hours. If you didn't sign up, you can ignore this email.\n"
    )
    html_body = (
        f"<p>Welcome!</p>"
        f"<p>Please verify your email by clicking the link below:</p>"
        f'<p><a href="{verify_link}">{verify_link}</a></p>'
        f"<p>The link expires in 24 hours. If you didn't sign up, you can ignore this email.</p>"
    )

    if AWS_REGION and SES_FROM_EMAIL:
        try:
            import boto3

            client = boto3.client("ses", region_name=AWS_REGION)
            client.send_email(
                Source=SES_FROM_EMAIL,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                },
            )
            logger.info("[ses] Sent verification email to %s", to_email)
            return
        except Exception:
            logger.exception(
                "[ses] Failed to send verification email to %s — falling back to log", to_email
            )

    # Dev fallback — print the link so you can copy/paste during development
    logger.warning(
        "\n=========================================================\n"
        "[email] DEV MODE — SES not configured.\n"
        "[email] Verification link for %s:\n"
        "[email]   %s\n"
        "=========================================================",
        to_email,
        verify_link,
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def _load_user_with_roles(db: AsyncSession, user_id: int) -> Optional[tuple[User, list[Role]]]:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return None
    roles_q = select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    roles = list((await db.execute(roles_q)).scalars().all())
    return user, roles


class AuthedUser:
    """Resolved current-user bundle: User + their list of Role objects."""

    def __init__(self, user: User, roles: list[Role]):
        self.user = user
        self.roles = roles

    @property
    def role_names(self) -> set[str]:
        return {r.name for r in self.roles}

    @property
    def is_admin(self) -> bool:
        return "admin" in self.role_names

    @property
    def viewing_data_mode(self) -> str:
        """Per-user sticky view mode for the data-isolation system.
        'real' (default) or 'demo'. See backend/data_scope.py."""
        return getattr(self.user, "viewing_data_mode", None) or "real"


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> AuthedUser:
    """Resolve the bearer token to a User. Raises 401 on any auth failure."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    loaded = await _load_user_with_roles(db, user_id)
    if loaded is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    user, roles = loaded
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")
    if not user.is_email_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return AuthedUser(user, roles)


async def require_admin(authed: AuthedUser = Depends(get_current_user)) -> AuthedUser:
    if not authed.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    return authed
