"""
Authentication endpoints: email/password signup + login, email verification,
and OAuth (google / microsoft / github) authorization-code flow.

OAuth providers are configured via env vars; if a provider's credentials are
missing the `/authorize` endpoint returns 503 so the frontend can disable
the button gracefully.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import (
    APP_BASE_URL,
    AuthedUser,
    create_access_token,
    get_current_user,
    hash_password,
    new_verification_token,
    send_verification_email,
    verify_password,
)
from database import get_db
from models import EmailVerificationToken, OAuthAccount, Role, User, UserRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)


class RegisterResponse(BaseModel):
    user_id: int
    email: str
    verification_required: bool = True
    message: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    user: "MeResponse"


class MeResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    is_active: bool
    is_email_verified: bool
    roles: list[str]
    is_admin: bool

    @classmethod
    def from_authed(cls, authed: AuthedUser) -> "MeResponse":
        return cls(
            id=authed.user.id,
            email=authed.user.email,
            full_name=authed.user.full_name,
            is_active=authed.user.is_active,
            is_email_verified=authed.user.is_email_verified,
            roles=sorted(authed.role_names),
            is_admin=authed.is_admin,
        )


class VerifyEmailResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _assign_default_role(db: AsyncSession, user_id: int) -> None:
    """Give a freshly-created user the built-in 'user' role."""
    role = (await db.execute(select(Role).where(Role.name == "user"))).scalar_one_or_none()
    if role is None:
        logger.warning("Default 'user' role not found; new user has no roles")
        return
    db.add(UserRole(user_id=user_id, role_id=role.id))


async def _create_verification_token(db: AsyncSession, user_id: int) -> str:
    token = new_verification_token()
    db.add(EmailVerificationToken(
        user_id=user_id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=24),
    ))
    return token


def _verify_link(token: str) -> str:
    return f"{APP_BASE_URL.rstrip('/')}/verify-email?token={token}"


# ---------------------------------------------------------------------------
# Email/password endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create an unverified account and email a verification link."""
    try:
        # Skip DNS check — pydantic's EmailStr already validates syntax, and
        # we don't want to fail on test/private domains during dev.
        validate_email(req.email, check_deliverability=False)
    except EmailNotValidError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = (await db.execute(select(User).where(User.email == req.email.lower()))).scalar_one_or_none()
    if existing is not None:
        # Don't leak whether the email is taken in detail; return 409
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        is_active=True,
        is_email_verified=False,
    )
    db.add(user)
    await db.flush()

    await _assign_default_role(db, user.id)
    token = await _create_verification_token(db, user.id)
    await db.commit()

    send_verification_email(user.email, _verify_link(token))

    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        message="Account created. Check your email to verify before logging in.",
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Email + password login. Returns a JWT access token."""
    user = (await db.execute(select(User).where(User.email == req.email.lower()))).scalar_one_or_none()
    if user is None or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    if not user.is_email_verified:
        raise HTTPException(status_code=403, detail="Email not verified. Check your inbox or request a new link.")

    roles_q = select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
    roles = list((await db.execute(roles_q)).scalars().all())
    authed = AuthedUser(user, roles)

    return LoginResponse(
        access_token=create_access_token(user.id, user.email),
        user=MeResponse.from_authed(authed),
    )


@router.get("/me", response_model=MeResponse)
async def me(authed: AuthedUser = Depends(get_current_user)):
    """Return the currently-authenticated user's profile + roles."""
    return MeResponse.from_authed(authed)


