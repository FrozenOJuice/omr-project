from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.course_roster_entry import CourseRosterEntry
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.notification import Notification
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.retention_policy import RetentionPolicy
from models.review_request import ReviewRequest
from models.review_request_audit_entry import ReviewRequestAuditEntry
from models.scan import Scan
from models.user import User
from repositories.storage import StorageRepository
from services.course_stats import get_course_stats


async def process_due_retention(
    db: AsyncSession,
    storage: StorageRepository,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    courses = list((await db.execute(
        select(Course)
        .where(Course.archived_at.is_not(None))
        .with_for_update(skip_locked=True)
    )).scalars())
    result = {"scanned_images": 0, "exam_records": 0}

    for course in courses:
        if (
            course.scanned_images_purged_at is None
            and course.scanned_images_retention_until is not None
            and course.scanned_images_retention_until <= now
        ):
            await _purge_scan_images(db, storage, course, now)
            result["scanned_images"] += 1

        if (
            course.exam_records_purged_at is None
            and course.exam_records_retention_until is not None
            and course.exam_records_retention_until <= now
        ):
            # Student records cannot be safely removed while identifiable scan
            # images remain, even when the image policy was configured longer.
            if course.scanned_images_purged_at is None:
                await _purge_scan_images(db, storage, course, now)
                result["scanned_images"] += 1
            await _purge_student_records(db, course, now)
            result["exam_records"] += 1

    await db.commit()
    return result


async def _course_scans(db: AsyncSession, course_id):
    return list((await db.execute(
        select(Scan)
        .join(Exam, Exam.id == Scan.exam_id)
        .where(Exam.course_id == course_id)
    )).scalars())


async def _purge_scan_images(db, storage, course: Course, now: datetime) -> None:
    scans = await _course_scans(db, course.id)
    for scan in scans:
        if scan.path:
            storage.delete_file(scan.path)
        storage.delete_directory(f"processed-pages/{scan.id}/")
        marking = (await db.execute(select(OMRMarking).where(OMRMarking.scan_id == scan.id))).scalar_one_or_none()
        if marking and marking.marked_file_path:
            storage.delete_file(marking.marked_file_path)
            marking.marked_file_path = None
        scan.path = ""
        scan.omr_scan_id = None
        scan.failure_detail = None
    course.scanned_images_purged_at = now


async def _purge_student_records(db: AsyncSession, course: Course, now: datetime) -> None:
    snapshot = course.retention_policy_snapshot or {}
    if snapshot.get("retain_anonymized_analytics", False):
        stats = await get_course_stats(db, course.id, course.created_by)
        course.retained_analytics = stats.model_dump(mode="json")
    else:
        course.retained_analytics = None

    exam_ids = list((await db.execute(select(Exam.id).where(Exam.course_id == course.id))).scalars())
    key_ids = list((await db.execute(select(ExamAnswerKey.id).where(ExamAnswerKey.exam_id.in_(exam_ids)))).scalars()) if exam_ids else []
    grade_ids = list((await db.execute(select(ExamGrade.id).where(ExamGrade.exam_answer_key_id.in_(key_ids)))).scalars()) if key_ids else []
    review_ids = list((await db.execute(select(ReviewRequest.id).where(ReviewRequest.exam_grade_id.in_(grade_ids)))).scalars()) if grade_ids else []

    if review_ids:
        await db.execute(delete(ReviewRequestAuditEntry).where(ReviewRequestAuditEntry.review_request_id.in_(review_ids)))
    if grade_ids:
        await db.execute(delete(ReviewRequest).where(ReviewRequest.exam_grade_id.in_(grade_ids)))
    if key_ids:
        await db.execute(delete(ExamGrade).where(ExamGrade.exam_answer_key_id.in_(key_ids)))

    scans = await _course_scans(db, course.id)
    scan_ids = [scan.id for scan in scans]
    if scan_ids:
        await db.execute(delete(OMRMarking).where(OMRMarking.scan_id.in_(scan_ids)))
        await db.execute(delete(Scan).where(Scan.id.in_(scan_ids)))

    await db.execute(delete(CourseRosterEntry).where(CourseRosterEntry.course_id == course.id))
    await db.execute(delete(Enrolment).where(Enrolment.course_id == course.id, Enrolment.role == "student"))
    await db.execute(delete(Notification).where(Notification.course_id == course.id))
    course.exam_records_purged_at = now
    course.retention_processed_at = now
