"""Validate presentation seed checkpoints and generated upload files."""

import asyncio
import csv
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

import fitz
from sqlalchemy import func, select

import db.base  # noqa: F401 (registers the SQLAlchemy model graph)
from db.session import AsyncSessionLocal, engine
from models.course import Course
from models.course_roster_entry import CourseRosterEntry
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.user import User
from integrations.omr_client import delete_scans, run_marking_job, upload_scan_pdf
from presentation_config import (
    CANVAS_LINKED_STUDENTS,
    DEFAULT_PRESENTATION_QUESTION_CONFIG,
    DEFAULT_PRESENTATION_SECTIONS,
    DEFAULT_PRESENTATION_TEMPLATE_NAME,
    PRESENTATION_QUESTION_CONFIG,
    PRESENTATION_SECTIONS,
    PRESENTATION_TEMPLATE_NAME,
    presentation_email,
)
from services.answer_key_scan_extraction import (
    AnswerKeyScanUpload,
    extract_answer_key_scan,
)
from repositories.omr_templates import get_omr_template_by_id
from services.omr_field_ids import parse_question_id
from services.student_identity_decoder import decode_identity_fields

engine.echo = False

ASSET_ROOT = Path("data/presentation_flows")
EXPECTED_PDF_PAGES = {
    "01-empty-professor/default-10-a-e/answer-keys-A-B.pdf": 4,
    "01-empty-professor/default-10-a-e/student-scans-9.pdf": 18,
    "01-empty-professor/mixed-15-a-k/answer-keys-A-B.pdf": 4,
    "01-empty-professor/mixed-15-a-k/optional-answer-keys-no-version-marks.pdf": 4,
    "01-empty-professor/mixed-15-a-k/student-scans-9.pdf": 18,
    "02-seeded-professor/default-10-a-e/answer-keys-A-B.pdf": 4,
    "02-seeded-professor/default-10-a-e/student-scans-9.pdf": 18,
    "02-seeded-professor/mixed-15-a-k/answer-keys-A-B.pdf": 4,
    "02-seeded-professor/mixed-15-a-k/optional-answer-keys-no-version-marks.pdf": 4,
    "02-seeded-professor/mixed-15-a-k/student-scans-9.pdf": 18,
    "03-canvas-from-scratch/default-10-a-e/answer-keys-A-B.pdf": 4,
    "03-canvas-from-scratch/default-10-a-e/student-scans-6.pdf": 12,
    "03-canvas-from-scratch/mixed-15-a-k/answer-keys-A-B.pdf": 4,
    "03-canvas-from-scratch/mixed-15-a-k/optional-answer-keys-no-version-marks.pdf": 4,
    "03-canvas-from-scratch/mixed-15-a-k/student-scans-6.pdf": 12,
    "05-canvas-invitation/default-10-a-e/invitation-student-scan.pdf": 2,
    "05-canvas-invitation/mixed-15-a-k/invitation-student-scan.pdf": 2,
}
CANVAS_LINKED_ACCOUNTS = {
    email: student_number
    for _, _, email, student_number in CANVAS_LINKED_STUDENTS
}
REQUIRED_ACCOUNTS = {
    "empty.prof@example.com",
    "test.prof@example.com",
    "taylor.morgan@example.com",
    "jordan.lee@example.com",
    *CANVAS_LINKED_ACCOUNTS,
}


