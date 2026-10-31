from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from models.omr_detected_mark import MarkFieldType, OMRDetectedMark
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan

_TERMINAL_STATUSES = {"completed", "failed"}


async def create_marking(
    db: AsyncSession,
    scan_id: UUID,
    omr_template_id: UUID,
    status: str = "pending",
    flush: bool = True,
) -> OMRMarking:
    marking = OMRMarking(scan_id=scan_id, omr_template_id=omr_template_id, status=status)
    db.add(marking)
    if flush:
        await db.flush()
    return marking


async def create_detected_marks(
    db: AsyncSession,
    marking_id: UUID,
    marks: list[tuple[MarkFieldType, int, str | None, bool, int, dict, list[dict], float]],
    flush: bool = True,
) -> None:
    for field_type, field_index, detected_value, needs_review, page_index, bounds, boxes, confidence in marks:
        db.add(OMRDetectedMark(
            marking_id=marking_id,
            field_type=field_type,
            field_index=field_index,
            detected_value=detected_value,
            needs_review=needs_review,
            page_index=page_index,
            bounds=bounds,
            boxes=boxes,
            confidence_score=confidence,
        ))
    if flush:
        await db.flush()


async def get_omr_marking_by_id(db: AsyncSession, marking_id: UUID) -> OMRMarking | None:
    result = await db.execute(select(OMRMarking).where(OMRMarking.id == marking_id))
    return result.scalar_one_or_none()


async def get_scan_for_marking(db: AsyncSession, marking: OMRMarking) -> Scan | None:
    result = await db.execute(select(Scan).where(Scan.id == marking.scan_id))
    return result.scalar_one_or_none()


async def get_omr_markings_by_ids(
    db: AsyncSession, marking_ids: list[UUID]
) -> dict[UUID, OMRMarking]:
    """Batch form of get_omr_marking_by_id, for grading many markings from
    one pipeline run without one query per marking."""
    if not marking_ids:
        return {}
    result = await db.execute(select(OMRMarking).where(OMRMarking.id.in_(marking_ids)))
    return {marking.id: marking for marking in result.scalars().all()}


async def get_detected_marks_by_marking_ids(
    db: AsyncSession, marking_ids: list[UUID]
) -> dict[UUID, list[OMRDetectedMark]]:
    """Batch form of get_detected_marks, grouped by marking id."""
    if not marking_ids:
        return {}
    result = await db.execute(
        select(OMRDetectedMark)
        .options(
            load_only(
                OMRDetectedMark.marking_id,
                OMRDetectedMark.field_type,
                OMRDetectedMark.field_index,
                OMRDetectedMark.detected_value,
                OMRDetectedMark.needs_review,
            )
        )
        .where(OMRDetectedMark.marking_id.in_(marking_ids))
        .order_by(OMRDetectedMark.marking_id, OMRDetectedMark.field_type, OMRDetectedMark.field_index)
    )
    marks_by_marking: dict[UUID, list[OMRDetectedMark]] = {}
    for mark in result.scalars().all():
        marks_by_marking.setdefault(mark.marking_id, []).append(mark)
    return marks_by_marking


async def get_scans_by_ids(db: AsyncSession, scan_ids: list[UUID]) -> dict[UUID, Scan]:
    """Batch form of get_scan_for_marking, keyed by scan id."""
    if not scan_ids:
        return {}
    result = await db.execute(select(Scan).where(Scan.id.in_(scan_ids)))
    return {scan.id: scan for scan in result.scalars().all()}


async def get_page_counts_by_marking_ids(
    db: AsyncSession, marking_ids: list[UUID]
) -> dict[UUID, int]:
    """How many pages each marking's OMR template has, keyed by marking id.

    This is what a grade's page range for annotations/images comes from,
    since page indices are defined by the template, not the scan.
    """
    if not marking_ids:
        return {}
    result = await db.execute(
        select(OMRMarking.id, OMRTemplate.page_count)
        .join(OMRTemplate, OMRMarking.omr_template_id == OMRTemplate.id)
        .where(OMRMarking.id.in_(marking_ids))
    )
    return dict(result.all())


