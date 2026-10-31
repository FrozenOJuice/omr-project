from collections import Counter
from datetime import datetime
from typing import Any
import uuid

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import BadRequestError, ConflictError, NotFoundError
from integrations.canvas_client import normalize_canvas_id
from models.course import Course
from models.course_roster_entry import CourseRosterEntry
from models.user import User, UserRole
from repositories import course_roster_entries, courses, users
from schemas.canvas_schema import (
    CanvasRosterInvitationResponse,
    CanvasRosterResponse,
    CanvasRosterSyncResponse,
    CanvasStudentResponse,
)
from schemas.student_schema import StudentCSVRow
from services import course as course_service
from services import course_invites
from services.canvas_access import connected_course, manageable_course
from services.canvas_connection import call_canvas, utc_now


async def get_roster(
    db: AsyncSession, user_id: uuid.UUID, course_id: str
) -> CanvasRosterResponse:
    students = await call_canvas(
        db,
        user_id,
        lambda client, token: client.get_students(token, course_id),
    )
    parsed, skip_reasons = parse_students_with_skips(students)
    return CanvasRosterResponse(
        course_id=course_id,
        students=parsed,
        skip_reasons=_roster_skip_reasons(parsed, skip_reasons),
    )


async def sync_roster(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
) -> CanvasRosterSyncResponse:
    course, connection, canvas_course_id = await connected_course(
        db, user, course_id
    )
    students = await call_canvas(
        db,
        user.id,
        lambda client, token: client.get_students(token, canvas_course_id),
    )
    parsed, skip_reasons = parse_students_with_skips(students)
    synced_at = utc_now()
    try:
        result = await reconcile_roster(
            db, course.id, parsed, synced_at, skip_reasons
        )
        course.canvas_link.canvas_connection_id = connection.id
        course.canvas_link.last_synced_at = synced_at
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise


async def invite_pending_students(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
) -> CanvasRosterInvitationResponse:
    course = await _invitable_course(db, user, course_id)
    entries = await course_roster_entries.list_active_by_course(db, course_id)
    return await _send_invitations(db, user, course, entries)


async def invite_student(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
    roster_entry_id: uuid.UUID,
) -> CanvasRosterInvitationResponse:
    course = await _invitable_course(db, user, course_id)
    entry = await course_roster_entries.get_by_id(db, roster_entry_id)
    if entry is None or entry.course_id != course_id or not entry.active:
        raise NotFoundError(
            "Student roster entry not found",
            code="roster_entry_not_found",
        )
    return await _send_invitations(db, user, course, [entry])


async def _invitable_course(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
) -> Course:
    course = await manageable_course(db, user, course_id)
    if course.archived_at is not None:
        raise ConflictError(
            "Restore the course before inviting students",
            code="course_archived",
        )
    return course


async def _send_invitations(
    db: AsyncSession,
    user: User,
    course: Course,
    entries: list[CourseRosterEntry],
) -> CanvasRosterInvitationResponse:
    already_invited = sum(
        entry.invited_at is not None for entry in entries if not entry.user_id
    )
    linked = sum(entry.user_id is not None for entry in entries)

    delivery = await course_invites.deliver_invitations(db, user, course, entries)

    roster = await course_roster_entries.list_active_by_course(db, course.id)
    return CanvasRosterInvitationResponse(
        sent=delivery.sent,
        already_invited=already_invited,
        linked=linked,
        failed=delivery.failed,
        pending=sum(
            entry.user_id is None and entry.invited_at is None for entry in roster
        ),
    )


async def reconcile_roster(
    db: AsyncSession,
    course_id: uuid.UUID,
    students: list[CanvasStudentResponse],
    synced_at: datetime,
    initial_skip_reasons: Counter[str] | None = None,
) -> CanvasRosterSyncResponse:
    all_entries = await course_roster_entries.list_by_course(db, course_id)
    entries = [entry for entry in all_entries if entry.canvas_user_id is not None]
    entries_by_canvas_id = {
        entry.canvas_user_id: entry
        for entry in entries
        if entry.canvas_user_id is not None
    }
    entries_by_email = {
        course_roster_entries.normalize_email(entry.email): entry
        for entry in all_entries
    }
    entries_by_student_number = {
        entry.student_number: entry
        for entry in all_entries
        if entry.student_number is not None
    }
    seen_ids = {student.id for student in students}
    added = updated = removed = 0
    skip_reasons = Counter(initial_skip_reasons or {})

    for student in students:
        entry = entries_by_canvas_id.get(student.id)
        try:
            row = _student_row(student)
            was_managed = entry is not None
            async with db.begin_nested():
                created = False
                if entry is None:
                    entry = _matching_local_entry(
                        entries_by_email, entries_by_student_number, row
                    )
                    if entry is None:
                        entry = await course_service.create_roster_entry(
                            db,
                            course_id,
                            row,
                            source="canvas",
                            canvas_user_id=student.id,
                        )
                        created = True
                    else:
                        entry.canvas_user_id = student.id
                        entry.source = "canvas"
                changed = not created and await _update_entry(db, entry, row)
            if not was_managed:
                entries.append(entry)
                entries_by_canvas_id[student.id] = entry
                added += int(created)
                updated += int(not created)
            elif changed:
                updated += 1
            _index_entry(entries_by_email, entries_by_student_number, entry)
        except RosterStudentError as exc:
            skip_reasons[exc.reason] += 1
        except (BadRequestError, IntegrityError):
            skip_reasons["identity_conflict"] += 1

    for entry in entries:
        if entry.active and entry.canvas_user_id not in seen_ids:
            entry.active = False
            if entry.user_id:
                enrolment = await courses.get_student_enrolment(
                    db, course_id, entry.user_id
                )
                if enrolment:
                    await db.delete(enrolment)
            removed += 1

    await db.flush()
    return CanvasRosterSyncResponse(
        added=added,
        updated=updated,
        removed=removed,
        skipped=sum(skip_reasons.values()),
        skip_reasons=dict(skip_reasons),
        active=await course_roster_entries.count_active_by_course(db, course_id),
        last_synced_at=synced_at,
    )


