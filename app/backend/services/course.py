import uuid
import calendar
from datetime import datetime, timezone
from uuid import UUID

from errors.exceptions import BadRequestError
from errors.exceptions import ConflictError
from errors.exceptions import ForbiddenError
from errors.exceptions import NotFoundError
from core.datetime_utils import is_expired
from repositories import course_roster_entries
from repositories import courses
from repositories import retention_policies
from repositories import users
from services import academic_terms as academic_term_service
from services import course_invites

from fastapi import HTTPException, status, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.course import Course, new_invite_link_expiry
from models.course_roster_entry import CourseRosterEntry
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.review_request import ReviewRequest
from models.user import User, UserRole
from schemas.course_schema import AddStudentRequest, CourseResponse
from schemas.student_schema import StudentCSVRow
import csv
import io


async def get_course(
    db: AsyncSession, course_id: UUID, requesting_user: User
) -> CourseResponse:
    return _course_response(
        await _get_viewable_course(db, course_id, requesting_user),
        requesting_user,
    )


async def create_new_course(
    db: AsyncSession,
    name: str,
    academic_term_id: UUID,
    academic_year_start: int,
    created_by: User,
):
    try:
        academic_term = await academic_term_service.resolve_for_course(
            db,
            created_by,
            academic_term_id=academic_term_id,
        )
        course = await courses.create(
            db,
            name,
            academic_term,
            created_by.id,
            academic_year_start,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return course


async def delete_existing_course(db: AsyncSession, course_id: UUID, requesting_user: User):
    course = await _get_manageable_course(db, course_id, requesting_user)
    if await courses.has_dependent_records(db, course_id):
        raise ConflictError(
            "Courses with exams or enrolment history must be archived instead.",
            code="course_has_history",
        )

    try:
        await courses.delete(db, course)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return True


async def archive_existing_course(
    db: AsyncSession,
    course_id: UUID,
    requesting_user: User,
    *,
    confirmed: bool = False,
    override_active_course: bool = False,
) -> CourseResponse:
    course = await _get_manageable_course(db, course_id, requesting_user)

    if course.archived_at is not None:
        return _course_response(course, requesting_user)

    policy = await retention_policies.get_by_owner_id(db, course.created_by)
    if policy is None:
        raise ConflictError(
            "Set a retention policy before archiving this course.",
            code="retention_policy_required",
        )
    if not confirmed:
        raise ConflictError(
            "Confirm the archive operation before continuing.",
            code="archive_confirmation_required",
        )

    archived_at = datetime.now(timezone.utc)
    blockers, latest_exam_end = await _archive_blockers(db, course.id, archived_at)
    if blockers and not override_active_course:
        raise ConflictError(
            "This course still has active academic work. Resolve it or explicitly override before archiving.",
            code="course_still_active",
            details={"blockers": blockers},
        )
    retention_anchor = max(archived_at, latest_exam_end) if latest_exam_end else archived_at
    policy_snapshot = {
        "scanned_image_retention_months": policy.scanned_image_retention_months,
        "exam_record_retention_months": policy.exam_record_retention_months,
        "retain_anonymized_analytics": policy.retain_anonymized_analytics,
        "source": policy.source,
        "retention_anchor_at": retention_anchor.isoformat(),
        "active_course_override_used": bool(blockers and override_active_course),
    }

    try:
        archived = await courses.archive(
            db,
            course,
            archived_at=archived_at,
            archived_by_user_id=requesting_user.id,
            retention_policy_id=policy.id,
            retention_policy_snapshot=policy_snapshot,
            scanned_images_retention_until=_add_months(
                retention_anchor,
                policy.scanned_image_retention_months,
            ),
            exam_records_retention_until=_add_months(
                retention_anchor,
                policy.exam_record_retention_months,
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _course_response(archived, requesting_user)


async def restore_existing_course(
    db: AsyncSession,
    course_id: UUID,
    requesting_user: User,
) -> CourseResponse:
    course = await _get_manageable_course(db, course_id, requesting_user)

    if course.archived_at is None:
        return _course_response(course, requesting_user)

    if course.scanned_images_purged_at or course.exam_records_purged_at or course.retention_processed_at:
        raise ConflictError(
            "This course cannot be restored because retention processing has already removed records.",
            code="retention_already_processed",
        )

    try:
        restored = await courses.restore(db, course)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _course_response(restored, requesting_user)


async def update_existing_course(
    db: AsyncSession,
    course_id: UUID,
    requesting_user: User,
    name: str | None = None,
    academic_term_id: UUID | None = None,
    academic_year_start: int | None = None,
) -> CourseResponse:
    course = await _get_mutable_course(db, course_id, requesting_user)

    try:
        academic_term = None
        if academic_term_id is not None:
            academic_term = await academic_term_service.resolve_for_course(
                db,
                requesting_user,
                academic_term_id=academic_term_id,
            )
        updated = await courses.update(
            db,
            course,
            name,
            academic_term,
            academic_year_start,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _course_response(updated, requesting_user)


async def list_courses_for_user(
    db: AsyncSession,
    user: User,
    *,
    include_archived: bool = False,
):
    # Archived offerings are historical staff records and are never exposed
    # through the student course list.
    include_archived = include_archived and user.role_enum != UserRole.STUDENT
    if user.role_enum == UserRole.ADMIN:
        rows = await courses.list_all(db, include_archived=include_archived)
    else:
        rows = await courses.list_by_user(db, user.id, include_archived=include_archived)
    return [
        {
            'id': c.id,
            'name': c.name,
            'academic_term_id': c.academic_term_id,
            'academic_term': c.academic_term,
            'academic_year_start': c.academic_year_start,
            'archived_at': c.archived_at,
            'archived_by_user_id': c.archived_by_user_id,
            'retention_policy_id': c.retention_policy_id,
            'scanned_images_retention_until': c.scanned_images_retention_until,
            'exam_records_retention_until': c.exam_records_retention_until,
            'scanned_images_purged_at': c.scanned_images_purged_at,
            'exam_records_purged_at': c.exam_records_purged_at,
            'retention_processed_at': c.retention_processed_at,
            'created_by': c.created_by,
            'created_at': c.created_at,
            'updated_at': c.updated_at,
            'invite_link': c.invite_link,
            'invite_link_expires_at': c.invite_link_expires_at,
            'student_count': count,
            'source': c.source,
            'canvas_link': c.canvas_link,
            'can_manage_canvas': bool(
                c.canvas_link and c.canvas_link.owner_user_id == user.id
            ),
        }
        for c, count in rows
    ]


async def list_enrolled_students(
    db: AsyncSession,
    course_id: UUID,
    requesting_user: User | None = None,
):
    if requesting_user is not None:
        await _get_manageable_course(db, course_id, requesting_user)

    result = await db.execute(
        select(User)
        .join(Enrolment, Enrolment.user_id == User.id)
        .where(Enrolment.course_id == course_id, Enrolment.role == "student")
    )
    return result.scalars().all()


async def list_course_roster(
    db: AsyncSession,
    course_id: UUID,
    requesting_user: User,
):
    await _get_staff_viewable_course(db, course_id, requesting_user)
    return await course_roster_entries.list_by_course(db, course_id)


async def add_student_to_course(
    db: AsyncSession,
    course_id: UUID,
    student_data: AddStudentRequest,
    requesting_user: User,
) -> CourseRosterEntry:
    course = await _get_mutable_course(db, course_id, requesting_user)

    try:
        entry = await create_roster_entry(db, course_id, student_data, source="manual")
        await db.commit()
        await db.refresh(entry)

        # Match the CSV enrolment flow: once the roster entry is durable,
        # notify a student who does not have an account yet. Existing accounts
        # are already linked and enrolled, so pending_invitations skips them.
        await course_invites.deliver_invitations(
            db,
            requesting_user,
            course,
            [entry],
        )
        return entry
    except IntegrityError as exc:
        await db.rollback()

        raise ConflictError(
            "Student is already on the course roster.",
            code="student_already_enrolled",
        ) from exc

    except Exception:
        await db.rollback()
        raise


async def unenroll_student(
    db: AsyncSession,
    course_id: UUID,
    roster_entry_id: UUID,
    requesting_user: User,
):
    await _get_mutable_course(db, course_id, requesting_user)

    entry = await course_roster_entries.get_by_id(db, roster_entry_id)
    if not entry or entry.course_id != course_id:
        raise NotFoundError("Roster entry not found", code="student_enrolment_not_found")
    if entry.source == "canvas":
        raise ConflictError(
            "Canvas roster students are managed by roster sync",
            code="canvas_roster_managed",
        )

    try:
        if entry.user_id:
            enrolment = await courses.get_student_enrolment(db, course_id, entry.user_id)
            if enrolment:
                await db.delete(enrolment)

        await course_roster_entries.delete(db, entry)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def promote_student_to_professor(
    db: AsyncSession,
    course_id: UUID,
    roster_entry_id: UUID,
    requesting_user: User,
):
    await _get_mutable_course(db, course_id, requesting_user)

    entry = await course_roster_entries.get_by_id(db, roster_entry_id)
    if not entry or entry.course_id != course_id:
        raise NotFoundError("Roster entry not found", code="student_enrolment_not_found")
    if entry.source == "canvas":
        raise ConflictError(
            "Canvas roster students are managed by roster sync",
            code="canvas_roster_managed",
        )
    if not entry.user_id:
        raise BadRequestError(
            "This student hasn't linked an account yet, so they can't be promoted.",
            code="student_not_linked",
        )

    user = await users.get_by_id(db, entry.user_id, for_update=True)
    if not user:
        raise NotFoundError("Student not found", code="user_not_found")
    if user.role_enum != UserRole.STUDENT:
        raise BadRequestError(
            "Only students can be promoted to professor.",
            code="already_staff",
        )

    try:
        enrolment = await courses.get_student_enrolment(db, course_id, user.id)
        if enrolment:
            await db.delete(enrolment)
        await course_roster_entries.delete(db, entry)

        await users.update_role(db, user, UserRole.PROFESSOR)
        db.add(Enrolment(course_id=course_id, user_id=user.id, role="professor"))

        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def _get_course_or_404(db: AsyncSession, course_id: UUID) -> Course:
    course = await courses.get_by_id(db, course_id)

    if not course:
        raise NotFoundError("Course not found", code="course_not_found")

    return course


async def _get_mutable_course(db: AsyncSession, course_id: UUID, user: User) -> Course:
    course = await _get_manageable_course(db, course_id, user)
    if course.archived_at is not None:
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )
    return course


async def _archive_blockers(
    db: AsyncSession,
    course_id: UUID,
    now: datetime,
) -> tuple[list[dict], datetime | None]:
    exam_rows = list((await db.execute(select(Exam).where(Exam.course_id == course_id))).scalars())
    blockers = [
        {"type": "exam_not_finished", "exam_id": str(exam.id), "exam_name": exam.name, "ends_at": exam.end_time.isoformat()}
        for exam in exam_rows
        if exam.end_time is not None and exam.end_time > now
    ]
    latest_exam_end = max(
        (exam.end_time for exam in exam_rows if exam.end_time is not None),
        default=None,
    )
    pending = list((await db.execute(
        select(ReviewRequest.id)
        .join(ExamGrade, ExamGrade.id == ReviewRequest.exam_grade_id)
        .join(ExamAnswerKey, ExamAnswerKey.id == ExamGrade.exam_answer_key_id)
        .join(Exam, Exam.id == ExamAnswerKey.exam_id)
        .where(Exam.course_id == course_id, ReviewRequest.status == "pending")
    )).scalars())
    if pending:
        blockers.append({"type": "pending_review_requests", "count": len(pending)})
    return blockers, latest_exam_end


def _add_months(value: datetime, months: int) -> datetime:
    """Adds calendar months without drifting archive deadlines by 30-day blocks."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


async def _get_viewable_course(db: AsyncSession, course_id: UUID, user: User) -> Course:
    course = await _get_course_or_404(db, course_id)

    if user.role_enum == UserRole.STUDENT and course.archived_at is not None:
        raise NotFoundError("Course not found", code="course_not_found")

    if user.role_enum == UserRole.ADMIN or course.created_by == user.id:
        return course

    if await courses.get_student_enrolment(db, course_id, user.id):
        return course

    if await courses.get_staff_enrolment(db, course_id, user.id):
        return course

    raise ForbiddenError("Not authorized", code="forbidden")


async def _get_manageable_course(db: AsyncSession, course_id: UUID, user: User) -> Course:
    course = await _get_course_or_404(db, course_id)

    if user.role_enum != UserRole.ADMIN and course.created_by != user.id:
        raise ForbiddenError("Not authorized", code="forbidden")

    return course


async def _get_staff_viewable_course(db: AsyncSession, course_id: UUID, user: User) -> Course:
    """Like _get_manageable_course, but also lets a promoted co-professor read
    the roster -- they need real names to make sense of results and regrade
    requests, even though they can't manage the course. Plain students still
    can't see this (it's the whole class list, not just their own record).
    """
    course = await _get_course_or_404(db, course_id)

    if user.role_enum == UserRole.ADMIN or course.created_by == user.id:
        return course

    if await courses.get_staff_enrolment(db, course_id, user.id):
        return course

    raise ForbiddenError("Not authorized", code="forbidden")


def _course_response(course: Course, user: User) -> CourseResponse:
    return CourseResponse.model_validate(course).model_copy(
        update={
            "can_manage_canvas": bool(
                course.canvas_link and course.canvas_link.owner_user_id == user.id
            )
        }
    )


async def create_roster_entry(
    db: AsyncSession,
    course_id: UUID,
    student_data: AddStudentRequest | StudentCSVRow,
    source: str,
    canvas_user_id: str | None = None,
) -> CourseRosterEntry:
    existing_entry = await course_roster_entries.get_by_course_and_email(
        db,
        course_id,
        str(student_data.email),
    )
    if existing_entry:
        raise BadRequestError(
            "Student is already on the course roster.",
            code="student_already_enrolled",
        )

    existing_student_number = await course_roster_entries.get_by_course_and_student_number(
        db,
        course_id,
        student_data.student_number,
    )
    if existing_student_number:
        raise BadRequestError(
            "Student number is already on the course roster.",
            code="student_already_enrolled",
        )

    student = await users.get_by_email(db, str(student_data.email))
    user_id = None

    if student:
        if student.role_enum != UserRole.STUDENT:
            raise BadRequestError(
                "Existing user is not a student",
                code="user_not_student",
            )
        if student.student_number and student.student_number != student_data.student_number:
            raise BadRequestError(
                "Student number does not match existing student account.",
                code="student_number_mismatch",
            )
        if not student.student_number:
            student.student_number = student_data.student_number
        user_id = student.id

    entry = await course_roster_entries.create(
        db,
        course_id=course_id,
        user_id=user_id,
        email=str(student_data.email),
        first_name=student_data.first_name,
        last_name=student_data.last_name,
        student_number=student_data.student_number,
        source=source,
        canvas_user_id=canvas_user_id,
    )

    if student:
        await add_student_enrolment(db, course_id, student)

    return entry


async def add_student_enrolment(
    db: AsyncSession,
    course_id: UUID,
    student: User,
) -> bool:
    if await courses.get_student_enrolment(db, course_id, student.id):
        return False

    db.add(Enrolment(course_id=course_id, user_id=student.id, role="student"))
    return True


async def claim_roster_entries_for_user(db: AsyncSession, user: User) -> int:
    if user.role_enum != UserRole.STUDENT:
        return 0

    entries = await course_roster_entries.list_unclaimed_by_email(db, user.email)
    claimed = 0
    for entry in entries:
        if entry.student_number and entry.student_number != user.student_number:
            continue
        entry.user_id = user.id
        await add_student_enrolment(db, entry.course_id, user)
        claimed += 1

    if claimed:
        await db.flush()

    return claimed


def _csv_row_message(exc: Exception) -> str:
    message = getattr(exc, "message", None)
    if message is not None:
        return message

    if isinstance(exc, ValidationError):
        field_messages = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        return "; ".join(field_messages)

    if isinstance(exc, IntegrityError):
        if users.is_email_conflict(exc):
            return "Email is already in use by another account."
        if users.is_student_number_conflict(exc):
            return "Student number is already in use by another account."
        return "This row conflicts with existing data."

    return "Unable to process this row due to an unexpected error."


def _csv_row_error(row_idx: int, exc: Exception) -> str:
    return f"Row {row_idx}: {_csv_row_message(exc)}"


def _csv_already_enrolled_warning(row_idx: int, row: dict) -> str:
    first = (row.get("first_name") or "").strip()
    last = (row.get("last_name") or "").strip()
    email = (row.get("email") or "").strip()
    name = " ".join(part for part in (first, last) if part)
    if name and email:
        who = f"{name} ({email})"
    else:
        who = name or email or "This student"
    return f"Row {row_idx}: {who} is already a part of the class."


class CourseInviteService:
    
    @staticmethod
    async def enroll_current_student_via_link(db: AsyncSession, invite_link: str, student: User) -> Course:
        if student.role_enum != UserRole.STUDENT:
            raise ForbiddenError("Only students can join courses by invite link", code="student_required")

        course_result = await db.execute(select(Course).filter(Course.invite_link == invite_link))
        course = course_result.scalar_one_or_none()
        if not course:
            raise NotFoundError("Invalid or expired invite link", code="invalid_invite_link")

        # A student who is already enrolled re-opening their link is a harmless
        # no-op, so return success even if the link has since expired or the
        # course was archived — they already have access.
        already_enrolled = await courses.get_student_enrolment(db, course.id, student.id)
        if already_enrolled:
            return course

        if course.archived_at is not None or is_expired(course.invite_link_expires_at):
            raise NotFoundError("Invalid or expired invite link", code="invalid_invite_link")

        entry = await course_roster_entries.get_by_course_and_email(
            db,
            course.id,
            student.email,
        )
        if entry:
            if entry.student_number and entry.student_number != student.student_number:
                raise BadRequestError(
                    "Student number does not match the roster entry.",
                    code="student_number_mismatch",
                )
            entry.user_id = student.id
        else:
            await course_roster_entries.create(
                db,
                course_id=course.id,
                user_id=student.id,
                email=student.email,
                first_name=student.first_name,
                last_name=student.last_name,
                student_number=student.student_number,
                source="invite",
            )

        await add_student_enrolment(db, course.id, student)
        await db.commit()
        
        return course

    @staticmethod
    async def regenerate_invite_link(db: AsyncSession, course_id: UUID, current_user: User) -> Course:
        course = await _get_mutable_course(db, course_id, current_user)

        course.invite_link = uuid.uuid4().hex[:8]
        course.invite_link_expires_at = new_invite_link_expiry()
        await course_roster_entries.reset_pending_invitations(db, course_id)
        await db.commit()
        await db.refresh(course)
        return course

    @staticmethod
    async def resend_pending_invites(
        db: AsyncSession, course_id: UUID, current_user: User
    ) -> dict:
        """Retry invitations for students who haven't been successfully invited.

        The manual retry path for regular (non-Canvas) courses: re-uploading a
        CSV skips students already on the roster, so this is how a professor
        recovers invites that failed to send. Only entries with no account and
        no recorded invite are re-sent, so nobody is emailed twice.
        """
        course = await _get_mutable_course(db, course_id, current_user)
        entries = await course_roster_entries.list_active_by_course(db, course_id)
        delivery = await course_invites.deliver_invitations(
            db, current_user, course, entries
        )
        return {"invited": delivery.sent, "invite_failed": delivery.failed}

    @staticmethod
    async def bulk_enroll_via_csv(db: AsyncSession, course_id: UUID, file: UploadFile, current_user: User) -> dict:
        course = await _get_mutable_course(db, course_id, current_user)

        contents = await file.read()
        try:
            decoded = contents.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be UTF-8 encoded. Re-export the CSV as UTF-8 and try again.",
            ) from exc
        buffer = io.StringIO(decoded)
        reader = csv.DictReader(buffer)

        # Basic header sanity check
        required_fields = {"email", "first_name", "last_name", "student_number"}
        if not required_fields.issubset(set(reader.fieldnames or [])):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV missing required headers: 'email', 'first_name', 'last_name', 'student_number'"
            )

        results = {
            "enrolled": 0,
            "linked": 0,
            "pending": 0,
            "skipped": 0,
            "invited": 0,
            "invite_failed": 0,
            "warnings": [],
            "errors": [],
        }
        created_entries: list[CourseRosterEntry] = []

        for row_idx, row in enumerate(reader, start=1):
            # Spreadsheet exports (Excel, Google Sheets) commonly pad trailing
            # rows with empty, comma-only lines. csv.DictReader only skips
            # truly blank lines on its own, so a row where every field is
            # blank must be skipped explicitly rather than reported as a
            # validation error for a row the user never actually entered.
            # Rows with more columns than the header collect the overflow
            # into a list under DictReader's restkey (None), so non-string
            # values must be excluded from the blank check.
            if all(
                not (value or "").strip()
                for value in row.values()
                if isinstance(value, str)
            ):
                continue

            try:
                # Create an atomic savepoint for each row.
                async with db.begin_nested():
                    student_data = StudentCSVRow(
                        email=row.get("email", "").strip(),
                        first_name=row.get("first_name", "").strip(),
                        last_name=row.get("last_name", "").strip(),
                        student_number=row.get("student_number", "").strip(),
                    )

                    entry = await create_roster_entry(
                        db,
                        course_id,
                        student_data,
                        source="csv",
                    )

                    results["enrolled"] += 1
                    if entry.user_id:
                        results["linked"] += 1
                    else:
                        results["pending"] += 1

                # Recorded only once the savepoint has been released, so a row
                # that failed on flush is never handed to the mailer.
                created_entries.append(entry)

            except Exception as e:
                if getattr(e, "code", None) == "student_already_enrolled":
                    # The row names someone already on this course's roster.
                    # Skip them and tell the uploader by name, but keep going —
                    # each row runs in its own savepoint, so a duplicate never
                    # stops the rest of the file from being processed.
                    results["skipped"] += 1
                    results["warnings"].append(
                        _csv_already_enrolled_warning(row_idx, row)
                    )
                    continue

                results["errors"].append(_csv_row_error(row_idx, e))

        await db.commit()

        # Invitations go out only once the roster rows are durable, so a mail
        # failure can't roll back an enrolment. Students who matched an
        # existing account are already enrolled and get no join link.
        delivery = await course_invites.deliver_invitations(
            db,
            current_user,
            course,
            created_entries,
        )
        results["invited"] = delivery.sent
        results["invite_failed"] = delivery.failed

        return results
