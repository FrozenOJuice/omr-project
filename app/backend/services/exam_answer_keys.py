from string import ascii_uppercase
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from errors.exceptions import NotFoundError, ForbiddenError, BadRequestError
from repositories.exam_answer_keys import (
    create_exam_answer_key,
    get_answer_key_by_id,
    get_answer_key_by_version,
    list_answer_keys_by_exam,
    update_exam_answer_key,
    delete_exam_answer_key,
)
from repositories.exam_templates import get_exam_template_by_id
from repositories.exams import get_exam_by_id
from schemas.exam_answer_keys import CreateExamAnswerKeyRequest, UpdateExamAnswerKeyRequest
from services.course_lifecycle import ensure_exam_course_writable, ensure_exam_not_graded


async def create_new_answer_key(
    db: AsyncSession,
    exam_id: UUID,
    data: CreateExamAnswerKeyRequest,
    requesting_user_id: UUID,
):
    exam = await get_exam_by_id(db, exam_id)
    if not exam:
        raise NotFoundError("Exam not found", code="exam_not_found")
    if exam.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to modify this exam", code="forbidden")
    await ensure_exam_course_writable(db, exam_id)
    await ensure_exam_not_graded(db, exam_id)

    template = await get_exam_template_by_id(db, data.exam_template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if exam.exam_template_id != data.exam_template_id:
        raise ForbiddenError(
            "Template does not match this exam's assigned template", code="template_exam_mismatch"
        )

    _validate_exam_version(data.exam_version, template.n_versions)

    existing = await get_answer_key_by_version(
        db, exam_id, data.exam_template_id, data.exam_version
    )
    if existing:
        version_label = data.exam_version or "default"
        raise ForbiddenError(
            f"An answer key for version '{version_label}' already exists for this template",
            code="answer_key_version_conflict",
        )

    _validate_answer_key_choices(data.answer_key, template.question_config)

    try:
        answer_key = await create_exam_answer_key(db, exam_id, data)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return answer_key


async def get_answer_key(db: AsyncSession, answer_key_id: UUID):
    key = await get_answer_key_by_id(db, answer_key_id)
    if not key:
        raise NotFoundError("Answer key not found", code="answer_key_not_found")
    return key


async def get_answer_keys_for_exam(db: AsyncSession, exam_id: UUID):
    return await list_answer_keys_by_exam(db, exam_id)


async def update_existing_answer_key(
    db: AsyncSession,
    answer_key_id: UUID,
    data: UpdateExamAnswerKeyRequest,
    requesting_user_id: UUID,
):
    key = await get_answer_key_by_id(db, answer_key_id)
    if not key:
        raise NotFoundError("Answer key not found", code="answer_key_not_found")

    exam = await get_exam_by_id(db, key.exam_id)
    if not exam or exam.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to modify this answer key", code="forbidden")
    await ensure_exam_course_writable(db, key.exam_id)
    await ensure_exam_not_graded(db, key.exam_id)

    try:
        if data.answer_key is not None:
            template = await get_exam_template_by_id(db, key.exam_template_id)
            if not template:
                raise NotFoundError("Associated template not found", code="template_not_found")
            _validate_answer_key_choices(data.answer_key, template.question_config)
            merged = dict(key.answer_key)
            for q, item in data.answer_key.items():
                merged[q] = item.model_dump()
            key.answer_key = merged
            flag_modified(key, "answer_key")

        if data.scoring_rules is not None:
            key.scoring_rules = data.scoring_rules
            flag_modified(key, "scoring_rules")

        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return key


async def remove_answer_key(
    db: AsyncSession,
    answer_key_id: UUID,
    requesting_user_id: UUID,
):
    key = await get_answer_key_by_id(db, answer_key_id)
    if not key:
        raise NotFoundError("Answer key not found", code="answer_key_not_found")

    exam = await get_exam_by_id(db, key.exam_id)
    if not exam or exam.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to delete this answer key", code="forbidden")
    await ensure_exam_course_writable(db, key.exam_id)
    await ensure_exam_not_graded(db, key.exam_id)

    try:
        await delete_exam_answer_key(db, answer_key_id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _validate_answer_key_choices(
    answer_key: dict,
    question_config: dict,
) -> None:
    for question_num, item in answer_key.items():
        if question_num not in question_config:
            raise BadRequestError(
                f"Question '{question_num}' in answer key does not exist in template",
                code="invalid_answer_key",
            )
        allowed_choices = set(question_config[question_num]["choices"])
        for choice in item.correct_choices:
            if choice not in allowed_choices:
                raise BadRequestError(
                    f"Choice '{choice}' for question '{question_num}' is not a valid option",
                    code="invalid_answer_key",
                )
        if item.partial_weights:
            for choice in item.partial_weights:
                if choice not in allowed_choices:
                    raise BadRequestError(
                        f"Partial weight choice '{choice}' for question '{question_num}' is not valid",
                        code="invalid_answer_key",
                    )


def _validate_exam_version(exam_version: str | None, version_count: int) -> None:
    if version_count == 1:
        if exam_version is not None:
            raise BadRequestError(
                "This exam uses one unversioned answer key.",
                code="invalid_answer_key_version",
            )
        return

    allowed_versions = ascii_uppercase[:version_count]
    if exam_version is None:
        raise BadRequestError(
            f"This exam requires an answer key for each version ({', '.join(allowed_versions)}).",
            code="answer_key_version_required",
        )
    if exam_version not in allowed_versions:
        raise BadRequestError(
            f"Version {exam_version} is not used by this exam.",
            code="invalid_answer_key_version",
        )