def _validate_files() -> None:
    for relative_path, expected_pages in EXPECTED_PDF_PAGES.items():
        path = ASSET_ROOT / relative_path
        if not path.is_file():
            raise RuntimeError(f"Missing {path}; run `make presentation-data`")
        with fitz.open(path) as pdf:
            if pdf.page_count != expected_pages:
                raise RuntimeError(
                    f"{path} has {pdf.page_count} pages; expected {expected_pages}"
                )

    roster_path = ASSET_ROOT / "01-empty-professor/roster-100.csv"
    with roster_path.open(newline="", encoding="utf-8") as csv_file:
        roster = list(csv.DictReader(csv_file))
    if len(roster) != 100:
        raise RuntimeError(f"{roster_path} has {len(roster)} students; expected 100")
    emails = {student["email"] for student in roster}
    student_numbers = {student["student_number"] for student in roster}
    if len(emails) != 100 or len(student_numbers) != 100:
        raise RuntimeError(f"{roster_path} contains duplicate student identities")
    first_name_distribution = Counter(
        Counter(student["first_name"] for student in roster).values()
    )
    if first_name_distribution != Counter({1: 85, 2: 3, 3: 3}):
        raise RuntimeError(
            f"{roster_path} has unexpected first-name duplicates: "
            f"{dict(first_name_distribution)}"
        )
    if len({student["last_name"] for student in roster}) != 100:
        raise RuntimeError(f"{roster_path} must contain 100 unique last names")
    malformed_emails = [
        student["email"]
        for student in roster
        if student["email"]
        != presentation_email(student["first_name"], student["last_name"])
    ]
    if malformed_emails:
        raise RuntimeError(
            f"{roster_path} contains non-name-based emails: {malformed_emails[:3]}"
        )


async def _extract(
    exam: Exam,
    professor: User,
    relative_path: str,
    question_count: int,
):
    path = ASSET_ROOT / relative_path
    async with AsyncSessionLocal() as session:
        return await extract_answer_key_scan(
            session,
            exam.id,
            professor.id,
            files=[
                AnswerKeyScanUpload(
                    filename=path.name,
                    content_type="application/pdf",
                    pdf_bytes=path.read_bytes(),
                )
            ],
            question_count=question_count,
        )


async def _decode_scan_identities(
    template: ExamTemplate,
    relative_path: str,
):
    async with AsyncSessionLocal() as session:
        omr_template = await get_omr_template_by_id(session, template.omr_template_id)
    path = ASSET_ROOT / relative_path
    scan_ids: list[str] = []
    try:
        scan_ids = await upload_scan_pdf(
            omr_template.preprocess_template_id,
            path.read_bytes(),
        )
        result = await run_marking_job(omr_template.mark_template_id, scan_ids)
        if result.errors or len(result.scans) != len(scan_ids):
            raise RuntimeError(f"OMR could not mark every identity in {path}")

        identities = []
        scans_by_id = {scan.scan_id: scan for scan in result.scans}
        for scan_id in scan_ids:
            decoded_marks = []
            for mark in scans_by_id[scan_id].marks:
                field_type, field_index = parse_question_id(mark.question_id)
                decoded_marks.append(
                    SimpleNamespace(
                        field_type=field_type,
                        field_index=field_index,
                        detected_value=",".join(mark.selected) if mark.selected else None,
                        needs_review=mark.flagged,
                    )
                )
            identities.append(decode_identity_fields(decoded_marks))
        return identities
    finally:
        await delete_scans(scan_ids)


