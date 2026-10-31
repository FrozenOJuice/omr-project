from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.academic_term import AcademicTerm, AcademicTermType
from models.course import Course


async def get_by_id(db: AsyncSession, term_id: UUID) -> AcademicTerm | None:
    return (
        await db.execute(select(AcademicTerm).where(AcademicTerm.id == term_id))
    ).scalar_one_or_none()


async def list_available(
    db: AsyncSession,
    institution: str,
    user_id: UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[AcademicTerm, bool]]:
    in_use = (
        select(Course.id)
        .where(Course.academic_term_id == AcademicTerm.id)
        .exists()
    )
    statement = select(AcademicTerm, in_use.label("in_use")).where(
        AcademicTerm.institution == institution,
        or_(
            AcademicTerm.term_type == AcademicTermType.PRESET.value,
            AcademicTerm.created_by == user_id,
        ),
    )
    if not include_archived:
        statement = statement.where(AcademicTerm.is_active.is_(True))
    statement = statement.order_by(
        AcademicTerm.term_type.desc(),
        func.lower(AcademicTerm.name),
    )
    return [
        (term, bool(term_in_use))
        for term, term_in_use in (await db.execute(statement)).all()
    ]


async def find_preset_by_name(
    db: AsyncSession,
    institution: str,
    normalized_name: str,
) -> AcademicTerm | None:
    return (
        await db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution == institution,
                AcademicTerm.term_type == AcademicTermType.PRESET.value,
                AcademicTerm.normalized_name == normalized_name,
            )
        )
    ).scalar_one_or_none()


async def find_custom_by_name(
    db: AsyncSession,
    institution: str,
    user_id: UUID,
    normalized_name: str,
) -> AcademicTerm | None:
    return (
        await db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution == institution,
                AcademicTerm.term_type == AcademicTermType.CUSTOM.value,
                AcademicTerm.created_by == user_id,
                AcademicTerm.normalized_name == normalized_name,
            )
        )
    ).scalar_one_or_none()


async def find_preset_by_code(
    db: AsyncSession,
    institution: str,
    code: str,
) -> AcademicTerm | None:
    return (
        await db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution == institution,
                AcademicTerm.code == code,
            )
        )
    ).scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    institution: str,
    name: str,
    normalized_name: str,
    term_type: AcademicTermType,
    year_format: str,
    created_by: UUID | None,
    code: str | None = None,
) -> AcademicTerm:
    term = AcademicTerm(
        institution=institution,
        code=code,
        name=name,
        normalized_name=normalized_name,
        term_type=term_type.value,
        year_format=year_format,
        created_by=created_by,
    )
    db.add(term)
    await db.flush()
    await db.refresh(term)
    return term


async def count_active_presets(db: AsyncSession, institution: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(AcademicTerm)
            .where(
                AcademicTerm.institution == institution,
                AcademicTerm.term_type == AcademicTermType.PRESET.value,
                AcademicTerm.is_active.is_(True),
            )
        )
    ).scalar_one()


async def is_in_use(db: AsyncSession, term_id: UUID) -> bool:
    return (
        await db.execute(
            select(func.count()).select_from(Course).where(Course.academic_term_id == term_id)
        )
    ).scalar_one() > 0


async def delete(db: AsyncSession, term: AcademicTerm) -> None:
    await db.delete(term)
    await db.flush()
