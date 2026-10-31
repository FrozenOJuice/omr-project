from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi import status
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from dependencies.auth_dep import require_admin
from models.user import User
from schemas.site_branding import SiteBrandingResponse
from services.site_branding import DEFAULT_SITE_LOGO_URL
from services.site_branding import MAX_SITE_LOGO_BYTES
from services.site_branding import get_custom_logo
from services.site_branding import get_site_branding
from services.site_branding import reset_site_logo
from services.site_branding import update_site_logo

router = APIRouter(prefix="/api", tags=["Site Branding"])


@router.get("/site-branding", response_model=SiteBrandingResponse)
async def read_site_branding(
    db: AsyncSession = Depends(get_db),
):
    return await get_site_branding(db)


@router.get("/site-branding/logo", response_class=Response)
async def read_site_logo(
    v: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    logo = await get_custom_logo(db)
    if logo is None:
        return RedirectResponse(
            DEFAULT_SITE_LOGO_URL,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Cache-Control": "no-store"},
        )

    data, content_type = logo
    cache_control = (
        "public, max-age=31536000, immutable"
        if v is not None
        else "no-store"
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": cache_control,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/admin/site-branding/logo",
    response_model=SiteBrandingResponse,
)
async def upload_site_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    data = await file.read(MAX_SITE_LOGO_BYTES + 1)
    if len(data) > MAX_SITE_LOGO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded logo exceeds the 2 MB limit",
        )

    return await update_site_logo(
        db,
        data=data,
    )


@router.delete(
    "/admin/site-branding/logo",
    response_model=SiteBrandingResponse,
)
async def restore_default_site_logo(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return await reset_site_logo(db)