async def get_detected_marks(db: AsyncSession, marking_id: UUID) -> list[OMRDetectedMark]:
    result = await db.execute(
        select(OMRDetectedMark)
        .where(OMRDetectedMark.marking_id == marking_id)
        .order_by(OMRDetectedMark.field_type, OMRDetectedMark.field_index)
    )
    return list(result.scalars().all())


async def get_question_marks_for_page(
    db: AsyncSession, marking_id: UUID, page_index: int
) -> list[OMRDetectedMark]:
    """Answer-question marks (not name/id/version fields) on a single page.

    This is what an annotation view for that page needs to draw.
    """
    result = await db.execute(
        select(OMRDetectedMark)
        .where(
            OMRDetectedMark.marking_id == marking_id,
            OMRDetectedMark.field_type == MarkFieldType.QUESTION,
            OMRDetectedMark.page_index == page_index,
        )
        .order_by(OMRDetectedMark.field_index)
    )
    return list(result.scalars().all())


_IDENTITY_FIELD_TYPES = (MarkFieldType.LAST_NAME, MarkFieldType.FIRST_NAME, MarkFieldType.STUDENT_ID)


async def get_version_mark_for_page(
    db: AsyncSession, marking_id: UUID, page_index: int
) -> OMRDetectedMark | None:
    """The version-selector mark on a single page, if this template has one
    and it's on this page. Some blueprints infer version from Q1 instead
    (see detect_version_from_q1 in services/omr_mark_parsing.py) and have no
    dedicated version mark at all.
    """
    result = await db.execute(
        select(OMRDetectedMark).where(
            OMRDetectedMark.marking_id == marking_id,
            OMRDetectedMark.field_type == MarkFieldType.VERSION,
            OMRDetectedMark.page_index == page_index,
        )
    )
    return result.scalar_one_or_none()


async def get_identity_marks_for_page(
    db: AsyncSession, marking_id: UUID, page_index: int
) -> list[OMRDetectedMark]:
    """Name/student-ID bubble marks (not answer questions) on a single page.

    This is what an annotation view for that page needs to draw, and what
    decode_identity_fields needs to resolve the detected name/ID.
    """
    result = await db.execute(
        select(OMRDetectedMark)
        .where(
            OMRDetectedMark.marking_id == marking_id,
            OMRDetectedMark.field_type.in_(_IDENTITY_FIELD_TYPES),
            OMRDetectedMark.page_index == page_index,
        )
        .order_by(OMRDetectedMark.field_type, OMRDetectedMark.field_index)
    )
    return list(result.scalars().all())


async def get_identity_marks(db: AsyncSession, marking_id: UUID) -> list[OMRDetectedMark]:
    """All name/student-ID bubble marks for a marking, regardless of page.

    Used for a persistent (not page-scoped) summary of the detected
    identity, e.g. an always-visible card that also needs to know which
    page to jump to, unlike get_identity_marks_for_page above.
    """
    result = await db.execute(
        select(OMRDetectedMark)
        .where(
            OMRDetectedMark.marking_id == marking_id,
            OMRDetectedMark.field_type.in_(_IDENTITY_FIELD_TYPES),
        )
        .order_by(OMRDetectedMark.field_type, OMRDetectedMark.field_index)
    )
    return list(result.scalars().all())


async def update_marking_status(
    db: AsyncSession, marking_id: UUID, status: str
) -> OMRMarking | None:
    marking = await get_omr_marking_by_id(db, marking_id)
    if not marking:
        return None
    marking.status = status
    if status == "processing" and marking.started_at is None:
        marking.started_at = datetime.now(timezone.utc)
    elif status in _TERMINAL_STATUSES:
        marking.finished_at = datetime.now(timezone.utc)
    await db.flush()
    return marking