async def _validate_database_and_omr() -> None:
    async with AsyncSessionLocal() as session:
        accounts = (
            await session.execute(select(User).where(User.email.in_(REQUIRED_ACCOUNTS)))
        ).scalars().all()
        accounts_by_email = {account.email: account for account in accounts}
        missing_accounts = REQUIRED_ACCOUNTS - set(accounts_by_email)
        if missing_accounts:
            raise RuntimeError(
                "Missing presentation accounts; run `make dev-seed`: "
                + ", ".join(sorted(missing_accounts))
            )
        mismatched_canvas_accounts = {
            email: account.student_number
            for email, expected_number in CANVAS_LINKED_ACCOUNTS.items()
            if (account := accounts_by_email[email]).student_number != expected_number
        }
        if mismatched_canvas_accounts:
            raise RuntimeError(
                "Canvas-linked OMR accounts have incorrect student numbers: "
                f"{mismatched_canvas_accounts}"
            )

        roster_path = ASSET_ROOT / "01-empty-professor/roster-100.csv"
        with roster_path.open(newline="", encoding="utf-8") as csv_file:
            roster = list(csv.DictReader(csv_file))
        existing_roster_users = (
            await session.execute(
                select(User).where(
                    User.email.in_([student["email"] for student in roster])
                )
            )
        ).scalars().all()
        expected_linked_numbers = {f"9{index:07d}" for index in range(20)}
        if {
            user.student_number for user in existing_roster_users
        } != expected_linked_numbers:
            raise RuntimeError(
                "Manual roster must contain exactly 20 existing OMR accounts"
            )

        professor = accounts_by_email["test.prof@example.com"]
        for course_name, expected_students in (
            ("COSC 499 - Capstone Project", 200),
            ("COSC 304 - Database Systems", 18),
        ):
            course_id = await session.scalar(
                select(Course.id).where(
                    Course.name == course_name,
                    Course.created_by == professor.id,
                    Course.archived_at.is_(None),
                )
            )
            roster_count = (
                await session.scalar(
                    select(func.count(CourseRosterEntry.id)).where(
                        CourseRosterEntry.course_id == course_id,
                        CourseRosterEntry.active.is_(True),
                    )
                )
                if course_id
                else 0
            )
            if roster_count != expected_students:
                raise RuntimeError(
                    f"{course_name} has {roster_count} active students; "
                    f"expected {expected_students}"
                )

        expected_options = {
            "default": (
                DEFAULT_PRESENTATION_TEMPLATE_NAME,
                DEFAULT_PRESENTATION_QUESTION_CONFIG,
                DEFAULT_PRESENTATION_SECTIONS,
                "Default 10-Question Upload Exam",
            ),
            "mixed": (
                PRESENTATION_TEMPLATE_NAME,
                PRESENTATION_QUESTION_CONFIG,
                PRESENTATION_SECTIONS,
                "Mixed 15-Question Upload Exam",
            ),
        }
        exams: dict[str, Exam] = {}
        templates: dict[str, ExamTemplate] = {}
        for option_name, (
            template_name,
            question_config,
            sections,
            exam_name,
        ) in expected_options.items():
            template = (
                await session.execute(
                    select(ExamTemplate).where(
                        ExamTemplate.name == template_name,
                        ExamTemplate.created_by == professor.id,
                    )
                )
            ).scalar_one_or_none()
            if template is None:
                raise RuntimeError(f"Seeded {option_name} presentation template is missing")
            if (
                template.question_config != question_config
                or template.sections != sections
                or template.n_versions != 2
                or template.omr_template_id is None
            ):
                raise RuntimeError(
                    f"Seeded {option_name} presentation template is out of sync"
                )

            exam = (
                await session.execute(
                    select(Exam).where(
                        Exam.name == exam_name,
                        Exam.created_by == professor.id,
                    )
                )
            ).scalar_one_or_none()
            if exam is None or exam.exam_template_id != template.id:
                raise RuntimeError(f"Seeded {exam_name} is missing or incompatible")
            key_count = await session.scalar(
                select(func.count(ExamAnswerKey.id)).where(ExamAnswerKey.exam_id == exam.id)
            )
            if key_count != 2:
                raise RuntimeError(f"{exam_name} must have answer keys A and B")
            exams[option_name] = exam
            templates[option_name] = template

        for email in ("taylor.morgan@example.com", "jordan.lee@example.com"):
            student = accounts_by_email[email]
            released_grade_count = await session.scalar(
                select(func.count(ExamGrade.id))
                .join(ExamAnswerKey, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
                .join(Exam, ExamAnswerKey.exam_id == Exam.id)
                .where(ExamGrade.student_id == student.id, Exam.released.is_(True))
            )
            if not released_grade_count:
                raise RuntimeError(f"{email} must have a released presentation result")

    marked = await _extract(
        exams["mixed"],
        professor,
        "01-empty-professor/mixed-15-a-k/answer-keys-A-B.pdf",
        len(PRESENTATION_QUESTION_CONFIG),
    )
    detected_versions = [sheet.version.detected_version for sheet in marked.sheets]
    if set(detected_versions) != {"A", "B"} or len(detected_versions) != 2:
        raise RuntimeError(
            f"Marked answer keys detected versions {detected_versions}; expected one A and one B"
        )

    unmarked = await _extract(
        exams["mixed"],
        professor,
        "01-empty-professor/mixed-15-a-k/optional-answer-keys-no-version-marks.pdf",
        len(PRESENTATION_QUESTION_CONFIG),
    )
    statuses = [sheet.version.status.value for sheet in unmarked.sheets]
    if statuses != ["missing", "missing"]:
        raise RuntimeError(
            f"Unmarked answer keys detected statuses {statuses}; expected missing, missing"
        )

    for response in (marked, unmarked):
        if len(response.sheets) != 2 or any(
            len(sheet.answers) != len(PRESENTATION_QUESTION_CONFIG)
            for sheet in response.sheets
        ):
            raise RuntimeError("Answer-key extraction returned incomplete sheets")

    default_keys = await _extract(
        exams["default"],
        professor,
        "01-empty-professor/default-10-a-e/answer-keys-A-B.pdf",
        len(DEFAULT_PRESENTATION_QUESTION_CONFIG),
    )
    if (
        len(default_keys.sheets) != 2
        or {sheet.version.detected_version for sheet in default_keys.sheets} != {"A", "B"}
        or any(
            len(sheet.answers) != len(DEFAULT_PRESENTATION_QUESTION_CONFIG)
            for sheet in default_keys.sheets
        )
    ):
        raise RuntimeError("Default 10-question answer-key extraction is incomplete")

    normal_batch = await _extract(
        exams["mixed"],
        professor,
        "01-empty-professor/mixed-15-a-k/student-scans-9.pdf",
        len(PRESENTATION_QUESTION_CONFIG),
    )
    review_sheets = [
        sheet
        for sheet in normal_batch.sheets
        if set(sheet.answers["3"].selected_choices) == {"C", "E"}
    ]
    if (
        len(normal_batch.sheets) != 9
        or len(review_sheets) != 1
        or review_sheets[0].version.status.value != "detected"
        or review_sheets[0].version.detected_version != "A"
    ):
        raise RuntimeError(
            "Normal mixed-format scan batch must contain eight clean sheets "
            "and one version-A scan with C/E selected on question 3"
        )

    canvas_identities = await _decode_scan_identities(
        templates["mixed"],
        "03-canvas-from-scratch/mixed-15-a-k/student-scans-6.pdf",
    )
    actual_canvas_identities = {
        (identity.first_name.value, identity.last_name.value, identity.student_id.value)
        for identity in canvas_identities
    }
    expected_canvas_identities = {
        (first_name.upper(), last_name.upper(), student_number)
        for first_name, last_name, _, student_number in CANVAS_LINKED_STUDENTS[:6]
    }
    if len(canvas_identities) != 6 or actual_canvas_identities != expected_canvas_identities:
        raise RuntimeError(
            "Canvas scan batch must contain six unique linked identities: "
            f"{actual_canvas_identities}"
        )

    invitation_identities = await _decode_scan_identities(
        templates["mixed"],
        "05-canvas-invitation/mixed-15-a-k/invitation-student-scan.pdf",
    )
    actual_invitation_identities = [
        (identity.first_name.value, identity.last_name.value, identity.student_id.value)
        for identity in invitation_identities
    ]
    if actual_invitation_identities != [("GRAEME", "B", "33333333")]:
        raise RuntimeError(
            "Real-address invitation scans contain unexpected identities: "
            f"{actual_invitation_identities}"
        )


async def main() -> None:
    _validate_files()
    try:
        await _validate_database_and_omr()
    finally:
        await engine.dispose()
    print("Presentation data ready: seed checkpoints, uploads, and OMR extraction verified")


if __name__ == "__main__":
    asyncio.run(main())
