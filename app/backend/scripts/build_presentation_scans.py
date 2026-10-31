"""Generate every upload file used by the presentation flows.

Run after ``make dev-seed``:

    make presentation-data

The generated tree is intentionally Git-ignored. It can be rebuilt from the
seeded identities and shared template configurations at any time.
"""

import argparse
import asyncio
import csv
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

import fitz  # noqa: E402
from sqlalchemy import or_, select  # noqa: E402

import db.base  # noqa: E402, F401 (registers the SQLAlchemy model graph)
from db.session import AsyncSessionLocal, engine  # noqa: E402
from models.exam_template import ExamTemplate  # noqa: E402
from models.user import User  # noqa: E402
from presentation_config import (  # noqa: E402
    CANVAS_LINKED_STUDENTS,
    DEFAULT_PRESENTATION_QUESTION_CONFIG,
    DEFAULT_PRESENTATION_SECTIONS,
    DEFAULT_PRESENTATION_TEMPLATE_NAME,
    PRESENTATION_ADDITIONAL_FIRST_NAMES,
    PRESENTATION_ADDITIONAL_LAST_NAMES,
    PRESENTATION_QUESTION_CONFIG,
    PRESENTATION_SECTIONS,
    PRESENTATION_TEMPLATE_NAME,
    presentation_email,
    unique_names,
)
from services.exam_generator import render_filled_scan_pdf  # noqa: E402

engine.echo = False

FLOW_DIRS = {
    "empty": "01-empty-professor",
    "seeded": "02-seeded-professor",
    "canvas": "03-canvas-from-scratch",
    "student": "04-student-results-regrade",
    "invitation": "05-canvas-invitation",
}
TEMPLATE_OPTIONS = {
    "default-10-a-e": (
        DEFAULT_PRESENTATION_TEMPLATE_NAME,
        DEFAULT_PRESENTATION_QUESTION_CONFIG,
        DEFAULT_PRESENTATION_SECTIONS,
    ),
    "mixed-15-a-k": (
        PRESENTATION_TEMPLATE_NAME,
        PRESENTATION_QUESTION_CONFIG,
        PRESENTATION_SECTIONS,
    ),
}

MANUAL_HEADER = (
    "Midterm Exam",
    "COSC 250 - Computer Architecture · Aug 07, 2026 · 10:00 AM",
)
SEEDED_KEY_HEADER = (
    "Live Answer Key Demo",
    "COSC 499 - Capstone Project · Aug 07, 2026 · 10:00 AM",
)
SEEDED_SCAN_HEADERS = {
    "default-10-a-e": (
        "Default 10-Question Upload Exam",
        "COSC 499 - Capstone Project · Aug 07, 2026 · 10:00 AM",
    ),
    "mixed-15-a-k": (
        "Mixed 15-Question Upload Exam",
        "COSC 499 - Capstone Project · Aug 07, 2026 · 10:00 AM",
    ),
}
CANVAS_HEADER = (
    "Midterm Exam",
    "COSC 111 - Introduction to Programming · Aug 07, 2026 · 10:00 AM",
)

LINKED_ROSTER_STUDENT_NUMBERS = tuple(
    f"9{index:07d}" for index in range(20)
)
CLEAN_SCAN_IDENTITIES = tuple(
    (f"9{index:07d}", "A" if index % 2 == 0 else "B")
    for index in range(8)
)
REVIEW_SCAN_STUDENT_NUMBER = "90000008"
CANVAS_SCAN_IDENTITIES = tuple(
    (email, "A" if index % 2 == 0 else "B")
    for index, (_, _, email, _) in enumerate(CANVAS_LINKED_STUDENTS[:5])
)
CANVAS_REVIEW_STUDENT_EMAIL = CANVAS_LINKED_STUDENTS[5][2]
INVITATION_STUDENT = {
    "email": "invitation.student@example.com",
    "first_name": "Graeme",
    "last_name": "B",
    "student_number": "33333333",
}

PENDING_FIRST_NAMES = (
    "Camila", "Daniel", "Luna", "Matthew", "Sofia", "Jackson", "Aria",
    "Sebastian", "Scarlett", "Jack", "Chloe", "Owen", "Layla", "Samuel",
    "Mila", "Leo", "Nora", "Julian", "Hazel", "David",
    *PRESENTATION_ADDITIONAL_FIRST_NAMES,
)
PENDING_LAST_NAMES = (
    "Garcia", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Perez", "Thompson", "White", "Harris", "Sanchez", "Ramirez",
    "Robinson", "Patel", "Chen", "Campbell", "Mitchell", "Roberts",
    "Carter", "Phillips",
    *PRESENTATION_ADDITIONAL_LAST_NAMES,
)
NORMAL_SCORES = {
    10: (10, 9, 8, 7, 6, 5, 4, 3),
    15: (15, 14, 13, 12, 11, 10, 8, 6),
}
CANVAS_SCORES = {
    10: (10, 8, 7, 6, 9),
    15: (15, 13, 11, 9, 12),
}


