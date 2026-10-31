from fastapi import APIRouter, Depends, status

from db.session import get_db
from dependencies.auth_dep import require_admin_or_prof
from models.user import User
from schemas.retention_policy import (
    RetentionPolicyResponse,
    RetentionPolicyStatusResponse,
    RetentionPolicyUpsertRequest,
)
from services import retention_policies


router = APIRouter(prefix="/api/retention-policy", tags=["retention-policy"])


@router.get("", response_model=RetentionPolicyStatusResponse)
async def get_retention_policy(
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await retention_policies.get_current_policy(db, user)


@router.put("", response_model=RetentionPolicyResponse)
async def upsert_retention_policy(
    request: RetentionPolicyUpsertRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await retention_policies.upsert_current_policy(db, user, request)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_retention_policy(
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    await retention_policies.delete_current_policy(db, user)
