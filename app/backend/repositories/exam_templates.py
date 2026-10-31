from datetime import datetime
from uuid import UUID
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_template import ExamTemplate
from models.scan import Scan
from schemas.exam_templates import CreateExamTemplateRequest


async def create_exam_template(
    db: AsyncSession,
    template_data: CreateExamTemplateRequest,
    total_questions: int,
    version: int,
    created_by: UUID,
    blueprint: str | None = None,
    version_from_q1: bool = False,
) -> ExamTemplate:
    new_version = template_data.version if template_data.version is not None else 1

    template = ExamTemplate(
        name=template_data.name,
        created_by=created_by,
        question_config={k: v.model_dump() for k, v in template_data.question_config.items()},
        sections=[section.model_dump() for section in template_data.sections],
        total_questions=total_questions,
        version=new_version,
        n_versions=template_data.n_versions,
        blueprint=blueprint,
        version_from_q1=version_from_q1,
    )
    db.add(template)
    await db.flush()
    return template


async def get_exam_template_by_id(db: AsyncSession, template_id: UUID) -> ExamTemplate | None:
    result = await db.execute(select(ExamTemplate).where(ExamTemplate.id == template_id))
    return result.scalars().first()


async def get_exam_templates_by_ids(
    db: AsyncSession, template_ids: list[UUID]
) -> dict[UUID, ExamTemplate]:
    if not template_ids:
        return {}
    result = await db.execute(
        select(ExamTemplate).where(ExamTemplate.id.in_(template_ids))
    )
    return {template.id: template for template in result.scalars().all()}


async def list_all_templates(
    db: AsyncSession, *, include_archived: bool = False
) -> list[ExamTemplate]:
    query = select(ExamTemplate)
    if not include_archived:
        query = query.where(ExamTemplate.archived_at.is_(None))
    result = await db.execute(
        query.order_by(ExamTemplate.archived_at.asc().nullsfirst(), ExamTemplate.name)
    )
    return list(result.scalars().all())


async def list_templates_by_creator(
    db: AsyncSession,
    user_id: UUID,
    *,
    include_archived: bool = False,
) -> list[ExamTemplate]:
    query = select(ExamTemplate).where(ExamTemplate.created_by == user_id)
    if not include_archived:
        query = query.where(ExamTemplate.archived_at.is_(None))
    result = await db.execute(
        query.order_by(ExamTemplate.archived_at.asc().nullsfirst(), ExamTemplate.name)
    )
    return list(result.scalars().all())


async def get_exam_template_by_omr_template_id(
    db: AsyncSession, omr_template_id: UUID
) -> ExamTemplate | None:
    result = await db.execute(
        select(ExamTemplate).where(ExamTemplate.omr_template_id == omr_template_id)
    )
    return result.scalar_one_or_none()


async def delete_exam_template(db: AsyncSession, template_id: UUID) -> bool:
    stmt = delete(ExamTemplate).where(ExamTemplate.id == template_id)
    result = await db.execute(stmt)
    return result.rowcount > 0


async def archive_exam_template(
    db: AsyncSession,
    template: ExamTemplate,
    archived_at: datetime,
) -> ExamTemplate:
    template.archived_at = archived_at
    await db.flush()
    await db.refresh(template)
    return template


async def restore_exam_template(
    db: AsyncSession,
    template: ExamTemplate,
) -> ExamTemplate:
    template.archived_at = None
    await db.flush()
    await db.refresh(template)
    return template


async def get_template_usage(db: AsyncSession, template_id: UUID) -> dict:
    exam_rows = await db.execute(
        select(Exam).where(Exam.exam_template_id == template_id)
    )
    exams_by_id = {exam.id: exam for exam in exam_rows.scalars().all()}

    answer_key_rows = await db.execute(
        select(ExamAnswerKey.exam_id, func.count(ExamAnswerKey.id))
        .where(ExamAnswerKey.exam_template_id == template_id)
        .group_by(ExamAnswerKey.exam_id)
    )
    answer_key_counts = dict(answer_key_rows.all())

    scan_rows = await db.execute(
        select(Scan.exam_id, func.count(Scan.id))
        .where(Scan.exam_template_id == template_id)
        .group_by(Scan.exam_id)
    )
    scan_counts = dict(scan_rows.all())

    missing_exam_ids = (
        set(answer_key_counts.keys())
        | set(scan_counts.keys())
    ) - set(exams_by_id.keys())
    if missing_exam_ids:
        linked_exam_rows = await db.execute(
            select(Exam).where(Exam.id.in_(missing_exam_ids))
        )
        exams_by_id.update({exam.id: exam for exam in linked_exam_rows.scalars().all()})

    exams = [
        {
            "id": exam.id,
            "name": exam.name,
            "course_id": exam.course_id,
            "answer_key_count": answer_key_counts.get(exam.id, 0),
            "scan_count": scan_counts.get(exam.id, 0),
        }
        for exam in sorted(exams_by_id.values(), key=lambda item: item.name.lower())
    ]

    return {
        "template_id": template_id,
        "exam_count": len(exams_by_id),
        "answer_key_count": sum(answer_key_counts.values()),
        "scan_count": sum(scan_counts.values()),
        "exams": exams,
    }


async def detach_template_references(db: AsyncSession, template_id: UUID) -> None:
    await db.execute(
        update(Exam)
        .where(Exam.exam_template_id == template_id)
        .values(exam_template_id=None)
    )
    await db.execute(
        update(ExamAnswerKey)
        .where(ExamAnswerKey.exam_template_id == template_id)
        .values(exam_template_id=None)
    )
    await db.execute(
        update(Scan)
        .where(Scan.exam_template_id == template_id)
        .values(exam_template_id=None)
    )
