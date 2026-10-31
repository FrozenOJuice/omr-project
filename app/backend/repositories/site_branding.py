from sqlalchemy.ext.asyncio import AsyncSession

from models.site_branding import SiteBranding


async def get(db: AsyncSession) -> SiteBranding | None:
    return await db.get(SiteBranding, 1)


async def save_logo(
    db: AsyncSession,
    *,
    data: bytes | None,
    content_type: str | None,
) -> SiteBranding:
    branding = await get(db)
    if branding is None:
        branding = SiteBranding(id=1)
        db.add(branding)

    branding.logo_data = data
    branding.logo_content_type = content_type
    await db.flush()
    await db.refresh(branding)
    return branding
