from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.exam_answer_key import ExamAnswerKey
from models.exam_template import ExamTemplate
from schemas.exam_answer_keys import CreateExamAnswerKeyRequest, UpdateExamAnswerKeyRequest


async def create_exam_answer_key(
    db: AsyncSession,
    exam_id: UUID,
    data: CreateExamAnswerKeyRequest,
) -> ExamAnswerKey:
    key = ExamAnswerKey(
        exam_id=exam_id,
        exam_template_id=data.exam_template_id,
        exam_version=data.exam_version,
        answer_key={k: v.model_dump() for k, v in data.answer_key.items()},
        scoring_rules=data.scoring_rules,
    )
    db.add(key)
    await db.flush()
    return key


async def get_answer_key_by_id(
    db: AsyncSession, answer_key_id: UUID
) -> ExamAnswerKey | None:
    result = await db.execute(
        select(ExamAnswerKey).where(ExamAnswerKey.id == answer_key_id)
    )
    return result.scalar_one_or_none()


async def get_exam_ids_by_answer_key_ids(
    db: AsyncSession, answer_key_ids: list[UUID]
) -> dict[UUID, UUID]:
    if not answer_key_ids:
        return {}
    result = await db.execute(
        select(ExamAnswerKey.id, ExamAnswerKey.exam_id).where(ExamAnswerKey.id.in_(answer_key_ids))
    )
    return dict(result.all())


async def get_exam_versions_by_answer_key_ids(
    db: AsyncSession, answer_key_ids: list[UUID]
) -> dict[UUID, str | None]:
    if not answer_key_ids:
        return {}
    result = await db.execute(
        select(ExamAnswerKey.id, ExamAnswerKey.exam_version).where(ExamAnswerKey.id.in_(answer_key_ids))
    )
    return dict(result.all())


async def get_template_sections_by_answer_key_ids(
    db: AsyncSession, answer_key_ids: list[UUID]
) -> dict[UUID, list[dict]]:
    if not answer_key_ids:
        return {}
    result = await db.execute(
        select(ExamAnswerKey.id, ExamTemplate.sections)
        .outerjoin(ExamTemplate, ExamAnswerKey.exam_template_id == ExamTemplate.id)
        .where(ExamAnswerKey.id.in_(answer_key_ids))
    )
    return {
        answer_key_id: sections or []
        for answer_key_id, sections in result.all()
    }


async def get_answer_key_by_version(
    db: AsyncSession,
    exam_id: UUID,
    exam_template_id: UUID,
    exam_version: str | None,
) -> ExamAnswerKey | None:
    result = await db.execute(
        select(ExamAnswerKey).where(
            ExamAnswerKey.exam_id == exam_id,
            ExamAnswerKey.exam_template_id == exam_template_id,
            ExamAnswerKey.exam_version == exam_version,
        )
    )
    return result.scalar_one_or_none()


async def list_answer_keys_by_exam(
    db: AsyncSession, exam_id: UUID
) -> list[ExamAnswerKey]:
    result = await db.execute(
        select(ExamAnswerKey)
        .where(ExamAnswerKey.exam_id == exam_id)
        .order_by(ExamAnswerKey.created_at)
    )
    return list(result.scalars().all())


async def list_answer_keys_by_exam_ids(
    db: AsyncSession, exam_ids: list[UUID]
) -> dict[UUID, list[ExamAnswerKey]]:
    if not exam_ids:
        return {}
    result = await db.execute(
        select(ExamAnswerKey)
        .where(ExamAnswerKey.exam_id.in_(exam_ids))
        .order_by(ExamAnswerKey.created_at)
    )
    grouped = {exam_id: [] for exam_id in exam_ids}
    for answer_key in result.scalars().all():
        grouped[answer_key.exam_id].append(answer_key)
    return grouped


async def list_answer_keys_by_template(
    db: AsyncSession, exam_template_id: UUID
) -> list[ExamAnswerKey]:
    result = await db.execute(
        select(ExamAnswerKey)
        .where(ExamAnswerKey.exam_template_id == exam_template_id)
        .order_by(ExamAnswerKey.exam_version.nullsfirst(), ExamAnswerKey.created_at)
    )
    return list(result.scalars().all())


async def update_exam_answer_key(
    db: AsyncSession,
    answer_key: ExamAnswerKey,
    data: UpdateExamAnswerKeyRequest,
) -> ExamAnswerKey:
    if data.answer_key is not None:
        answer_key.answer_key = {k: v.model_dump() for k, v in data.answer_key.items()}
    if data.scoring_rules is not None:
        answer_key.scoring_rules = data.scoring_rules
    await db.flush()
    return answer_key


async def delete_exam_answer_key(db: AsyncSession, answer_key_id: UUID) -> bool:
    result = await db.execute(
        delete(ExamAnswerKey).where(ExamAnswerKey.id == answer_key_id)
    )
    return result.rowcount > 0


async def delete_answer_keys_by_exam(db: AsyncSession, exam_id: UUID) -> None:
    await db.execute(
        delete(ExamAnswerKey).where(ExamAnswerKey.exam_id == exam_id)
    )