@dataclass(frozen=True)
class StudentIdentity:
    email: str
    first_name: str
    last_name: str
    student_number: str


def _template(option: tuple[str, dict, list]) -> ExamTemplate:
    name, question_config, sections = option
    return ExamTemplate(
        name=name,
        question_config=question_config,
        sections=sections,
        total_questions=len(question_config),
        n_versions=2,
        version=1,
    )


def _identity(user: User | dict[str, str]) -> StudentIdentity:
    def value(field: str) -> str:
        return user[field] if isinstance(user, dict) else getattr(user, field)

    return StudentIdentity(
        email=value("email"),
        first_name=value("first_name"),
        last_name=value("last_name"),
        student_number=value("student_number"),
    )


def _answers(
    template: ExamTemplate,
    version: str,
    correct_count: int,
) -> dict[str, list[str]]:
    version_offset = ord(version) - ord("A")
    answers = {}
    for position, (question_id, config) in enumerate(
        sorted(template.question_config.items(), key=lambda item: int(item[0]))
    ):
        choices = config["choices"]
        correct_index = (int(question_id) - 1 + version_offset) % len(choices)
        selected_index = (
            correct_index
            if position < correct_count
            else (correct_index + 1) % len(choices)
        )
        answers[question_id] = [choices[selected_index]]
    return answers


def _render(
    template: ExamTemplate,
    student: StudentIdentity,
    *,
    version: str,
    correct_count: int,
    header: tuple[str, str],
    answers: dict[str, list[str]] | None = None,
) -> bytes:
    return render_filled_scan_pdf(
        template,
        version=version,
        student_id=student.student_number,
        first_name=student.first_name,
        last_name=student.last_name,
        answers=answers or _answers(template, version or "A", correct_count),
        darkness=0.95,
        identity_darkness=1.0,
        header=header,
    )


