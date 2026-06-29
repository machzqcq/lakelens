"""Metadata lookups: shared dimension-name resolution for the UI.

Currently exposes the workspace_id → workspace_name map used by the SKU &
Billing-Origin page (and reusable elsewhere). Respects the caller's data
scope: a user with workspace_ids restriction sees only their workspaces.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import Workspace
from rbac_filters import resolve_effective_filters

router = APIRouter(
    prefix="/api/metadata",
    tags=["metadata"],
    dependencies=[Depends(get_current_user)],
)


class WorkspaceMeta(BaseModel):
    workspace_id: str
    workspace_name: Optional[str] = None
    workspace_url: Optional[str] = None
    status: Optional[str] = None


class WorkspaceListResponse(BaseModel):
    data: list[WorkspaceMeta]


@router.get("/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Return all known workspaces visible to the caller.

    `workspace_name` may be NULL if the source system (Databricks
    `system.access.workspaces_latest`) didn't carry one — the UI should fall
    back to displaying `workspace_id` in that case.
    """
    stmt = select(
        Workspace.workspace_id,
        Workspace.workspace_name,
        Workspace.workspace_url,
        Workspace.status,
    ).where(
        Workspace.data_origin == authed.viewing_data_mode
    ).where(
        Workspace.deleted_at.is_(None)
    )
    rbac = resolve_effective_filters(authed)
    if rbac and rbac.get("__deny_all__"):
        return WorkspaceListResponse(data=[])
    if rbac and rbac.get("workspace_ids"):
        ids = [str(v) for v in rbac["workspace_ids"]]
        stmt = stmt.where(Workspace.workspace_id.in_(ids))

    rows = (await db.execute(stmt)).all()
    return WorkspaceListResponse(data=[
        WorkspaceMeta(
            workspace_id=r.workspace_id,
            workspace_name=r.workspace_name,
            workspace_url=r.workspace_url,
            status=r.status,
        )
        for r in rows
    ])
