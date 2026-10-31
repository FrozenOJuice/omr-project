from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.omr_template import OMRTemplate


async def create_omr_template(
    db: AsyncSession,
    name: str,
    page_count: int,
    scan_template_path: str,
    mark_template_path: str,
    preprocess_template_id: str | None = None,
    mark_template_id: str | None = None,
    native_dpi: float | None = None,
) -> OMRTemplate:
    template = OMRTemplate(
        name=name,
        page_count=page_count,
        scan_template_path=scan_template_path,
        mark_template_path=mark_template_path,
        preprocess_template_id=preprocess_template_id,
        mark_template_id=mark_template_id,
        native_dpi=native_dpi,
    )
    db.add(template)
    await db.flush()
    return template


async def get_omr_template_by_id(db: AsyncSession, template_id: UUID) -> OMRTemplate | None:
    result = await db.execute(select(OMRTemplate).where(OMRTemplate.id == template_id))
    return result.scalar_one_or_none()
