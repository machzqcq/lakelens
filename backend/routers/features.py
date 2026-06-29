"""
Feature-flag state — computed PER USER from the features matrix stored on
their roles.

There is no global on/off table. Each role carries a `features` JSON column
(see `models.Role`) — a list of feature keys it grants. The effective set
for a user is computed as follows:

  - Admins  → every registered feature.
  - User has only system role(s) (the bootstrap 'user' grant) → every feature.
  - User has at least one custom (non-system) role → UNION of `features`
    across those custom roles. A custom role with `features = NULL` (legacy)
    counts as 'grants everything'; with `features = []` counts as 'grants
    nothing'.

This mirrors the existing `rbac_filters.resolve_effective_filters` semantics
so admins / power users keep their reach while explicitly-scoped custom
roles can subtract capabilities. The endpoint is read-only and available to
any signed-in user — admins edit the matrix on the Role create/edit page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from features_registry import FEATURES, FEATURES_BY_KEY

state_router = APIRouter(prefix="/api/features", tags=["features"])


class FeatureStateMap(BaseModel):
    features: dict[str, bool]


def effective_feature_keys(user: AuthedUser) -> set[str]:
    """Resolve which feature keys are enabled for this user.

    Public so route guards and other backend code can call it directly.
    """
    all_keys = {spec["key"] for spec in FEATURES}
    if user.is_admin:
        return all_keys
    custom_roles = [r for r in user.roles if not r.is_system]
    if not custom_roles:
        return all_keys  # plain 'user' role → everything
    granted: set[str] = set()
    for r in custom_roles:
        feats = r.features
        if feats is None:
            return all_keys  # legacy / unscoped custom role unlocks all
        granted.update(k for k in feats if k in FEATURES_BY_KEY)
    return granted


@state_router.get("/state", response_model=FeatureStateMap)
async def feature_state(
    user: AuthedUser = Depends(get_current_user),
    _db: AsyncSession = Depends(get_db),
):
    """Compact {key: enabled} map for the calling user.

    Every registered key is present so the client never needs to know the
    feature registry. Unknown / retired keys are omitted.
    """
    granted = effective_feature_keys(user)
    return FeatureStateMap(features={spec["key"]: (spec["key"] in granted) for spec in FEATURES})
