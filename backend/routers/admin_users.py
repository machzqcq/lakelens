"""
Admin-only endpoints for managing users and roles. Every endpoint requires
the 'admin' role; non-admin users get 403.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, distinct, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, hash_password, require_admin
from database import get_db
from models import BillingUsage, Cluster, OAuthAccount, Role, User, UserRole

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    roles: list[str]
    oauth_providers: list[str]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)
    role_ids: list[int] = Field(default_factory=list)
    # Admin-created accounts skip email verification by default so the user
    # can sign in immediately. Set false to force the email flow.
    is_email_verified: bool = True


class UserPatch(BaseModel):
    is_active: Optional[bool] = None
    full_name: Optional[str] = Field(None, max_length=255)


class RoleOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_system: bool
    filters: Optional[dict[str, Any]] = None
    # Feature keys this role grants. None = grants everything (system roles,
    # legacy custom roles); explicit list = only those keys.
    features: Optional[list[str]] = None
    user_count: int = 0


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    description: Optional[str] = Field(None, max_length=500)
    filters: Optional[dict[str, Any]] = None
    features: Optional[list[str]] = None


class RolePatch(BaseModel):
    description: Optional[str] = Field(None, max_length=500)
    filters: Optional[dict[str, Any]] = None
    features: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    users = list((await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all())
    if not users:
        return []

    user_ids = [u.id for u in users]

    # Roles per user
    roles_by_user: dict[int, list[str]] = {u.id: [] for u in users}
    role_rows = (await db.execute(
        select(UserRole.user_id, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(user_ids))
    )).all()
    for uid, rname in role_rows:
        roles_by_user[uid].append(rname)

    # OAuth providers per user
    providers_by_user: dict[int, list[str]] = {u.id: [] for u in users}
    oauth_rows = (await db.execute(
        select(OAuthAccount.user_id, OAuthAccount.provider).where(OAuthAccount.user_id.in_(user_ids))
    )).all()
    for uid, provider in oauth_rows:
        providers_by_user[uid].append(provider)

    return [
        UserOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            is_email_verified=u.is_email_verified,
            created_at=u.created_at,
            roles=sorted(roles_by_user.get(u.id, [])),
            oauth_providers=sorted(providers_by_user.get(u.id, [])),
        )
        for u in users
    ]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(req: UserCreate, db: AsyncSession = Depends(get_db)):
    """Admin-provisioned account. Created active and (by default) pre-verified
    so the user can log in right away with the password set here."""
    email = req.email.lower().strip()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        is_active=True,
        is_email_verified=req.is_email_verified,
    )
    db.add(user)
    await db.flush()

    # Always grant the built-in 'user' role, then any extra roles requested.
    role_ids = set(req.role_ids)
    default = (await db.execute(select(Role).where(Role.name == "user"))).scalar_one_or_none()
    if default is not None:
        role_ids.add(default.id)
    for rid in role_ids:
        role = (await db.execute(select(Role).where(Role.id == rid))).scalar_one_or_none()
        if role is not None:
            db.add(UserRole(user_id=user.id, role_id=role.id))

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return await _user_out(db, user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, patch: UserPatch, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if patch.is_active is not None:
        user.is_active = patch.is_active
    if patch.full_name is not None:
        user.full_name = patch.full_name
    await db.commit()
    return await _user_out(db, user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(require_admin),
):
    if user_id == authed.user.id:
        raise HTTPException(status_code=400, detail="You can't delete your own account")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()


@router.post("/users/{user_id}/roles/{role_id}", response_model=UserOut)
async def assign_role(user_id: int, role_id: int, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if user is None or role is None:
        raise HTTPException(status_code=404, detail="User or role not found")
    db.add(UserRole(user_id=user_id, role_id=role_id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()  # already assigned — idempotent
    return await _user_out(db, user)


@router.delete("/users/{user_id}/roles/{role_id}", response_model=UserOut)
async def unassign_role(
    user_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(require_admin),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if user is None or role is None:
        raise HTTPException(status_code=404, detail="User or role not found")
    # Don't let an admin remove their own admin role and lock themselves out
    if user_id == authed.user.id and role.name == "admin":
        raise HTTPException(status_code=400, detail="You can't remove your own admin role")
    await db.execute(
        delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
    )
    await db.commit()
    return await _user_out(db, user)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: AsyncSession = Depends(get_db)):
    roles = list((await db.execute(select(Role).order_by(Role.is_system.desc(), Role.name))).scalars().all())
    counts: dict[int, int] = {}
    rows = (await db.execute(
        select(UserRole.role_id, UserRole.user_id)
    )).all()
    for rid, _uid in rows:
        counts[rid] = counts.get(rid, 0) + 1
    return [
        RoleOut(
            id=r.id, name=r.name, description=r.description,
            is_system=r.is_system, filters=r.filters or None,
            features=r.features, user_count=counts.get(r.id, 0),
        )
        for r in roles
    ]


def _validate_features(values: list[str]) -> list[str]:
    """Drop any keys that aren't in the registry. Caller may pass [] safely."""
    from features_registry import FEATURES_BY_KEY  # local import avoids cycle
    return sorted({k for k in values if k in FEATURES_BY_KEY})


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(req: RoleCreate, db: AsyncSession = Depends(get_db)):
    name = req.name.strip().lower()
    if name in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Reserved role name")
    existing = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Role name already exists")
    role = Role(
        name=name,
        description=req.description,
        is_system=False,
        filters=req.filters or {},
        features=_validate_features(req.features) if req.features is not None else None,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return RoleOut(id=role.id, name=role.name, description=role.description,
                   is_system=role.is_system, filters=role.filters,
                   features=role.features, user_count=0)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(role_id: int, patch: RolePatch, db: AsyncSession = Depends(get_db)):
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system and (patch.filters is not None or patch.features is not None):
        raise HTTPException(status_code=400, detail="Cannot edit filters or features on a system role")
    if patch.description is not None:
        role.description = patch.description
    if patch.filters is not None:
        role.filters = patch.filters
    if patch.features is not None:
        role.features = _validate_features(patch.features)
    await db.commit()
    return RoleOut(id=role.id, name=role.name, description=role.description,
                   is_system=role.is_system, filters=role.filters,
                   features=role.features, user_count=0)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(role_id: int, db: AsyncSession = Depends(get_db)):
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete a system role")
    await db.delete(role)
    await db.commit()


# ---------------------------------------------------------------------------
# Filter dimensions — populates role-builder dropdowns
# ---------------------------------------------------------------------------

@router.get("/feature-registry")
async def feature_registry():
    """The canonical list of toggleable features the Role editor renders.

    Same shape returned regardless of which role is being edited — the
    per-role enabled state lives in `RoleOut.features`.
    """
    from features_registry import FEATURES  # local import avoids cycle
    return {"features": FEATURES}


@router.get("/filter-dimensions")
async def filter_dimensions(db: AsyncSession = Depends(get_db)):
    """Distinct values for each filterable dimension, capped to keep the UI sane."""

    async def _distinct_strs(stmt, limit: int = 500) -> list[str]:
        rows = (await db.execute(stmt.limit(limit))).all()
        return sorted({str(r[0]) for r in rows if r[0] is not None})

    return {
        "workspace_ids": await _distinct_strs(
            select(distinct(BillingUsage.workspace_id)).order_by(BillingUsage.workspace_id)
        ),
        "clouds": await _distinct_strs(
            select(distinct(BillingUsage.cloud)).order_by(BillingUsage.cloud)
        ),
        "billing_origins": await _distinct_strs(
            select(distinct(BillingUsage.billing_origin_product)).order_by(BillingUsage.billing_origin_product)
        ),
        "cluster_sources": await _distinct_strs(
            select(distinct(Cluster.cluster_source)).order_by(Cluster.cluster_source)
        ),
        # SKU patterns are free-form; suggest a few common prefixes by sampling distinct names
        "sku_names": await _distinct_strs(
            select(distinct(BillingUsage.sku_name)).order_by(BillingUsage.sku_name)
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _user_out(db: AsyncSession, user: User) -> UserOut:
    role_names = [
        r for (r,) in (await db.execute(
            select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
        )).all()
    ]
    providers = [
        p for (p,) in (await db.execute(
            select(OAuthAccount.provider).where(OAuthAccount.user_id == user.id)
        )).all()
    ]
    return UserOut(
        id=user.id, email=user.email, full_name=user.full_name,
        is_active=user.is_active, is_email_verified=user.is_email_verified,
        created_at=user.created_at,
        roles=sorted(role_names), oauth_providers=sorted(providers),
    )
