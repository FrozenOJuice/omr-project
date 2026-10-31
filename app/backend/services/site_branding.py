from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import BadRequestError
from models.site_branding import SiteBranding
from repositories import site_branding
from schemas.site_branding import SiteBrandingResponse

DEFAULT_SITE_LOGO_URL = "/ApertureLogoFull.svg"
MAX_SITE_LOGO_BYTES = 2 * 1024 * 1024


def _detected_content_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _response(branding: SiteBranding | None) -> SiteBrandingResponse:
    if branding is None or branding.logo_data is None:
        return SiteBrandingResponse(
            logo_url=DEFAULT_SITE_LOGO_URL,
            is_custom_logo=False,
        )

    version = int(branding.updated_at.timestamp() * 1_000_000)
    return SiteBrandingResponse(
        logo_url=f"/api/site-branding/logo?v={version}",
        is_custom_logo=True,
    )


async def get_site_branding(db: AsyncSession) -> SiteBrandingResponse:
    return _response(await site_branding.get(db))


async def get_custom_logo(db: AsyncSession) -> tuple[bytes, str] | None:
    branding = await site_branding.get(db)
    if (
        branding is None
        or branding.logo_data is None
        or branding.logo_content_type is None
    ):
        return None
    return branding.logo_data, branding.logo_content_type


async def _save_site_logo(
    db: AsyncSession,
    *,
    data: bytes | None,
    content_type: str | None,
) -> SiteBrandingResponse:
    try:
        branding = await site_branding.save_logo(
            db,
            data=data,
            content_type=content_type,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _response(branding)


async def update_site_logo(
    db: AsyncSession,
    *,
    data: bytes,
) -> SiteBrandingResponse:
    if not data:
        raise BadRequestError("Select a logo image to upload", code="site_logo_empty")

    content_type = _detected_content_type(data)
    if content_type is None:
        raise BadRequestError(
            "Logo must be a PNG, JPEG, or WebP image",
            code="site_logo_invalid_type",
        )

    return await _save_site_logo(db, data=data, content_type=content_type)


async def reset_site_logo(db: AsyncSession) -> SiteBrandingResponse:
    return await _save_site_logo(db, data=None, content_type=None)
