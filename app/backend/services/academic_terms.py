import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from models.academic_term import AcademicTerm, AcademicTermType, AcademicTermYearFormat
from models.user import Institution, User, UserRole
from repositories import academic_terms
from schemas.academic_term import (
    AcademicTermListItemResponse,
    CreateAcademicTermRequest,
    UpdateAcademicTermRequest,
)


def normalize_term_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _term_code(name: str) -> str:
    code = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return code or "term"


async def list_terms(
    db: AsyncSession,
    user: User,
    *,
    institution: Institution | None = None,
    include_archived: bool = False,
) -> list[AcademicTermListItemResponse]:
    target = institution.value if institution else user.institution
    if target != user.institution and user.role_enum != UserRole.ADMIN:
        raise ForbiddenError(
            "Only administrators can view terms for another institution",
            code="academic_term_institution_forbidden",
        )
    terms = await academic_terms.list_available(
        db,
        target,
        user.id,
        include_archived=include_archived,
    )
    return [
        AcademicTermListItemResponse.model_validate(term).model_copy(
            update={"in_use": in_use}
        )
        for term, in_use in terms
    ]


async def create_term(
    db: AsyncSession,
    user: User,
    request: CreateAcademicTermRequest,
) -> AcademicTerm:
    is_preset = request.term_type == AcademicTermType.PRESET
    if is_preset and user.role_enum != UserRole.ADMIN:
        raise ForbiddenError(
            "Only administrators can create preset academic terms",
            code="academic_term_preset_admin_required",
        )

    institution = request.institution.value if request.institution else user.institution
    if institution != user.institution and (
        not is_preset or user.role_enum != UserRole.ADMIN
    ):
        raise ForbiddenError(
            "Academic terms must belong to your institution",
            code="academic_term_institution_forbidden",
        )

    normalized_name = normalize_term_name(request.name)
    await _ensure_name_available(
        db,
        institution,
        user.id,
        normalized_name,
        is_preset=is_preset,
    )
    code = _term_code(request.code or request.name) if is_preset else None
    if code and await academic_terms.find_preset_by_code(db, institution, code):
        raise ConflictError(
            "An academic term already uses this code",
            code="academic_term_code_exists",
        )

    try:
        term = await academic_terms.create(
            db,
            institution=institution,
            name=request.name,
            normalized_name=normalized_name,
            term_type=request.term_type,
            year_format=request.year_format.value,
            created_by=None if is_preset else user.id,
            code=code,
        )
        await db.commit()
        return term
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "An academic term with this name or code already exists",
            code="academic_term_exists",
        ) from exc
    except Exception:
        await db.rollback()
        raise


async def update_term(
    db: AsyncSession,
    term_id: UUID,
    user: User,
    request: UpdateAcademicTermRequest,
) -> AcademicTerm:
    term = await _editable_term(db, term_id, user)
    if request.name is not None:
        normalized_name = normalize_term_name(request.name)
        if normalized_name != term.normalized_name:
            await _ensure_name_available(
                db,
                term.institution,
                term.created_by or user.id,
                normalized_name,
                is_preset=term.term_type_enum == AcademicTermType.PRESET,
            )
        term.name = request.name
        term.normalized_name = normalized_name
    if request.year_format is not None:
        term.year_format = request.year_format.value
    if request.is_active is not None and request.is_active != term.is_active:
        if (
            not request.is_active
            and term.term_type_enum == AcademicTermType.PRESET
            and await academic_terms.count_active_presets(db, term.institution) <= 1
        ):
            raise ConflictError(
                "Each institution must retain at least one active preset term",
                code="academic_term_last_preset",
            )
        term.is_active = request.is_active

    try:
        await db.commit()
        await db.refresh(term)
        return term
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "An academic term with this name already exists",
            code="academic_term_exists",
        ) from exc
    except Exception:
        await db.rollback()
        raise


async def delete_term(db: AsyncSession, term_id: UUID, user: User) -> None:
    term = await _editable_term(db, term_id, user)
    if term.term_type_enum == AcademicTermType.PRESET:
        raise BadRequestError(
            "Preset academic terms must be archived instead of deleted",
            code="academic_term_preset_delete_forbidden",
        )
    if await academic_terms.is_in_use(db, term.id):
        raise ConflictError(
            "Academic terms used by courses cannot be deleted",
            code="academic_term_in_use",
        )
    try:
        await academic_terms.delete(db, term)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def resolve_for_course(
    db: AsyncSession,
    user: User,
    *,
    academic_term_id: UUID,
) -> AcademicTerm:
    term = await academic_terms.get_by_id(db, academic_term_id)
    if term is None:
        raise NotFoundError("Academic term not found", code="academic_term_not_found")
    if term.institution != user.institution or not term.is_active:
        raise BadRequestError(
            "Academic term is not available for this course",
            code="academic_term_unavailable",
        )
    if term.term_type_enum == AcademicTermType.CUSTOM and term.created_by != user.id:
        raise ForbiddenError(
            "Custom academic terms are only available to their creator",
            code="academic_term_owner_required",
        )
    return term


async def resolve_imported_term(
    db: AsyncSession,
    user: User,
    name: str,
) -> AcademicTerm:
    name = " ".join(name.split()) or "Canvas"
    normalized_name = normalize_term_name(name)
    preset = await academic_terms.find_preset_by_name(db, user.institution, normalized_name)
    if preset and preset.is_active:
        return preset
    custom = await academic_terms.find_custom_by_name(
        db, user.institution, user.id, normalized_name
    )
    if custom:
        if not custom.is_active:
            custom.is_active = True
        return custom
    return await academic_terms.create(
        db,
        institution=user.institution,
        name=name,
        normalized_name=normalized_name,
        term_type=AcademicTermType.CUSTOM,
        year_format=AcademicTermYearFormat.NONE.value,
        created_by=user.id,
    )


async def _editable_term(
    db: AsyncSession,
    term_id: UUID,
    user: User,
) -> AcademicTerm:
    term = await academic_terms.get_by_id(db, term_id)
    if term is None:
        raise NotFoundError("Academic term not found", code="academic_term_not_found")
    if term.term_type_enum == AcademicTermType.PRESET:
        if user.role_enum != UserRole.ADMIN:
            raise ForbiddenError(
                "Only administrators can change preset academic terms",
                code="academic_term_preset_admin_required",
            )
    elif user.role_enum != UserRole.ADMIN and term.created_by != user.id:
        raise ForbiddenError(
            "Custom academic terms are only editable by their creator",
            code="academic_term_owner_required",
        )
    return term


async def _ensure_name_available(
    db: AsyncSession,
    institution: str,
    user_id: UUID,
    normalized_name: str,
    *,
    is_preset: bool,
) -> None:
    preset = await academic_terms.find_preset_by_name(db, institution, normalized_name)
    custom = await academic_terms.find_custom_by_name(
        db, institution, user_id, normalized_name
    )
    if preset or custom or (is_preset and await _any_custom_name(db, institution, normalized_name)):
        raise ConflictError(
            "An academic term with this name already exists",
            code="academic_term_exists",
        )


async def _any_custom_name(
    db: AsyncSession,
    institution: str,
    normalized_name: str,
) -> bool:
    # Preset names must stay unambiguous for every user in the institution.
    return (
        await db.execute(
            select(AcademicTerm.id).where(
                AcademicTerm.institution == institution,
                AcademicTerm.term_type == AcademicTermType.CUSTOM.value,
                AcademicTerm.normalized_name == normalized_name,
            ).limit(1)
        )
    ).scalar_one_or_none() is not None
