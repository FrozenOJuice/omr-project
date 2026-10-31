from datetime import datetime, timezone
from uuid import UUID

from schemas.exam_templates import (
    CreateExamTemplateRequest,
    TemplateSection,
    UpdateExamTemplateRequest,
    default_template_sections,
    validate_template_sections,
)
from repositories.exam_templates import (
    archive_exam_template,
    create_exam_template,
    get_exam_template_by_id,
    delete_exam_template,
    detach_template_references,
    get_template_usage as get_template_usage_details,
    list_templates_by_creator,
    restore_exam_template,
)
from errors.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from constants.blueprints import (
    UBCO_100_BLUEPRINT,
    UBCO_100_QUESTION_CONFIG,
    UBCO_100_QUESTION_CONFIG_VERSIONED,
)
from schemas.exam_templates import ExamTemplateUsageResponse


def _ubco_template_name(name: str | None) -> str:
    """Every UBCO_100_BLUEPRINT template gets a "[UBCO] " prefix, so it stays
    unmistakably separate from custom-built templates even after a rename."""
    stripped = (name or "").strip()
    if stripped.startswith("[UBCO]"):
        return stripped
    return f"[UBCO] {stripped}" if stripped else "[UBCO] 100-Question Template"


async def create_new_template(db, template_data: CreateExamTemplateRequest, requesting_user_id: UUID):
    total_questions = len(template_data.question_config)
    try:
        db_template = await create_exam_template(
            db,
            template_data=template_data,
            total_questions=total_questions,
            version=template_data.version or 1,
            created_by=requesting_user_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return db_template


async def get_template(db, template_id: UUID, requesting_user_id: UUID | None = None):
    template = await get_exam_template_by_id(db, template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if requesting_user_id is not None and template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to view this template", code="forbidden")
    return template


async def update_existing_template(
    db,
    template_id: UUID,
    template_data: UpdateExamTemplateRequest,
    requesting_user_id: UUID,
):
    template = await get_exam_template_by_id(db, template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to modify this template", code="forbidden")
    if template.archived_at is not None:
        raise ConflictError(
            "Archived templates are read-only. Restore this template before making changes.",
            code="template_archived_read_only",
        )

    try:
        n_versions = template_data.n_versions
        versions_changed = n_versions is not None and n_versions != template.n_versions
        layout_changed = (
            template_data.question_config is not None
            or template_data.sections is not None
        )
        usage = (
            await get_template_usage(db, template_id)
            if layout_changed or versions_changed
            else None
        )

        if template_data.name is not None:
            template.name = (
                _ubco_template_name(template_data.name)
                if template.blueprint is not None
                else template_data.name
            )

        if layout_changed:
            # A generated PDF or registered OMR template can be regenerated
            # for free as long as no exam actually uses this template yet,
            # the same rule the version-count guard below follows. Once an
            # exam, answer key, or scan does reference it, the layout is
            # what they're built on and can't move out from under them.
            if (usage and usage.has_usage) or template.blueprint:
                raise ConflictError(
                    "Cannot change this template's question layout.",
                    code="template_locked",
                    details=usage.model_dump(mode="json"),
                )

            resolved_question_config = (
                template_data.question_config
                if template_data.question_config is not None
                else dict(template.question_config)
            )
            if template_data.sections is not None:
                resolved_sections = template_data.sections
            elif template_data.question_config is not None:
                existing_sections = template.sections or []
                assigned_question_ids = {
                    question_id
                    for section in existing_sections
                    for question_id in section["question_ids"]
                }
                added_question_ids = (
                    set(resolved_question_config) - assigned_question_ids
                )
                if added_question_ids:
                    raise BadRequestError(
                        "Include sections when adding questions to a sectioned template.",
                        code="template_sections_required",
                    )
                resolved_sections = [
                    TemplateSection.model_validate(
                        {
                            **section,
                            "question_ids": [
                                question_id
                                for question_id in section["question_ids"]
                                if question_id in resolved_question_config
                            ],
                        }
                    )
                    for section in existing_sections
                    if any(
                        question_id in resolved_question_config
                        for question_id in section["question_ids"]
                    )
                ]
                if not resolved_sections:
                    resolved_sections = default_template_sections(
                        resolved_question_config
                    )
            # Sections are replaced as one ordered collection. Questions from
            # a removed section are deleted unless the request moves them into
            # another section.
            if (
                template_data.sections is not None
                and template_data.question_config is None
            ):
                retained_question_ids = {
                    question_id
                    for section in template_data.sections
                    for question_id in section.question_ids
                }
                resolved_question_config = {
                    question_id: config
                    for question_id, config in resolved_question_config.items()
                    if question_id in retained_question_ids
                }
            try:
                validate_template_sections(resolved_question_config, resolved_sections)
            except ValueError as exc:
                raise BadRequestError(
                    str(exc), code="invalid_template_sections"
                ) from exc

            if resolved_question_config != template.question_config:
                template.question_config = {
                    key: item.model_dump()
                    if hasattr(item, "model_dump")
                    else item
                    for key, item in resolved_question_config.items()
                }
                template.total_questions = len(template.question_config)
            template.sections = [
                section.model_dump()
                if isinstance(section, TemplateSection)
                else section
                for section in resolved_sections
            ]
        if versions_changed:
            if template.blueprint and (
                not template.version_from_q1
                or not 2 <= n_versions <= 5
            ):
                raise BadRequestError(
                    "UBCO templates using Q1 support between 2 and 5 versions.",
                    code="invalid_template_versions",
                )
            if usage and usage.exam_count > 0:
                raise ConflictError(
                    "Cannot change the number of versions after assigning this template to an exam.",
                    code="template_versions_locked",
                    details=usage.model_dump(mode="json"),
                )

            template.n_versions = n_versions

        if layout_changed or versions_changed:
            # Both changes affect the generated PDF and OMR registration.
            template.generated_pdf_path = None
            template.omr_template_id = None

        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return template


async def create_template_from_ubco_blueprint(
    db,
    requesting_user_id: UUID,
    version: int | None = None,
    version_from_q1: bool = False,
    n_versions: int | None = None,
    name: str | None = None,
):
    question_config = UBCO_100_QUESTION_CONFIG_VERSIONED if version_from_q1 else UBCO_100_QUESTION_CONFIG
    # Q1 physically has A-E bubbles, so a version selector supports 2-5
    # versions. Requests that omit the count retain the original five-version
    # default; without a selector, the template has one version.
    resolved_n_versions = (n_versions or 5) if version_from_q1 else 1
    blueprint_payload = CreateExamTemplateRequest(
        name=_ubco_template_name(name),
        question_config=question_config,
        version=version,
        n_versions=resolved_n_versions,
    )

    try:
        db_template = await create_exam_template(
            db=db,
            template_data=blueprint_payload,
            total_questions=len(question_config),
            version=version or 1,
            created_by=requesting_user_id,
            blueprint=UBCO_100_BLUEPRINT,
            version_from_q1=version_from_q1,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return db_template


async def remove_template(
    db,
    template_id: UUID,
    requesting_user_id: UUID,
    *,
    force: bool = False,
):
    template = await get_exam_template_by_id(db, template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to delete this template", code="forbidden")

    usage = await get_template_usage(db, template_id)
    if usage.has_usage and not force:
        raise ConflictError(
            "This template is used by existing exams.",
            code="template_in_use",
            details=usage.model_dump(mode="json"),
        )

    try:
        if force:
            await detach_template_references(db, template_id)
        await delete_exam_template(db, template_id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def archive_template(
    db,
    template_id: UUID,
    requesting_user_id: UUID,
):
    template = await get_exam_template_by_id(db, template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to archive this template", code="forbidden")
    if template.archived_at is not None:
        return template

    try:
        archived = await archive_exam_template(
            db,
            template,
            datetime.now(timezone.utc),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return archived


async def restore_template(
    db,
    template_id: UUID,
    requesting_user_id: UUID,
):
    template = await get_exam_template_by_id(db, template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to restore this template", code="forbidden")
    if template.archived_at is None:
        return template

    try:
        restored = await restore_exam_template(db, template)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return restored


async def get_my_templates(
    db,
    user_id: UUID,
    *,
    include_archived: bool = False,
):
    return await list_templates_by_creator(
        db,
        user_id,
        include_archived=include_archived,
    )


async def get_template_usage(
    db,
    template_id: UUID,
    requesting_user_id: UUID | None = None,
) -> ExamTemplateUsageResponse:
    template = await get_exam_template_by_id(db, template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if requesting_user_id is not None and template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to view this template", code="forbidden")
    return ExamTemplateUsageResponse.model_validate(
        await get_template_usage_details(db, template_id)
    )