def _write_batch(path: Path, sheets: list[bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = fitz.open()
    try:
        for sheet in sheets:
            source = fitz.open(stream=sheet, filetype="pdf")
            try:
                output.insert_pdf(source)
            finally:
                source.close()
        output.save(path, garbage=4, deflate=True)
    finally:
        output.close()


def _answer_keys(
    template: ExamTemplate,
    identity: StudentIdentity,
    header: tuple[str, str],
    *,
    mark_versions: bool,
) -> list[bytes]:
    return [
        _render(
            template,
            identity,
            version=version if mark_versions else "",
            correct_count=template.total_questions,
            header=header,
            answers=_answers(template, version, template.total_questions),
        )
        for version in ("A", "B")
    ]


def _review_scan(
    template: ExamTemplate,
    student: StudentIdentity,
    header: tuple[str, str],
) -> bytes:
    answers = _answers(template, "A", max(1, template.total_questions - 4))
    choices = template.question_config["3"]["choices"]
    extra_choice = "E" if "E" in choices and "E" not in answers["3"] else next(
        choice for choice in reversed(choices) if choice not in answers["3"]
    )
    answers["3"].append(extra_choice)
    return _render(
        template,
        student,
        version="A",
        correct_count=template.total_questions - 4,
        header=header,
        answers=answers,
    )


def _student_batch(
    template: ExamTemplate,
    students: list[tuple[StudentIdentity, str]],
    review_student: StudentIdentity,
    header: tuple[str, str],
    scores: tuple[int, ...],
) -> list[bytes]:
    sheets = [
        _render(
            template,
            student,
            version=version,
            correct_count=score,
            header=header,
        )
        for (student, version), score in zip(students, scores, strict=True)
    ]
    sheets.append(_review_scan(template, review_student, header))
    return sheets


def _pending_roster_students(
    linked_students: list[StudentIdentity],
    reserved_emails: set[str],
) -> list[dict[str, str]]:
    linked_first_names = [student.first_name for student in linked_students]
    linked_last_names = [student.last_name for student in linked_students]
    if len(set(linked_first_names)) != len(linked_first_names):
        raise ValueError("Linked presentation students must start with unique first names")
    if len(set(linked_last_names)) != len(linked_last_names):
        raise ValueError("Linked presentation students must start with unique last names")

    repeated_first_names = [
        *linked_first_names[:3],
        *(name for name in linked_first_names[3:6] for _ in range(2)),
    ]
    unique_first_names = unique_names(
        PENDING_FIRST_NAMES,
        80 - len(repeated_first_names),
        set(linked_first_names),
        " ",
    )
    first_names = [*repeated_first_names, *unique_first_names]
    available_last_names = [
        name for name in dict.fromkeys(PENDING_LAST_NAMES)
        if name not in linked_last_names
    ]
    last_names = []
    for first_name in first_names:
        match = next(
            (
                last_name
                for last_name in available_last_names
                if presentation_email(first_name, last_name) not in reserved_emails
            ),
            None,
        )
        if match is None:
            raise ValueError(f"Unable to assign a unique surname to {first_name}")
        available_last_names.remove(match)
        last_names.append(match)

    students = []
    for number, first_name, last_name in zip(
        range(21, 101),
        first_names,
        last_names,
        strict=True,
    ):
        students.append(
            {
                "email": presentation_email(first_name, last_name),
                "first_name": first_name,
                "last_name": last_name,
                "student_number": f"81{number:06d}",
            }
        )
    return students


def _write_roster(
    path: Path,
    linked_students: list[StudentIdentity],
    reserved_emails: set[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=("email", "first_name", "last_name", "student_number"),
        )
        writer.writeheader()
        for student in linked_students:
            writer.writerow(student.__dict__)
        writer.writerows(_pending_roster_students(linked_students, reserved_emails))


async def build(output_dir: Path) -> None:
    flow_paths = {name: output_dir / directory for name, directory in FLOW_DIRS.items()}
    for path in flow_paths.values():
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    required_student_numbers = set(LINKED_ROSTER_STUDENT_NUMBERS)
    required_emails = {
        *(email for email, _ in CANVAS_SCAN_IDENTITIES),
        CANVAS_REVIEW_STUDENT_EMAIL,
    }

    async with AsyncSessionLocal() as session:
        users = (
            await session.execute(
                select(User).where(
                    or_(
                        User.student_number.in_(required_student_numbers),
                        User.email.in_(required_emails),
                    )
                )
            )
        ).scalars().all()
        users_by_email = {user.email: user for user in users}
        users_by_student_number = {user.student_number: user for user in users}
        reserved_emails = set(
            (await session.execute(select(User.email))).scalars().all()
        )

    missing_emails = required_emails - set(users_by_email)
    missing_student_numbers = required_student_numbers - set(users_by_student_number)
    if missing_emails or missing_student_numbers:
        sys.exit(
            "ERROR: presentation users were not found; run `make dev-seed` first: "
            + ", ".join(sorted(missing_emails | missing_student_numbers))
        )

    linked_roster = [
        _identity(users_by_student_number[number])
        for number in LINKED_ROSTER_STUDENT_NUMBERS
    ]
    clean_students = [
        (_identity(users_by_student_number[number]), version)
        for number, version in CLEAN_SCAN_IDENTITIES
    ]
    review_student = _identity(
        users_by_student_number[REVIEW_SCAN_STUDENT_NUMBER]
    )
    key_identity = clean_students[0][0]
    invitation_student = _identity(INVITATION_STUDENT)
    canvas_students = [
        (_identity(users_by_email[email]), version)
        for email, version in CANVAS_SCAN_IDENTITIES
    ]
    canvas_review_student = _identity(users_by_email[CANVAS_REVIEW_STUDENT_EMAIL])

    _write_roster(
        flow_paths["empty"] / "roster-100.csv",
        linked_roster,
        reserved_emails,
    )

    for option_name, option in TEMPLATE_OPTIONS.items():
        template = _template(option)

        for flow, header in (
            ("empty", MANUAL_HEADER),
            ("seeded", SEEDED_KEY_HEADER),
            ("canvas", CANVAS_HEADER),
        ):
            option_path = flow_paths[flow] / option_name
            _write_batch(
                option_path / "answer-keys-A-B.pdf",
                _answer_keys(template, key_identity, header, mark_versions=True),
            )
            if option_name == "mixed-15-a-k":
                _write_batch(
                    option_path / "optional-answer-keys-no-version-marks.pdf",
                    _answer_keys(template, key_identity, header, mark_versions=False),
                )

        for flow, header in (
            ("empty", MANUAL_HEADER),
            ("seeded", SEEDED_SCAN_HEADERS[option_name]),
        ):
            _write_batch(
                flow_paths[flow] / option_name / "student-scans-9.pdf",
                _student_batch(
                    template,
                    clean_students,
                    review_student,
                    header,
                    NORMAL_SCORES[template.total_questions],
                ),
            )

        _write_batch(
            flow_paths["canvas"] / option_name / "student-scans-6.pdf",
            _student_batch(
                template,
                canvas_students,
                canvas_review_student,
                CANVAS_HEADER,
                CANVAS_SCORES[template.total_questions],
            ),
        )
        invitation_path = flow_paths["invitation"] / option_name
        _write_batch(
            invitation_path / "invitation-student-scan.pdf",
            [
                _render(
                    template,
                    invitation_student,
                    version="B",
                    correct_count=template.total_questions - 3,
                    header=CANVAS_HEADER,
                )
            ],
        )

    print(f"Presentation uploads written to {output_dir.resolve()}")
    for name, directory in FLOW_DIRS.items():
        assets = sorted(
            str(path.relative_to(flow_paths[name]))
            for path in flow_paths[name].rglob("*")
            if path.is_file()
        )
        print(f"  {directory}: {', '.join(assets) if assets else 'no uploads required'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/presentation_flows"),
    )
    args = parser.parse_args()

    async def run() -> None:
        try:
            await build(args.output_dir)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