@router.get("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(token: str = Query(..., min_length=10, max_length=200), db: AsyncSession = Depends(get_db)):
    """Activate a user's email via the one-time token."""
    rec = (await db.execute(select(EmailVerificationToken).where(EmailVerificationToken.token == token))).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    if rec.used_at is not None:
        raise HTTPException(status_code=400, detail="Token already used")
    if rec.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token expired — request a new one")

    user = (await db.execute(select(User).where(User.id == rec.user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="User no longer exists")

    user.is_email_verified = True
    rec.used_at = datetime.utcnow()
    await db.commit()
    return VerifyEmailResponse(success=True, message="Email verified. You can now log in.")


@router.post("/resend-verification")
async def resend_verification(email: EmailStr, db: AsyncSession = Depends(get_db)):
    """Issue a new verification token + email it. Always returns success to avoid user enumeration."""
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if user is not None and not user.is_email_verified:
        token = await _create_verification_token(db, user.id)
        await db.commit()
        send_verification_email(user.email, _verify_link(token))
    return {"success": True, "message": "If that account needs verification, a new link has been sent."}


@router.post("/logout")
async def logout():
    """Stateless logout — the client just discards the token. Kept for API symmetry."""
    return {"success": True}


@router.get("/dev-credentials")
async def dev_credentials():
    """Return the bootstrap admin email + password from env vars.

    For local development only. Gated by EXPOSE_DEV_CREDENTIALS=true so it
    is impossible to enable accidentally in a real deployment. Returns 404
    otherwise. NEVER set EXPOSE_DEV_CREDENTIALS=true in any environment that
    isn't your laptop.
    """
    if os.getenv("EXPOSE_DEV_CREDENTIALS", "").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="Not available")

    email = (os.getenv("DEFAULT_ADMIN_EMAIL", "") or "").strip()
    password = (os.getenv("DEFAULT_ADMIN_PASSWORD", "") or "").strip()
    if not email or not password:
        raise HTTPException(status_code=404, detail="No bootstrap credentials configured")

    return {"email": email, "password": password}


# ---------------------------------------------------------------------------
# OAuth (google / microsoft / github)
# ---------------------------------------------------------------------------

class OAuthProvider:
    def __init__(
        self,
        name: str,
        client_id_env: str,
        client_secret_env: str,
        authorize_url: str,
        token_url: str,
        userinfo_url: str,
        scopes: str,
        extra_authorize_params: Optional[dict[str, str]] = None,
        userinfo_method: str = "GET",
        userinfo_auth_header: str = "Bearer {token}",
    ):
        self.name = name
        self.client_id_env = client_id_env
        self.client_secret_env = client_secret_env
        self.authorize_url = authorize_url
        self.token_url = token_url
        self.userinfo_url = userinfo_url
        self.scopes = scopes
        self.extra_authorize_params = extra_authorize_params or {}
        self.userinfo_method = userinfo_method
        self.userinfo_auth_header = userinfo_auth_header

    @property
    def client_id(self) -> Optional[str]:
        return os.getenv(self.client_id_env)

    @property
    def client_secret(self) -> Optional[str]:
        return os.getenv(self.client_secret_env)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


_PROVIDERS: dict[str, OAuthProvider] = {
    "google": OAuthProvider(
        name="google",
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scopes="openid email profile",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
    ),
    "microsoft": OAuthProvider(
        name="microsoft",
        client_id_env="MICROSOFT_OAUTH_CLIENT_ID",
        client_secret_env="MICROSOFT_OAUTH_CLIENT_SECRET",
        # Multi-tenant + personal accounts. Use 'common' tenant.
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        userinfo_url="https://graph.microsoft.com/oidc/userinfo",
        scopes="openid email profile",
    ),
    "github": OAuthProvider(
        name="github",
        client_id_env="GITHUB_OAUTH_CLIENT_ID",
        client_secret_env="GITHUB_OAUTH_CLIENT_SECRET",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scopes="read:user user:email",
    ),
}


def _redirect_uri(request: Request, provider: str) -> str:
    """Build the OAuth callback URL the providers redirect back to."""
    base = os.getenv("OAUTH_BACKEND_BASE_URL")
    if base:
        return f"{base.rstrip('/')}/api/auth/oauth/{provider}/callback"
    # Fall back to the request scheme/host (works for local dev with proxy)
    return str(request.url_for("oauth_callback", provider=provider))


# In-memory state store (CSRF token). Production: use Redis / DB / signed cookie.
_oauth_state: dict[str, dict[str, Any]] = {}


@router.get("/oauth/providers")
async def oauth_providers():
    """Tell the frontend which OAuth buttons to show."""
    return {p.name: p.configured for p in _PROVIDERS.values()}


@router.get("/oauth/{provider}/authorize")
async def oauth_authorize(provider: str, request: Request):
    p = _PROVIDERS.get(provider)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth provider: {provider}")
    if not p.configured:
        raise HTTPException(
            status_code=503,
            detail=f"{provider} OAuth not configured. Set {p.client_id_env} + {p.client_secret_env}.",
        )
    state = secrets.token_urlsafe(24)
    _oauth_state[state] = {"provider": provider, "created_at": datetime.utcnow()}

    params = {
        "client_id": p.client_id,
        "redirect_uri": _redirect_uri(request, provider),
        "response_type": "code",
        "scope": p.scopes,
        "state": state,
        **p.extra_authorize_params,
    }
    return {"url": f"{p.authorize_url}?{urlencode(params)}", "state": state}


@router.get("/oauth/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    p = _PROVIDERS.get(provider)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth provider: {provider}")
    if error:
        return RedirectResponse(f"{APP_BASE_URL}/login?error={error}")
    if not code or not state or state not in _oauth_state:
        raise HTTPException(status_code=400, detail="Missing or invalid OAuth state")
    _oauth_state.pop(state, None)

    redirect_uri = _redirect_uri(request, provider)

    # 1. Exchange code for token
    async with httpx.AsyncClient(timeout=20.0) as client:
        token_resp = await client.post(
            p.token_url,
            data={
                "client_id": p.client_id,
                "client_secret": p.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code >= 400:
            logger.warning("[oauth:%s] token exchange failed %s: %s", provider, token_resp.status_code, token_resp.text)
            raise HTTPException(status_code=502, detail="OAuth token exchange failed")
        tok = token_resp.json()
        access_token = tok.get("access_token")
        if not access_token:
            raise HTTPException(status_code=502, detail=f"No access_token in {provider} response")

        # 2. Fetch userinfo
        info_resp = await client.get(
            p.userinfo_url,
            headers={
                "Authorization": p.userinfo_auth_header.format(token=access_token),
                "Accept": "application/json",
            },
        )
        if info_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Failed to fetch {provider} userinfo")
        info = info_resp.json()

        # GitHub primary email needs a separate call when private
        if provider == "github" and not info.get("email"):
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            if emails_resp.status_code < 400:
                emails = emails_resp.json()
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                if primary:
                    info["email"] = primary["email"]

    # Normalize fields across providers
    if provider == "google":
        provider_user_id = str(info.get("sub", ""))
        email = info.get("email", "")
        full_name = info.get("name") or None
        email_verified = bool(info.get("email_verified", True))
    elif provider == "microsoft":
        provider_user_id = str(info.get("sub") or info.get("oid") or "")
        email = info.get("email") or info.get("preferred_username") or ""
        full_name = info.get("name") or None
        email_verified = True  # MS userinfo doesn't return email_verified; trust the IdP
    else:  # github
        provider_user_id = str(info.get("id", ""))
        email = info.get("email") or ""
        full_name = info.get("name") or info.get("login")
        email_verified = bool(email)

    if not provider_user_id or not email:
        raise HTTPException(status_code=502, detail=f"{provider} returned no user id or email")

    email = email.lower()

    # 3. Find or create the linked User
    link = (await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_user_id,
        )
    )).scalar_one_or_none()

    if link is not None:
        user = (await db.execute(select(User).where(User.id == link.user_id))).scalar_one_or_none()
    else:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                password_hash=None,
                full_name=full_name,
                is_active=True,
                is_email_verified=email_verified,
            )
            db.add(user)
            await db.flush()
            await _assign_default_role(db, user.id)
        else:
            # Existing email — link the OAuth identity and consider the email verified
            user.is_email_verified = user.is_email_verified or email_verified

        db.add(OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
        ))
        await db.flush()

    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    await db.commit()

    jwt_token = create_access_token(user.id, user.email)
    # Bounce the user back to the frontend with the token in the URL fragment
    # (fragment never hits server logs; the SPA reads it on /oauth/callback).
    return RedirectResponse(f"{APP_BASE_URL}/oauth/callback#access_token={jwt_token}&provider={provider}")


# Resolve forward reference in LoginResponse
LoginResponse.model_rebuild()