def _matching_local_entry(
    entries_by_email: dict[str, CourseRosterEntry],
    entries_by_student_number: dict[str, CourseRosterEntry],
    row: StudentCSVRow,
) -> CourseRosterEntry | None:
    by_email = entries_by_email.get(
        course_roster_entries.normalize_email(str(row.email))
    )
    by_number = entries_by_student_number.get(row.student_number)
    if by_email is None and by_number is None:
        return None
    if by_email is not by_number or by_email is None:
        raise BadRequestError(
            "Canvas roster identity conflicts with an existing student"
        )
    if by_email.canvas_user_id is not None:
        raise BadRequestError(
            "Canvas roster identity conflicts with an existing student"
        )
    return by_email


def _index_entry(
    entries_by_email: dict[str, CourseRosterEntry],
    entries_by_student_number: dict[str, CourseRosterEntry],
    entry: CourseRosterEntry,
) -> None:
    for index in (entries_by_email, entries_by_student_number):
        for key, indexed_entry in list(index.items()):
            if indexed_entry is entry:
                del index[key]
    entries_by_email[course_roster_entries.normalize_email(entry.email)] = entry
    if entry.student_number:
        entries_by_student_number[entry.student_number] = entry


async def _update_entry(
    db: AsyncSession,
    entry: CourseRosterEntry,
    row: StudentCSVRow,
) -> bool:
    before = (
        entry.user_id,
        entry.email,
        entry.first_name,
        entry.last_name,
        entry.student_number,
        entry.active,
    )
    email = str(row.email)
    duplicate_email = await course_roster_entries.get_by_course_and_email(
        db, entry.course_id, email
    )
    duplicate_number = await course_roster_entries.get_by_course_and_student_number(
        db, entry.course_id, row.student_number
    )
    if duplicate_email not in (None, entry) or duplicate_number not in (None, entry):
        raise BadRequestError("Canvas roster identity conflicts with an existing student")

    account = (
        await users.get_by_id(db, entry.user_id)
        if entry.user_id
        else await users.get_by_email(db, email)
    )
    if account:
        if account.role_enum != UserRole.STUDENT:
            raise BadRequestError("Existing user is not a student")
        if account.student_number and account.student_number != row.student_number:
            raise BadRequestError("Student number does not match existing account")
        if not account.student_number:
            account.student_number = row.student_number
        entry.user_id = account.id
        await course_service.add_student_enrolment(db, entry.course_id, account)

    if entry.email != email and entry.user_id is None:
        entry.invited_at = None
    entry.email = email
    entry.first_name = row.first_name
    entry.last_name = row.last_name
    entry.student_number = row.student_number
    entry.active = True
    return before != (
        entry.user_id,
        entry.email,
        entry.first_name,
        entry.last_name,
        entry.student_number,
        entry.active,
    )


def parse_students_with_skips(
    items: Any,
) -> tuple[list[CanvasStudentResponse], Counter[str]]:
    students: dict[str, CanvasStudentResponse] = {}
    skip_reasons: Counter[str] = Counter()
    for item in items:
        user = item.get("user", item) if isinstance(item, dict) else None
        if not isinstance(user, dict):
            skip_reasons["invalid_canvas_record"] += 1
            continue
        canvas_user_id = normalize_canvas_id(user.get("id"))
        if canvas_user_id is None:
            skip_reasons["missing_canvas_user_id"] += 1
            continue
        if canvas_user_id in students:
            skip_reasons["duplicate_canvas_user_id"] += 1
        students[canvas_user_id] = CanvasStudentResponse(
            id=canvas_user_id,
            name=str(user.get("name") or canvas_user_id),
            login_id=_optional_string(user.get("login_id")),
            sis_user_id=_optional_string(user.get("sis_user_id")),
            email=_optional_string(user.get("email")),
            sortable_name=_optional_string(user.get("sortable_name")),
        )
    return (
        sorted(students.values(), key=lambda student: student.name.casefold()),
        skip_reasons,
    )


def _student_row(student: CanvasStudentResponse) -> StudentCSVRow:
    email = student.email or student.login_id
    if not email:
        raise RosterStudentError("missing_email")
    if not student.sis_user_id:
        raise RosterStudentError("missing_student_number")
    if student.sortable_name and "," in student.sortable_name:
        last_name, first_name = (
            part.strip() for part in student.sortable_name.split(",", 1)
        )
    else:
        names = student.name.rsplit(maxsplit=1)
        if len(names) != 2:
            raise RosterStudentError("invalid_name")
        first_name, last_name = names
    try:
        return StudentCSVRow(
            email=email,
            first_name=first_name,
            last_name=last_name,
            student_number=student.sis_user_id,
        )
    except ValidationError as exc:
        fields = {str(error["loc"][0]) for error in exc.errors() if error["loc"]}
        if "email" in fields:
            raise RosterStudentError("invalid_email") from exc
        if "student_number" in fields:
            raise RosterStudentError("invalid_student_number") from exc
        raise RosterStudentError("invalid_student_data") from exc


def _roster_skip_reasons(
    students: list[CanvasStudentResponse],
    initial: Counter[str],
) -> dict[str, int]:
    reasons = Counter(initial)
    for student in students:
        try:
            _student_row(student)
        except RosterStudentError as exc:
            reasons[exc.reason] += 1
    return dict(reasons)


class RosterStudentError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
