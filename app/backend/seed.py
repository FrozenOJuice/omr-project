#!/usr/bin/env python3
"""
Database seed script — populates the DB with realistic test data.

Run inside the backend container (recommended):
    docker compose exec backend python seed.py

Run locally (requires DATABASE_URL pointed at a reachable Postgres):
    DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/capstone python seed.py

The script is idempotent: running it twice will not create duplicates.
"""

import asyncio
import calendar
import logging
import os
import string
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from constants.blueprints import UBCO_100_BLUEPRINT, UBCO_100_QUESTION_CONFIG
from core.security import hash_password
from core.settings import settings
import db.base  # Register the complete SQLAlchemy model graph.
from dependencies.storage_dep import get_storage_repo
from errors.exceptions import ConflictError
from models.course import Course
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_template import ExamTemplate
from models.exam_grade import ExamGrade
from models.grade_audit_entry import GradeAuditEntry
from models.omr_detected_mark import MarkFieldType, OMRDetectedMark
from models.omr_marking import OMRMarking
from models.review_request import ReviewRequest
from models.review_request_audit_entry import ReviewRequestAuditEntry
from models.retention_policy import RetentionPolicy, RetentionPolicySource
from models.scan import Scan
from models.user import AccountStatus, User, UserRole
from presentation_config import (
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
from repositories import course_roster_entries
from repositories.exam_answer_keys import get_answer_key_by_version
from repositories.exam_grades import list_grades_by_exam
from repositories.omr_templates import get_omr_template_by_id
from repositories.review_requests import list_by_grade
from schemas.course_schema import AddStudentRequest
from schemas.exam_answer_keys import AnswerKeyItem, CreateExamAnswerKeyRequest, GradingType
from schemas.exam_templates import default_template_sections
from schemas.retention_policy import (
    UBC_EXAM_RECORD_RETENTION_MONTHS,
    UBC_SCANNED_IMAGE_RETENTION_MONTHS,
)
from services.scan_processing import run_pdf_batch_pipeline
from services.scan_simulation import render_scanner_like_pdf
from services.course import add_student_to_course
from services.academic_terms import resolve_imported_term
from services.exam import release_exam
from services.exam_answer_keys import create_new_answer_key
from services.exam_generator import (
    build_exam_header,
    finalize_exam_template,
    generate_template_pdf,
    render_filled_scan_pdf,
)
from services.grading_service import grade_marking
from db.session import engine as _app_engine

# db.session's engine (used internally by run_pdf_batch_pipeline's
# own AsyncSessionLocal) echoes every query when DEBUG=true -- useful for the
# running API server, just noise for this script. Setting a logger level
# doesn't touch this: SQLAlchemy's echo=True bypasses the normal logging
# hierarchy and hardcodes INFO internally (see sqlalchemy.log.InstanceLogger
# .log/_echo_map), so the actual fix is flipping the engine's own echo flag.
_app_engine.echo = False

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL environment variable is not set.")

engine = create_async_engine(DATABASE_URL, echo=False)
Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

DEFAULT_PASSWORD = "Password123!"

# ---------------------------------------------------------------------------
# Question config helpers
# ---------------------------------------------------------------------------

MCHOICES   = ["A", "B", "C", "D"]
MC5CHOICES = ["A", "B", "C", "D", "E"]


def mc_config(n: int, choices: list[str] = MCHOICES) -> dict:
    return {str(i): {"choices": choices} for i in range(1, n + 1)}


# ---------------------------------------------------------------------------
# Detected-mark helpers
# ---------------------------------------------------------------------------

# Cycle through A/B/C/D to produce plausible answer sequences
_ANSWER_CYCLE = ["A", "B", "C", "D"]


def _question_answers(n: int, offset: int = 0) -> list[str]:
    return [_ANSWER_CYCLE[(i + offset) % 4] for i in range(n)]


def _student_id_marks(marking_id, student_number: str, confidence: float = 0.96) -> list[OMRDetectedMark]:
    return [
        OMRDetectedMark(
            marking_id=marking_id,
            field_type=MarkFieldType.STUDENT_ID,
            field_index=i,
            detected_value=digit,
            confidence_score=confidence,
            needs_review=False,
        )
        # field_index is 1-based to match the OMR service / decoder convention
        # (decode_identity_fields reads positions 1..max), like _question_marks.
        for i, digit in enumerate(student_number, start=1)
    ]


def _name_marks(marking_id, first: str, last: str, confidence: float = 0.95) -> list[OMRDetectedMark]:
    marks = [
        OMRDetectedMark(
            marking_id=marking_id,
            field_type=MarkFieldType.FIRST_NAME,
            field_index=i,
            detected_value=ch.upper(),
            confidence_score=confidence,
            needs_review=False,
        )
        # 1-based field_index (see _student_id_marks / decode_identity_fields).
        for i, ch in enumerate(first[:6], start=1)  # bubble sheets typically cap name length
    ]
    marks += [
        OMRDetectedMark(
            marking_id=marking_id,
            field_type=MarkFieldType.LAST_NAME,
            field_index=i,
            detected_value=ch.upper(),
            confidence_score=confidence,
            needs_review=False,
        )
        for i, ch in enumerate(last[:6], start=1)
    ]
    return marks


def _version_mark(marking_id, version: str, confidence: float = 0.99) -> OMRDetectedMark:
    return OMRDetectedMark(
        marking_id=marking_id,
        field_type=MarkFieldType.VERSION,
        field_index=0,
        detected_value=version,
        confidence_score=confidence,
        needs_review=False,
    )


def _question_marks(marking_id, answers: list[str], confidence: float = 0.97) -> list[OMRDetectedMark]:
    return [
        OMRDetectedMark(
            marking_id=marking_id,
            field_type=MarkFieldType.QUESTION,
            field_index=i + 1,
            detected_value=ans,
            confidence_score=confidence,
            needs_review=False,
        )
        for i, ans in enumerate(answers)
    ]


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

# Kept to exactly this one shape (10 questions, A-E, 2 versions): 3 physical
# bubble sheets were hand-filled and printed from this template (2 on
# version A, 1 on version B) for manual real-scan upload testing later.
# Changing the layout would make those physical sheets invalid.
EXAM_TEMPLATES = [
    {"name": "Short Quiz (10-Question MC)", "question_config": mc_config(10, choices=MC5CHOICES), "n_versions": 2},
    {
        "name": "Multiple Choice Exam (24 Questions)",
        "question_config": mc_config(24, choices=MC5CHOICES),
        "n_versions": 3,
    },
]

_STATS_FIRST_NAMES = (
    "Adeline", "Brandon", "Celeste", "Darius", "Elise", "Felix",
    "Giselle", "Hugo", "Iris", "Jasper", "Keira", "Milo", "Nadia",
    "Orion", "Phoebe", "Quentin", "Rhea", "Tristan",
)
_STATS_LAST_NAMES = (
    "Armstrong", "Bishop", "Caldwell", "Delaney", "Everett", "Franklin",
    "Griffin", "Hawthorne", "Ingram", "Jennings", "Kendall", "Lawson",
    "Monroe", "Nolan", "Prescott", "Quinn", "Rowan", "Sinclair",
)

STATS_SHOWCASE_STUDENTS = [
    {
        "first_name": _STATS_FIRST_NAMES[index - 1],
        "last_name": _STATS_LAST_NAMES[index - 1],
        "email": presentation_email(
            _STATS_FIRST_NAMES[index - 1],
            _STATS_LAST_NAMES[index - 1],
        ),
        "role": UserRole.STUDENT,
        "student_number": f"91{index:06d}",
    }
    for index in range(1, 19)
]

# The custom (non-blueprint) entry below carries an explicit "Section 1"
# section covering all its questions, the same shape a template created
# through the real app UI gets by default (see default_template_sections in
# schemas/exam_templates.py). It uses its own question_config/name rather
# than reusing "Short Quiz (10-Question MC)": that template's bubble layout
# is locked (3 hand-filled physical sheets, see EXAM_TEMPLATES above), and
# adding a section header shifts every question's row down by one
# HEADER_EXTRA_H, which would invalidate them.
#
# The UBC blueprint's physical sheet layout comes from the hand-made
# mark.json/scan.json (see UBC_TEMPLATE_DIR in services/exam_generator.py),
# not from question_config, but question_config is still required (answer-key
# validation reads it) and must use the blueprint's own field-ID shape
# ("1".."100", not render_filled_ubc_scan_pdf's separate "Q1".."Q100"
# mark.json IDs).
_SCALE_CUSTOM_QUESTION_CONFIG = mc_config(10, choices=MC5CHOICES)

SCALE_EXAM_TEMPLATES = [
    {
        "name": "Sectioned Quiz (10-Question MC)",
        "question_config": _SCALE_CUSTOM_QUESTION_CONFIG,
        "n_versions": 2,
        "sections": [
            section.model_dump()
            for section in default_template_sections(_SCALE_CUSTOM_QUESTION_CONFIG)
        ],
    },
    {
        "name": "UBC Blueprint Exam (100Q)",
        "question_config": UBCO_100_QUESTION_CONFIG,
        "n_versions": 1,
        "blueprint": UBCO_100_BLUEPRINT,
    },
    {
        "name": DEFAULT_PRESENTATION_TEMPLATE_NAME,
        "question_config": DEFAULT_PRESENTATION_QUESTION_CONFIG,
        "n_versions": 2,
        "sections": DEFAULT_PRESENTATION_SECTIONS,
    },
    {
        "name": PRESENTATION_TEMPLATE_NAME,
        "question_config": PRESENTATION_QUESTION_CONFIG,
        "n_versions": 2,
        "sections": PRESENTATION_SECTIONS,
    },
]

USERS = [
    {"first_name": "Admin", "last_name": "User",      "email": "admin@example.com",      "role": UserRole.ADMIN,     "student_number": None},
    # Staff identities are deliberately fake-looking (test.*@example.com) so
    # seeded data can never be mistaken for a real professor.
    {"first_name": "Test",  "last_name": "Professor",  "email": "test.prof@example.com", "role": UserRole.PROFESSOR, "student_number": None},
    # Presentation entry points. These accounts deliberately own no seeded
    # courses or templates so a fresh database always opens on a clean slate.
    {"first_name": "Avery", "last_name": "Brooks", "email": "empty.prof@example.com", "role": UserRole.PROFESSOR, "student_number": None},
    # A second professor, enrolled but not the course owner, to exercise the
    # promoted co-professor path (view + resolve regrades, no owner actions).
    {"first_name": "Test",  "last_name": "Co-Professor", "email": "test.coprof@example.com", "role": UserRole.PROFESSOR, "student_number": None},
    # Joe Blow/Mama/Shmoe also have 3 physically hand-filled bubble sheets
    # (see EXAM_TEMPLATES) for manual real-scan upload testing -- their
    # names/student numbers must stay exactly as-is. Student names otherwise
    # stay realistic-looking (unlike staff) since that's not a collision risk.
    {"first_name": "Joe",   "last_name": "Blow",      "email": "joe.blow@example.com",    "role": UserRole.STUDENT, "student_number": "12345678"},
    {"first_name": "Joe",   "last_name": "Mama",      "email": "joe.mama@example.com",    "role": UserRole.STUDENT, "student_number": "67676767"},
    {"first_name": "Joe",   "last_name": "Shmoe",     "email": "joe.shmoe@example.com",   "role": UserRole.STUDENT, "student_number": "11111111"},
    {"first_name": "Alice", "last_name": "Chen",      "email": "alice.chen@example.com",  "role": UserRole.STUDENT, "student_number": "22334455"},
    {"first_name": "Maria", "last_name": "Garcia",    "email": "maria.garcia@example.com", "role": UserRole.STUDENT, "student_number": "33445566"},
    {"first_name": "Wei",   "last_name": "Zhang",     "email": "wei.zhang@example.com",   "role": UserRole.STUDENT, "student_number": "44556677"},
    # Clean released-result accounts for backup student demonstrations.
    {"first_name": "Taylor", "last_name": "Morgan", "email": "taylor.morgan@example.com", "role": UserRole.STUDENT, "student_number": "88990011"},
    {"first_name": "Jordan", "last_name": "Lee", "email": "jordan.lee@example.com", "role": UserRole.STUDENT, "student_number": "99001122"},
    {"first_name": "Priya", "last_name": "Patel",     "email": "priya.patel@example.com", "role": UserRole.STUDENT, "student_number": "55667788"},
    {"first_name": "Liam",  "last_name": "O'Brien",   "email": "liam.obrien@example.com", "role": UserRole.STUDENT, "student_number": "66778899"},
    {"first_name": "Sofia", "last_name": "Rossi",     "email": "sofia.rossi@example.com", "role": UserRole.STUDENT, "student_number": "77889900"},
] + [
    {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "role": UserRole.STUDENT,
        "student_number": student_number,
    }
    for first_name, last_name, email, student_number in CANVAS_LINKED_STUDENTS
] + STATS_SHOWCASE_STUDENTS

# --- Scale-testing roster ---
#
# Broad deterministic name pools keep the large roster natural while allowing
# strict, testable duplicate limits without numeric suffixes.
_SCALE_FIRST_NAMES = [
    "Olivia", "Noah", "Emma", "Liam", "Ava", "William", "Sophia", "James",
    "Isabella", "Benjamin", "Mia", "Lucas", "Charlotte", "Henry", "Amelia",
    "Alexander", "Harper", "Michael", "Evelyn", "Ethan",
    "Camila", "Daniel", "Luna", "Matthew", "Sofia", "Jackson", "Aria",
    "Sebastian", "Scarlett", "Jack", "Chloe", "Owen", "Layla", "Samuel",
    "Mila", "Leo", "Nora", "Julian", "Hazel", "David", "Ellie", "Joseph",
    "Violet", "Wyatt", "Aurora", "John", "Savannah", "Luke", "Natalie",
    "Gabriel", "Grace", "Isaac", "Zoe", "Anthony", "Hannah", "Dylan",
    "Victoria", "Lincoln", "Elena", "Thomas", "Maya", "Levi", "Naomi",
    "Mateo", "Sarah", "Andrew", "Addison", "Joshua", "Audrey", "Christopher",
    "Leah", "Nathan", "Lucy", "Ryan", "Brooklyn", "Adrian", "Claire",
    "Charles", "Skylar", "Josiah", "Anna", "Robert", "Caroline", "Jonathan",
    "Genesis", "Nicholas", "Aaliyah", "Dominic", "Kennedy", "Austin",
    "Kinsley", "Adam", "Allison", "Xavier", "Gabriella", "Jace", "Madelyn",
    "Everett", "Cora", "Wesley", "Ruby", "Vincent", "Eva", "Silas", "Alice",
    "Bennett", "Valentina", "Parker", "Sadie", "Theodore", "Piper",
    *PRESENTATION_ADDITIONAL_FIRST_NAMES,
]
_SCALE_LAST_NAMES = [
    "Nguyen", "Smith", "Kim", "Singh", "Martin", "Johnson", "Lee", "Brown",
    "Wilson", "Ahmed", "Davis", "Clark", "Lewis", "Walker", "Young",
    "King", "Wright", "Scott", "Green", "Baker",
    "Garcia", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Perez", "Thompson", "White", "Harris", "Sanchez", "Ramirez", "Robinson",
    "Patel", "Chen", "Campbell", "Mitchell", "Roberts", "Carter", "Phillips",
    "Evans", "Turner", "Torres", "Parker", "Collins", "Edwards", "Stewart",
    "Flores", "Morris", "Murphy", "Rivera", "Cook", "Rogers", "Morgan",
    "Peterson", "Cooper", "Reed", "Bailey", "Bell", "Gomez", "Kelly",
    "Howard", "Ward", "Cox", "Diaz", "Richardson", "Wood", "Watson", "Brooks",
    "Bennett", "Gray", "James", "Reyes", "Cruz", "Hughes", "Price", "Myers",
    "Long", "Foster", "Sanders", "Ross", "Morales", "Powell", "Sullivan",
    "Russell", "Ortiz", "Jenkins", "Gutierrez", "Perry", "Butler", "Barnes",
    "Fisher", "Henderson", "Coleman", "Simmons", "Patterson", "Jordan",
    "Reynolds", "Hamilton", "Graham", "Wallace", "Woods", "Cole", "West",
    "Owens", "Webb", "Tucker", "Freeman", "Wells",
    *PRESENTATION_ADDITIONAL_LAST_NAMES,
]

SCALE_STUDENT_COUNT = 200
# The first SCALE_SHOWCASE_COUNT identities have committed general-purpose
# scan fixtures. Their fixed index order and student numbers keep those files
# stable even though every student's email is name-based.
SCALE_SHOWCASE_COUNT = 20


def _generate_scale_students() -> list[dict]:
    """Builds SCALE_STUDENT_COUNT synthetic student dicts (same shape as
    USERS). Fully deterministic (no randomness) so re-running seed.py always
    produces the exact same roster for email-based seed deduplication.
    Student numbers live in a reserved 9xxxxxxx block, distinct from USERS'
    existing 8-digit IDs (none of which start with 9).
    """
    # Preserve the first 20 showcase identities embedded in the committed
    # general-purpose scan fixtures. They begin with unique first/last names.
    showcase_first_names = _SCALE_FIRST_NAMES[:SCALE_SHOWCASE_COUNT]
    showcase_last_names = [
        _SCALE_LAST_NAMES[(7 * index) % SCALE_SHOWCASE_COUNT]
        for index in range(SCALE_SHOWCASE_COUNT)
    ]

    # Across all 200 students, exactly three first names occur twice and
    # three occur three times. Every other first name occurs once, and every
    # last name is unique. The same six repeated first names feed the 100-row
    # CSV's intentionally limited duplicates.
    repeated_first_names = [
        *showcase_first_names[:3],
        *(name for name in showcase_first_names[3:6] for _ in range(2)),
    ]
    unique_first_names = unique_names(
        _SCALE_FIRST_NAMES,
        SCALE_STUDENT_COUNT - SCALE_SHOWCASE_COUNT - len(repeated_first_names),
        set(showcase_first_names),
        " ",
    )
    first_names = [
        *showcase_first_names,
        *repeated_first_names,
        *unique_first_names,
    ]
    last_names = [
        *showcase_last_names,
        *unique_names(
            _SCALE_LAST_NAMES,
            SCALE_STUDENT_COUNT - SCALE_SHOWCASE_COUNT,
            set(showcase_last_names),
            "-",
        ),
    ]

    students = []
    for i, (first, last) in enumerate(zip(first_names, last_names, strict=True)):
        students.append({
            "first_name": first,
            "last_name": last,
            "email": presentation_email(first, last),
            "role": UserRole.STUDENT,
            "student_number": f"9{i:07d}",
        })
    return students


SCALE_USERS = _generate_scale_students()

# The development dataset uses realistic course names so screenshots and
# presentations resemble a real deployment. All presentation email addresses
# use reserved test domains. Historical rows reuse the same course name under
# different years
# to feed the course-comparison UI.
COURSES = [
    {
        "name": "COSC 221 - Data Structures",
        "term_name": "Summer Session 2",
        "professor_email": "test.prof@example.com",
        "enrolments": [
            ("test.prof@example.com",    "professor"),
            ("test.coprof@example.com",  "professor"),
            ("joe.blow@example.com",     "student"),
            ("joe.mama@example.com",     "student"),
            ("joe.shmoe@example.com",    "student"),
            ("alice.chen@example.com",   "student"),
            ("maria.garcia@example.com", "student"),
            ("wei.zhang@example.com",    "student"),
            ("taylor.morgan@example.com", "student"),
            ("jordan.lee@example.com",    "student"),
            ("priya.patel@example.com",  "student"),
            ("liam.obrien@example.com",  "student"),
            ("sofia.rossi@example.com",  "student"),
        ],
        "exams": [
            {
                "name": "Quiz 1",
                "description": "Quiz covering asymptotic analysis and fundamental data structures.",
                "template_name": "Short Quiz (10-Question MC)",
                "start_offset_days": -3,
                "duration_hours": 1,
                "seed_answer_keys": False,
            },
            {
                "name": "Midterm Exam",
                "description": "Midterm covering lists, stacks, queues, trees, and hashing.",
                "template_name": "Short Quiz (10-Question MC)",
                "start_offset_days": -21,
                "duration_hours": 1,
            },
            {
                "name": "Final Exam",
                "description": "Comprehensive final examination.",
                "template_name": "Short Quiz (10-Question MC)",
                "start_offset_days": -7,
                "duration_hours": 1,
            },
        ],
    },
    {
        "name": "COSC 304 - Database Systems",
        "term_name": "Summer Session 2",
        "professor_email": "test.prof@example.com",
        "enrolments": [
            ("test.prof@example.com", "professor"),
            ("test.coprof@example.com", "professor"),
            *[(student["email"], "student") for student in STATS_SHOWCASE_STUDENTS],
        ],
        "exams": [
            {
                "name": "Database Systems Final Exam",
                "description": (
                    "Comprehensive final covering data modelling, SQL, "
                    "normalization, transactions, and indexing."
                ),
                "template_name": "Multiple Choice Exam (24 Questions)",
                "start_offset_days": -14,
                "duration_hours": 2,
            },
        ],
    },
    {
        "name": "COSC 221 - Data Structures",
        "term_name": "Summer Session 2",
        "academic_year_start": 2024,
        "archived_at": datetime(2025, 8, 31, tzinfo=timezone.utc),
        "historical": True,
        "professor_email": "test.prof@example.com",
        "enrolments": [
            ("test.prof@example.com",    "professor"),
            ("test.coprof@example.com",  "professor"),
            ("joe.blow@example.com",     "student"),
            ("joe.mama@example.com",     "student"),
            ("joe.shmoe@example.com",    "student"),
            ("alice.chen@example.com",   "student"),
            ("maria.garcia@example.com", "student"),
            ("wei.zhang@example.com",    "student"),
        ],
        "exams": [
            {
                "name": "Midterm Exam",
                "description": "Archived midterm covering core data structures.",
                "template_name": "Short Quiz (10-Question MC)",
                "start_offset_days": -414,
                "duration_hours": 1,
            },
        ],
    },
    {
        "name": "COSC 221 - Data Structures",
        "term_name": "Summer Session 2",
        "academic_year_start": 2023,
        "archived_at": datetime(2024, 8, 31, tzinfo=timezone.utc),
        "historical": True,
        "professor_email": "test.prof@example.com",
        "enrolments": [
            ("test.prof@example.com",   "professor"),
            ("test.coprof@example.com", "professor"),
            ("joe.blow@example.com",    "student"),
            ("joe.mama@example.com",    "student"),
            ("joe.shmoe@example.com",   "student"),
            ("alice.chen@example.com",  "student"),
        ],
        "exams": [
            {
                "name": "Midterm Exam",
                "description": "Archived midterm covering core data structures.",
                "template_name": "Short Quiz (10-Question MC)",
                "start_offset_days": -779,
                "duration_hours": 1,
            },
        ],
    },
    {
        "name": "COSC 210 - Software Engineering",
        "term_name": "Summer Session 1",
        "academic_year_start": 2023,
        "archived_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
        "historical": True,
        "retention_demo": True,
        "professor_email": "test.prof@example.com",
        "enrolments": [
            ("test.prof@example.com", "professor"),
            ("joe.blow@example.com", "student"),
        ],
        "exams": [
            {
                "name": "Requirements Midterm",
                "description": "Midterm covering requirements analysis and software modelling.",
                "template_name": "Short Quiz (10-Question MC)",
                "start_offset_days": -800,
                "duration_hours": 1,
            },
        ],
    },
]


def build_scale_course_def() -> dict:
    """Large-roster course with custom, mixed, and UBC blueprint exams.

    These exams receive no seeded scans, so a manual presentation upload
    stands out against an otherwise-empty grade sheet.
    """
    return {
        "name": "COSC 499 - Capstone Project",
        "term_name": "Summer Session 2",
        "professor_email": "test.prof@example.com",
        "summarize_enrolments": True,
        "enrolments": [
            ("test.prof@example.com", "professor"),
            *[(s["email"], "student") for s in SCALE_USERS],
        ],
        "exams": [
            {
                "name": "Capstone Midterm",
                "description": "Midterm evaluation of project planning, design, and implementation progress.",
                "template_name": "Sectioned Quiz (10-Question MC)",
                "start_offset_days": -5,
                "duration_hours": 1,
            },
            {
                "name": "Capstone Final Exam",
                "description": "Comprehensive assessment of capstone project methods and outcomes.",
                "template_name": "UBC Blueprint Exam (100Q)",
                "start_offset_days": -5,
                "duration_hours": 1,
            },
            {
                "name": "Default 10-Question Upload Exam",
                "description": "Ready-to-use 10-question A-E exam with answer keys and no uploaded scans.",
                "template_name": DEFAULT_PRESENTATION_TEMPLATE_NAME,
                "start_offset_days": 2,
                "duration_hours": 1,
            },
            {
                "name": "Mixed 15-Question Upload Exam",
                "description": "Ready-to-use mixed-format A-K exam with answer keys and no uploaded scans.",
                "template_name": PRESENTATION_TEMPLATE_NAME,
                "start_offset_days": 2,
                "duration_hours": 1,
            },
        ],
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def get_or_create_user(session: AsyncSession, data: dict) -> tuple[User, bool]:
    result = await session.execute(select(User).where(User.email == data["email"]))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    user = User(
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
        password_hash=hash_password(DEFAULT_PASSWORD),
        role=data["role"].value,
        student_number=data.get("student_number"),
        status=AccountStatus.ACTIVE.value,
    )
    session.add(user)
    await session.flush()
    return user, True


async def get_or_create_retention_policy(
    session: AsyncSession,
    owner: User,
) -> tuple[RetentionPolicy, bool]:
    """Give the seeded professor the recommended UBC policy without
    overwriting a policy a developer has changed through the frontend."""
    result = await session.execute(
        select(RetentionPolicy).where(RetentionPolicy.owner_user_id == owner.id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False

    policy = RetentionPolicy(
        owner_user_id=owner.id,
        scanned_image_retention_months=UBC_SCANNED_IMAGE_RETENTION_MONTHS,
        exam_record_retention_months=UBC_EXAM_RECORD_RETENTION_MONTHS,
        retain_anonymized_analytics=True,
        source=RetentionPolicySource.UBC_DEFAULT.value,
    )
    session.add(policy)
    await session.flush()
    return policy, True


async def get_or_create_exam_template(
    session: AsyncSession, data: dict, professor: User
) -> tuple[ExamTemplate, bool]:
    """Creates the ExamTemplate row only. The physical PDF and OMR service
    registration happen later through the same generate/finalize flow the
    frontend uses."""
    result = await session.execute(
        select(ExamTemplate).where(
            ExamTemplate.name == data["name"],
            ExamTemplate.created_by == professor.id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    qc = data["question_config"]
    tmpl = ExamTemplate(
        name=data["name"],
        created_by=professor.id,
        question_config=qc,
        total_questions=len(qc),
        n_versions=data.get("n_versions", 4),
        version=1,
        blueprint=data.get("blueprint"),
        version_from_q1=data.get("version_from_q1", False),
        sections=data.get("sections", []),
    )
    session.add(tmpl)
    await session.flush()
    return tmpl, True


async def seed_answer_keys_for_exam(
    session: AsyncSession, exam: Exam, template: ExamTemplate
) -> int:
    """Defines one answer key per exam version, exactly as a professor would
    through the answer-key UI. Required before the template can be finalized.
    A single-version template (n_versions == 1, e.g. the UBC blueprint) uses
    one unversioned answer key (exam_version=None) rather than a lettered
    "A" version -- see _validate_exam_version in services/exam_answer_keys.py,
    which rejects a non-None version when version_count == 1."""
    created = 0
    versions: list[str | None] = (
        [None] if template.n_versions == 1 else list(string.ascii_uppercase[: template.n_versions])
    )
    for offset, version in enumerate(versions):
        if await get_answer_key_by_version(session, exam.id, template.id, version):
            continue
        answer_key = {
            q_num: AnswerKeyItem(
                grading_type=GradingType.SINGLE,
                correct_choices=[cfg["choices"][(int(q_num) - 1 + offset) % len(cfg["choices"])]],
                points=1.0,
            )
            for q_num, cfg in template.question_config.items()
        }
        await create_new_answer_key(
            session,
            exam.id,
            CreateExamAnswerKeyRequest(
                exam_template_id=template.id,
                exam_version=version,
                answer_key=answer_key,
            ),
            requesting_user_id=exam.created_by,
        )
        created += 1
    return created


async def ensure_template_registered(session: AsyncSession, template: ExamTemplate) -> bool:
    """Runs the real generate-PDF + finalize flow for a template, registering
    it with the OMR service so it behaves identically to one built through the
    frontend. No-ops if the template already has a genuine registration — but
    re-registers if omr_template_id points at a row that was never actually
    uploaded to the OMR service (e.g. left over from an older seed script)."""
    if template.omr_template_id:
        omr_template = await get_omr_template_by_id(session, template.omr_template_id)
        if omr_template and omr_template.preprocess_template_id and omr_template.mark_template_id:
            return False
    storage_repo = get_storage_repo()
    await generate_template_pdf(session, storage_repo, template.id, template.created_by)
    await finalize_exam_template(session, storage_repo, template.id, template.created_by)
    return True


async def get_or_create_course(
    session: AsyncSession,
    name: str,
    term_name: str,
    professor_id,
    academic_year_start: int,
    archived_at: datetime | None = None,
    retention_policy: RetentionPolicy | None = None,
) -> tuple[Course, bool]:
    professor = await session.get(User, professor_id)
    if professor is None:
        raise RuntimeError("Course professor must exist before seeding courses")
    academic_term = await resolve_imported_term(
        session,
        professor,
        term_name,
    )
    result = await session.execute(
        select(Course).where(
            Course.name == name,
            Course.academic_term_id == academic_term.id,
            Course.academic_year_start == academic_year_start,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        if archived_at is not None and retention_policy is not None:
            _apply_archive_retention(
                existing,
                archived_at=archived_at,
                archived_by_user_id=professor_id,
                retention_policy=retention_policy,
            )
            await session.flush()
        return existing, False
    course = Course(
        name=name,
        academic_term_id=academic_term.id,
        academic_term=academic_term,
        academic_year_start=academic_year_start,
        created_by=professor_id,
    )
    if archived_at is not None and retention_policy is not None:
        _apply_archive_retention(
            course,
            archived_at=archived_at,
            archived_by_user_id=professor_id,
            retention_policy=retention_policy,
        )
    session.add(course)
    await session.flush()
    return course, True


def _apply_archive_retention(
    course: Course,
    *,
    archived_at: datetime,
    archived_by_user_id,
    retention_policy: RetentionPolicy,
) -> None:
    """Populate missing archive metadata while preserving its policy snapshot."""
    course.archived_at = course.archived_at or archived_at
    course.archived_by_user_id = course.archived_by_user_id or archived_by_user_id
    course.retention_policy_id = course.retention_policy_id or retention_policy.id

    if course.retention_policy_snapshot is None:
        course.retention_policy_snapshot = {
            "scanned_image_retention_months": retention_policy.scanned_image_retention_months,
            "exam_record_retention_months": retention_policy.exam_record_retention_months,
            "retain_anonymized_analytics": retention_policy.retain_anonymized_analytics,
            "source": retention_policy.source,
        }

    snapshot = course.retention_policy_snapshot
    if course.scanned_images_retention_until is None:
        course.scanned_images_retention_until = _add_months(
            course.archived_at,
            int(snapshot["scanned_image_retention_months"]),
        )
    if course.exam_records_retention_until is None:
        course.exam_records_retention_until = _add_months(
            course.archived_at,
            int(snapshot["exam_record_retention_months"]),
        )


def _add_months(value: datetime, months: int) -> datetime:
    """Match the archive service's calendar-month deadline calculation."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


async def get_or_create_enrolment(
    session: AsyncSession, user: User, course: Course, role: str
) -> bool:
    result = await session.execute(
        select(Enrolment).where(
            Enrolment.user_id == user.id, Enrolment.course_id == course.id
        )
    )
    if result.scalar_one_or_none():
        return False
    session.add(Enrolment(user_id=user.id, course_id=course.id, role=role))
    return True


async def get_or_create_roster_entry(
    session: AsyncSession, student: User, course: Course, professor: User
) -> bool:
    """Enrols a student through the same service the frontend's "add student"
    flow uses, rather than inserting a bare Enrolment row -- that's what
    creates the CourseRosterEntry the course's student count and the grade
    sheet's name lookup actually read from (see services/course.py)."""
    existing = await course_roster_entries.get_by_course_and_email(
        session, course.id, student.email
    )
    if existing:
        return False
    await add_student_to_course(
        session,
        course.id,
        AddStudentRequest(
            email=student.email,
            first_name=student.first_name,
            last_name=student.last_name,
            student_number=student.student_number,
        ),
        requesting_user=professor,
    )
    return True


async def get_or_create_exam(
    session: AsyncSession,
    name: str,
    description: str,
    course: Course,
    professor: User,
    template: ExamTemplate | None,
    start_offset_days: int,
    duration_hours: int,
) -> tuple[Exam, bool]:
    result = await session.execute(
        select(Exam).where(Exam.course_id == course.id, Exam.name == name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    now = datetime.now(timezone.utc)
    exam = Exam(
        name=name,
        description=description,
        course_id=course.id,
        created_by=professor.id,
        exam_template_id=template.id if template else None,
        role="student",
        start_time=now + timedelta(days=start_offset_days),
        end_time=now + timedelta(days=start_offset_days, hours=duration_hours),
    )
    session.add(exam)
    await session.flush()
    return exam, True


async def scan_already_exists(session: AsyncSession, path: str) -> bool:
    result = await session.execute(select(Scan).where(Scan.path == path))
    return result.scalar_one_or_none() is not None


async def _clear_batch_a_other_mode(session: AsyncSession, exam: Exam, other_dir: str) -> int:
    """Deletes any Batch A scans (and their cascading markings/detected
    marks/grades) left over when a seeded scenario changes between simulated
    and pipeline-backed scans. This keeps existing development databases from
    accumulating two grades per student. ReviewRequest.exam_grade_id has no
    ON DELETE cascade (unlike GradeAuditEntry), so reviews must be removed
    before their grades.
    """
    prefix = f"seed/{exam.id}/{other_dir}/"
    scans = (
        await session.execute(select(Scan).where(Scan.path.like(f"{prefix}%")))
    ).scalars().all()
    if not scans:
        return 0

    scan_ids = [s.id for s in scans]
    marking_ids = (
        await session.execute(select(OMRMarking.id).where(OMRMarking.scan_id.in_(scan_ids)))
    ).scalars().all()
    grade_ids = (
        await session.execute(select(ExamGrade.id).where(ExamGrade.omr_marking_id.in_(marking_ids)))
    ).scalars().all()
    if grade_ids:
        await session.execute(delete(ReviewRequest).where(ReviewRequest.exam_grade_id.in_(grade_ids)))
    for scan in scans:
        await session.delete(scan)
    await session.commit()
    return len(scans)


async def create_scan_with_marking(
    session: AsyncSession,
    *,
    path: str,
    exam: Exam,
    exam_template: ExamTemplate,
    omr_template_id: uuid.UUID,
    uploader: User,
    scan_status: str,
    marking_status: str,
    detected_marks: list[OMRDetectedMark] | None = None,
    batch_id: uuid.UUID | None = None,
    batch_index: int | None = None,
) -> OMRMarking:
    now = datetime.now(timezone.utc)

    scan = Scan(
        exam_id=exam.id,
        exam_template_id=exam_template.id,
        uploader_user_id=uploader.id,
        path=path,
        page_count=2,
        status=scan_status,
        batch_id=batch_id,
        batch_index=batch_index,
    )
    session.add(scan)
    await session.flush()

    marking = OMRMarking(
        scan_id=scan.id,
        omr_template_id=omr_template_id,
        status=marking_status,
        started_at=now - timedelta(minutes=5),
        finished_at=now - timedelta(minutes=4) if marking_status != "failed" else None,
    )
    session.add(marking)
    await session.flush()

    if detected_marks:
        for mark in detected_marks:
            mark.marking_id = marking.id
            session.add(mark)
        # Flush so a subsequent grade_marking() call can read these marks back.
        await session.flush()

    return marking


# ---------------------------------------------------------------------------
# Scan scenarios
# ---------------------------------------------------------------------------


async def seed_scans(
    session: AsyncSession,
    exam: Exam,
    exam_template: ExamTemplate,
    omr_template_id: uuid.UUID,
    uploader: User,
    students: list[User],
    include_flagged_and_failed: bool = True,
    real_scans: bool = False,
    course: Course | None = None,
) -> int:
    """Seed completed scans (Batch A) for a past exam, plus needs_review
    (Batch B) and failed (Batch C) scans, and an ambiguous double-bubble on
    Batch A's first scan, unless `include_flagged_and_failed` is False. An
    exam with any Batch B/C scans can never reach "Graded" (see
    services/exam.py's get_release_blockers), and one with an unresolved
    ambiguous grade shouldn't be treated as ready for release either, so
    callers that want a genuinely released demo exam must opt out of all of
    it. Returns count created.

    `real_scans` controls how Batch A is produced. False: fabricate
    OMRDetectedMark rows directly, same
    as Batch B/C -- fast, database-only. True: render a real filled PDF per
    student and run it through the actual OMR pipeline -- slower, and needs
    the OMR service and object storage reachable too, but produces a real
    scan file and real OMR/grading output instead of fabricated ones.

    `course`, when given alongside `real_scans=True`, is used to print the
    real exam name/course/date on each rendered sheet's header (see
    build_exam_header) so a real-scans fixture looks like the actual
    finalized exam a student received, not a blank template render.
    """
    created = 0
    base = f"seed/{exam.id}"

    # --- Batch A: clean completed scans, one per given student ---
    batch_a = uuid.uuid4()
    version_cycle = ["A", "B"]
    student_data = [
        (student, student.student_number, version_cycle[idx % len(version_cycle)], idx)
        for idx, student in enumerate(students)
    ]
    # Separate subfolders allow a scenario to move between simulated and real
    # processing without silently reusing a scan created by the other path.
    batch_a_dir = "batch_a_real" if real_scans else "batch_a"
    other_batch_a_dir = "batch_a" if real_scans else "batch_a_real"
    cleared = await _clear_batch_a_other_mode(session, exam, other_batch_a_dir)
    if cleared:
        print(f"  [x] cleared {cleared} pre-existing Batch A scan(s) from the other seeding mode")

    if real_scans:
        storage_repo = get_storage_repo()
        header = build_exam_header(exam, course) if course else None
        for idx, (student, sid, version, answer_offset) in enumerate(student_data):
            path = f"{base}/{batch_a_dir}/scan_{idx + 1:03d}.pdf"
            if await scan_already_exists(session, path):
                continue
            answers = _question_answers(exam_template.total_questions, offset=answer_offset)
            fill_answers = {str(i + 1): [ans] for i, ans in enumerate(answers)}
            if idx == 0 and include_flagged_and_failed:
                # Double-bubble question 1 for real, so this student's
                # otherwise cleanly-identified grade comes out of
                # grade_marking() with question_results["1"]["ambiguous"] =
                # True via grading_service's actual ambiguity detection (see
                # _is_ambiguous) -- see the fabricated-marks branch below for
                # why this scenario exists.
                other_choice = _ANSWER_CYCLE[(_ANSWER_CYCLE.index(answers[0]) + 1) % 4]
                fill_answers["1"] = [answers[0], other_choice]

            print(f"    Generating scan for {student.full_name} (version {version})...")

            pdf_bytes = render_filled_scan_pdf(
                exam_template,
                version=version,
                student_id=sid,
                first_name=student.first_name,
                last_name=student.last_name,
                answers=fill_answers,
                header=header,
            )
            # Degrades the pristine render to look scanner/printer-realistic
            # (skew, perspective jitter, lighting, JPEG artifacts) before
            # it's stored, so the "original scan" a professor downloads
            # actually looks scanned, not like a clean vector PDF.
            pdf_bytes = render_scanner_like_pdf(pdf_bytes)
            storage_repo.upload_file(pdf_bytes, path)

            scan = Scan(
                exam_id=exam.id,
                exam_template_id=exam_template.id,
                uploader_user_id=uploader.id,
                path=path,
                page_count=2,
                batch_id=batch_a,
                batch_index=idx,
            )
            session.add(scan)
            await session.flush()
            # Must be committed (not just flushed): run_pdf_batch_pipeline
            # looks the scan up from its own AsyncSessionLocal session, which
            # can't see uncommitted rows from this one.
            await session.commit()

            # Runs the exact pipeline a real upload takes: upload to OMR ->
            # mark -> grade. Produces a real Scan file
            # at `path`, a real OMRMarking/OMRDetectedMark set, and a real
            # ExamGrade, instead of fabricating all three. It logs its own
            # progress via SQL echo unless silenced (see _app_engine.echo
            # above) -- this print is the human-readable replacement.
            await run_pdf_batch_pipeline(path, scan.id, storage_repo)
            await session.refresh(scan)
            if scan.status == "completed":
                print("      -> completed")
            else:
                print(f"      -> {scan.status}: {scan.failure_code or scan.failure_detail or 'see logs'}")
            created += 1
    else:
        for idx, (student, sid, version, answer_offset) in enumerate(student_data):
            path = f"{base}/{batch_a_dir}/scan_{idx + 1:03d}.pdf"
            if await scan_already_exists(session, path):
                continue
            answers = _question_answers(exam_template.total_questions, offset=answer_offset)
            marks: list[OMRDetectedMark] = []
            marks.append(_version_mark(None, version))
            marks += _student_id_marks(None, sid)
            marks += _name_marks(None, student.first_name, student.last_name)
            question_marks = _question_marks(None, answers)
            if idx == 0 and include_flagged_and_failed:
                # Double-bubble the first question so this student's
                # otherwise cleanly-identified grade comes out of
                # grade_marking() with question_results["1"]["ambiguous"] =
                # True (see grading_service.py's _is_ambiguous) -- exercises
                # the ambiguous-grade badge on a real, matched grade rather
                # than only the scan-level needs_review scenarios in Batch B
                # below. Gated on the same flag as Batch B/C: an exam that's
                # meant to reach a genuinely released "Graded" state
                # (get_release_blockers doesn't care about ambiguous-but-
                # matched grades, but the professor's workflow does --
                # ambiguous questions get resolved via the Review popup
                # before the exam is considered Graded) can't seed one of its
                # own grades stuck ambiguous, or it'd show Review-Required
                # and Released at the same time.
                first = question_marks[0]
                other_choice = _ANSWER_CYCLE[(_ANSWER_CYCLE.index(first.detected_value) + 1) % 4]
                first.detected_value = f"{first.detected_value},{other_choice}"
                first.confidence_score = 0.52
                first.needs_review = True
            marks += question_marks
            marking = await create_scan_with_marking(
                session,
                path=path,
                exam=exam,
                exam_template=exam_template,
                omr_template_id=omr_template_id,
                uploader=uploader,
                scan_status="completed",
                marking_status="completed",
                detected_marks=marks,
                batch_id=batch_a,
                batch_index=idx,
            )
            # Run the real grading pipeline so this clean scan becomes an
            # actual graded ExamGrade (assigned to the student, with an
            # initial_grade audit entry) -- the seeder otherwise leaves
            # markings ungraded.
            await grade_marking(session, marking.id)
            created += 1

    if not include_flagged_and_failed:
        return created

    # --- Batch B: ambiguous scans ---
    batch_b = uuid.uuid4()

    # B-1: student ID partially illegible (several digit positions uncertain)
    path_b1 = f"{base}/batch_b/scan_001.pdf"
    if not await scan_already_exists(session, path_b1):
        marks = [
            _version_mark(None, "A"),
            # First 4 digits clear, last 4 are ambiguous
            *[
                OMRDetectedMark(
                    marking_id=None,
                    field_type=MarkFieldType.STUDENT_ID,
                    field_index=i,
                    detected_value=str(i + 3),
                    confidence_score=0.94,
                    needs_review=False,
                )
                for i in range(4)
            ],
            *[
                OMRDetectedMark(
                    marking_id=None,
                    field_type=MarkFieldType.STUDENT_ID,
                    field_index=i,
                    detected_value=str(i % 3),
                    confidence_score=0.38 + i * 0.04,
                    needs_review=True,
                )
                for i in range(4, 8)
            ],
            *_name_marks(None, "Unknown", "Student"),
            *_question_marks(None, _question_answers(exam_template.total_questions, offset=2)),
        ]
        await create_scan_with_marking(
            session,
            path=path_b1,
            exam=exam,
            exam_template=exam_template,
            omr_template_id=omr_template_id,
            uploader=uploader,
            scan_status="completed",
            marking_status="needs_review",
            detected_marks=marks,
            batch_id=batch_b,
            batch_index=0,
        )
        created += 1

    # B-2: multiple answers bubbled on several questions (erased improperly)
    path_b2 = f"{base}/batch_b/scan_002.pdf"
    if not await scan_already_exists(session, path_b2):
        question_marks: list[OMRDetectedMark] = []
        for q in range(1, exam_template.total_questions + 1):
            # Questions 3, 6, 9 have double-bubbles, ambiguous
            if q in (3, 6, 9):
                question_marks.append(OMRDetectedMark(
                    marking_id=None,
                    field_type=MarkFieldType.QUESTION,
                    field_index=q,
                    detected_value="B",
                    confidence_score=0.51,
                    needs_review=True,
                ))
            else:
                question_marks.append(OMRDetectedMark(
                    marking_id=None,
                    field_type=MarkFieldType.QUESTION,
                    field_index=q,
                    detected_value=_ANSWER_CYCLE[q % 4],
                    confidence_score=0.95,
                    needs_review=False,
                ))
        marks = [
            _version_mark(None, "C"),
            *_student_id_marks(None, "99887766"),
            *_name_marks(None, "Alex", "Brown"),
            *question_marks,
        ]
        await create_scan_with_marking(
            session,
            path=path_b2,
            exam=exam,
            exam_template=exam_template,
            omr_template_id=omr_template_id,
            uploader=uploader,
            scan_status="completed",
            marking_status="needs_review",
            detected_marks=marks,
            batch_id=batch_b,
            batch_index=1,
        )
        created += 1

    # B-3: exam version bubble not clearly detected
    path_b3 = f"{base}/batch_b/scan_003.pdf"
    if not await scan_already_exists(session, path_b3):
        marks = [
            # Version unreadable
            OMRDetectedMark(
                marking_id=None,
                field_type=MarkFieldType.VERSION,
                field_index=0,
                detected_value=None,
                confidence_score=0.29,
                needs_review=True,
            ),
            *_student_id_marks(None, "55443322"),
            *_name_marks(None, "Sam", "Taylor"),
            *_question_marks(None, _question_answers(exam_template.total_questions, offset=1)),
        ]
        await create_scan_with_marking(
            session,
            path=path_b3,
            exam=exam,
            exam_template=exam_template,
            omr_template_id=omr_template_id,
            uploader=uploader,
            scan_status="completed",
            marking_status="needs_review",
            detected_marks=marks,
            batch_id=batch_b,
            batch_index=2,
        )
        created += 1

    # --- Batch C: failed scans ---
    batch_c = uuid.uuid4()

    # C-1: OMR preprocessing failed entirely (e.g. blurry/upside-down page)
    path_c1 = f"{base}/batch_c/scan_001.pdf"
    if not await scan_already_exists(session, path_c1):
        await create_scan_with_marking(
            session,
            path=path_c1,
            exam=exam,
            exam_template=exam_template,
            omr_template_id=omr_template_id,
            uploader=uploader,
            scan_status="failed",
            marking_status="failed",
            detected_marks=None,
            batch_id=batch_c,
            batch_index=0,
        )
        created += 1

    # C-2: scan uploaded OK but marking step failed (e.g. wrong template applied)
    path_c2 = f"{base}/batch_c/scan_002.pdf"
    if not await scan_already_exists(session, path_c2):
        await create_scan_with_marking(
            session,
            path=path_c2,
            exam=exam,
            exam_template=exam_template,
            omr_template_id=omr_template_id,
            uploader=uploader,
            scan_status="completed",
            marking_status="failed",
            detected_marks=None,
            batch_id=batch_c,
            batch_index=1,
        )
        created += 1

    # C-3: blank / empty page submitted
    path_c3 = f"{base}/batch_c/scan_003.pdf"
    if not await scan_already_exists(session, path_c3):
        await create_scan_with_marking(
            session,
            path=path_c3,
            exam=exam,
            exam_template=exam_template,
            omr_template_id=omr_template_id,
            uploader=uploader,
            scan_status="failed",
            marking_status="failed",
            detected_marks=None,
            batch_id=batch_c,
            batch_index=2,
        )
        created += 1

    return created


# ---------------------------------------------------------------------------
# Statistics showcase
# ---------------------------------------------------------------------------


def _statistics_showcase_answers(
    total_questions: int,
    *,
    version_index: int,
    student_rank: int,
) -> list[str]:
    """Build deterministic responses that exercise the statistics UI.

    Each version has six students ordered from strongest to weakest. The
    first five questions deliberately produce an easy item, a very difficult
    item, negative discrimination, healthy discrimination, and weak
    distractors. The remaining questions create a broad score distribution,
    with later versions becoming progressively harder.
    """
    answers: list[str] = []
    for question_number in range(1, total_questions + 1):
        correct_index = (question_number - 1 + version_index) % len(MC5CHOICES)
        correct_choice = MC5CHOICES[correct_index]

        if question_number == 1:
            is_correct = True
        elif question_number == 2:
            is_correct = student_rank == 0
        elif question_number == 3:
            # Only the lowest-performing group gets this right, producing a
            # negative discrimination warning without distorting rankings.
            is_correct = student_rank >= 4
        elif question_number in (4, 5):
            is_correct = student_rank < 3
        else:
            correct_cutoff = max(1, 6 - (question_number % 4) - version_index)
            is_correct = student_rank < correct_cutoff

        if is_correct:
            answers.append(correct_choice)
            continue

        if question_number == 5:
            # Route every incorrect response to one option so the other
            # distractors are visibly unused and efficiency is low.
            wrong_offset = 1
        else:
            wrong_offset = 1 + ((student_rank + question_number) % 4)
        answers.append(MC5CHOICES[(correct_index + wrong_offset) % len(MC5CHOICES)])

    return answers


async def seed_statistics_showcase(
    session: AsyncSession,
    *,
    exam: Exam,
    exam_template: ExamTemplate,
    uploader: User,
    students: list[User],
) -> int:
    """Create 18 clean grades across three versions for visual stats testing."""
    created = 0
    batch_id = uuid.uuid4()
    versions = list(string.ascii_uppercase[: exam_template.n_versions])
    if len(versions) != 3 or len(students) != 18:
        raise ValueError("Statistics showcase requires 18 students and 3 versions")
    if exam_template.omr_template_id is None:
        raise ValueError("Statistics showcase template must be registered before seeding")

    for index, student in enumerate(students):
        version_index = index % len(versions)
        version = versions[version_index]
        student_rank = index // len(versions)
        path = f"seed/{exam.id}/statistics_showcase/scan_{index + 1:03d}.pdf"
        if await scan_already_exists(session, path):
            continue

        answers = _statistics_showcase_answers(
            exam_template.total_questions,
            version_index=version_index,
            student_rank=student_rank,
        )
        marks = [
            _version_mark(None, version),
            *_student_id_marks(None, student.student_number),
            *_name_marks(None, student.first_name, student.last_name),
            *_question_marks(None, answers),
        ]
        marking = await create_scan_with_marking(
            session,
            path=path,
            exam=exam,
            exam_template=exam_template,
            omr_template_id=exam_template.omr_template_id,
            uploader=uploader,
            scan_status="completed",
            marking_status="completed",
            detected_marks=marks,
            batch_id=batch_id,
            batch_index=index,
        )
        await grade_marking(session, marking.id)
        created += 1

    return created


# ---------------------------------------------------------------------------
# Re-grade (review) requests
# ---------------------------------------------------------------------------


async def release_exam_for_seed(session: AsyncSession, exam: Exam, actor: User) -> bool:
    """Releases `exam` through the real release_exam service, so seed data
    goes through the exact same get_release_blockers() check a professor
    would hit in the UI -- an exam with any pending/failed scans or
    needs_review grades simply can't be released, seed script or not.
    Callers must make sure the exam actually reaches "Graded" first (e.g. by
    seeding it via seed_scans(..., include_flagged_and_failed=False))."""
    if exam.released:
        return False
    try:
        await release_exam(session, exam.id, actor)
    except ConflictError:
        return False
    return True


async def collect_graded_students(
    session: AsyncSession, exam: Exam, students: list[User]
) -> list[tuple[ExamGrade, User]]:
    """Pairs up each cleanly-graded ExamGrade for `exam` with the student it
    was matched to, so seed_review_requests has something real to attach
    sample re-grade requests to."""
    grades = await list_grades_by_exam(session, exam.id)
    student_by_id = {student.id: student for student in students}
    return [
        (grade, student_by_id[grade.student_id])
        for grade in grades
        if grade.student_id in student_by_id
    ]


async def review_request_already_exists(
    session: AsyncSession, exam_grade_id: uuid.UUID, question_number: str
) -> bool:
    existing = await list_by_grade(session, exam_grade_id)
    return any(r.question_number == question_number for r in existing)


# Each entry: (days_ago, question_number, student_comment, status,
# instructor_response, proposed_correct). days_ago is spread out so the
# dashboard's re-grade-volume-by-weekday chart has more than one bar filled.
# proposed_correct is the staff decision on resolve (None for pending/
# rejected, since those never touch the grade's question_results).
REVIEW_REQUEST_SCENARIOS = [
    (1, "3", "I think my answer for Q3 was marked wrong, my bubble looks clearly on B.", "pending", None, None),
    (2, "7", "Can you double check question 7? I filled in C but it's marked incorrect.", "pending", None, None),
    (3, "8", "Question 8 seems to have two acceptable answers based on the lecture slides.", "resolved", "Reviewed, awarded credit for both accepted answers.", True),
    (5, "1", "My name may have been misspelled, which could explain this grade.", "rejected", "Verified against the roster, the grade is correctly assigned.", None),
    (6, "9", "I believe question 9 was graded against the wrong answer key version.", "pending", None, None),
    (8, "10", "Requesting a manual look at question 10, the OMR may have misread my mark.", "resolved", "Confirmed a misread, my answer matched the key.", True),
]


async def seed_review_requests(
    session: AsyncSession, graded_pairs: list[tuple[ExamGrade, User]], professor: User
) -> int:
    """Creates review requests directly (rather than via
    repositories.review_requests.create_review_request) so created_at/status/
    resolved_at can be backdated and varied, instead of every seeded request
    landing as "pending" at the moment the script runs.

    A "resolved" scenario also updates the grade's question_results and
    total_score, and writes the same grade_audit_entries /
    review_request_audit_entries rows repositories.review_requests would, so
    seeded resolved/rejected requests show a real decision history instead of
    an empty one.
    """
    created = 0
    now = datetime.now(timezone.utc)

    for i, (grade, student) in enumerate(graded_pairs):
        if i >= len(REVIEW_REQUEST_SCENARIOS):
            break
        days_ago, question_number, comment, status, response, proposed_correct = REVIEW_REQUEST_SCENARIOS[i]
        if await review_request_already_exists(session, grade.id, question_number):
            continue

        current_result = grade.question_results.get(question_number)
        current_score = current_result["score"] if current_result else None
        proposed_score = None
        created_at = now - timedelta(days=days_ago, hours=i)
        resolved_at = created_at + timedelta(hours=6) if status != "pending" else None

        if status == "resolved" and current_result is not None and proposed_correct is not None:
            previous_total_score = grade.total_score
            proposed_score = current_result["max_score"] if proposed_correct else 0.0
            updated_result = {
                **current_result,
                "correct": proposed_correct,
                "score": proposed_score,
                "ambiguous": False,
            }
            question_results = dict(grade.question_results)
            question_results[question_number] = updated_result
            grade.question_results = question_results
            grade.total_score = round(sum(r["score"] for r in question_results.values()), 4)

            session.add(GradeAuditEntry(
                exam_grade_id=grade.id,
                actor_user_id=professor.id,
                event_type="manual_correction",
                previous_total_score=previous_total_score,
                new_total_score=grade.total_score,
                changes={
                    "questions": {question_number: {"before": current_result, "after": updated_result}},
                    "total_score": {"before": previous_total_score, "after": grade.total_score},
                    "source": {"before": None, "after": "review_request_resolution"},
                },
                created_at=resolved_at,
            ))

        review = ReviewRequest(
            id=uuid.uuid4(),
            exam_grade_id=grade.id,
            student_id=student.id,
            question_number=question_number,
            student_comment=comment,
            status=status,
            instructor_response=response,
            current_score=current_score,
            proposed_score=proposed_score,
            proposed_correct=proposed_correct,
            created_at=created_at,
            resolved_at=resolved_at,
        )
        session.add(review)

        if status != "pending":
            changes: dict = {
                "status": {"before": "pending", "after": status},
                "instructor_response": {"before": None, "after": response},
            }
            if proposed_correct is not None:
                changes["proposed_correct"] = {"before": None, "after": proposed_correct}
            session.add(ReviewRequestAuditEntry(
                review_request_id=review.id,
                actor_user_id=professor.id,
                event_type=status,
                changes=changes,
                created_at=resolved_at,
            ))

        created += 1

    return created


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def seed() -> None:
    """Populate local data without sending externally visible email."""
    original_resend_api_key = settings.resend_api_key
    settings.resend_api_key = None
    try:
        await _seed()
    finally:
        settings.resend_api_key = original_resend_api_key


async def _seed() -> None:
    # No outer session.begin(): generate_template_pdf/finalize_exam_template/
    # create_new_answer_key each commit their own unit of work, same as they
    # would through a normal request. A final commit below covers whatever
    # was only flushed (users, courses, enrolments, exams, scans).
    async with Session() as session:
        print("=== Seeding database ===")
        print("Complete dataset: realistic scans + analytics + scale course")
        print()

        # --- Users ---
        print("Users:")
        user_map: dict[str, User] = {}
        for data in USERS:
            user, created = await get_or_create_user(session, data)
            user_map[data["email"]] = user
            tag = "[+]" if created else "[=]"
            sn = f"  ID: {user.student_number}" if user.student_number else ""
            print(f"  {tag} {user.full_name} ({user.email}){sn} — {'created' if created else 'exists'}")

        # Summarized rather than one line per student -- 200 lines of
        # per-user output would swamp the rest of the seed log.
        created_count = 0
        for data in SCALE_USERS:
            user, created = await get_or_create_user(session, data)
            user_map[data["email"]] = user
            created_count += created
        print(
            f"  [+] {created_count} scale student(s) created, "
            f"{len(SCALE_USERS) - created_count} already existed"
        )

        professor = user_map["test.prof@example.com"]
        # The messy/unreleased Midterm's cohort -- also the 3 students with
        # physically hand-filled bubble sheets (see EXAM_TEMPLATES), so this
        # exact trio stays the Midterm's scan cohort.
        students = [
            user_map["joe.blow@example.com"],
            user_map["joe.mama@example.com"],
            user_map["joe.shmoe@example.com"],
        ]
        # Widened cohort for the released Final Exam, so all 6
        # REVIEW_REQUEST_SCENARIOS actually get exercised (graded_pairs needs
        # at least 6 students) instead of only the first 2-3.
        released_students = students + [
            user_map["alice.chen@example.com"],
            user_map["maria.garcia@example.com"],
            user_map["wei.zhang@example.com"],
            user_map["taylor.morgan@example.com"],
            user_map["jordan.lee@example.com"],
        ]
        stats_showcase_students = [
            user_map[student["email"]] for student in STATS_SHOWCASE_STUDENTS
        ]

        # --- Retention policy ---
        print("\nRetention Policy:")
        retention_policy, created = await get_or_create_retention_policy(
            session,
            professor,
        )
        tag = "[+]" if created else "[=]"
        print(
            f"  {tag} {professor.full_name}: "
            f"scans={retention_policy.scanned_image_retention_months} months, "
            f"exam records={retention_policy.exam_record_retention_months} months, "
            f"anonymous analytics={'kept' if retention_policy.retain_anonymized_analytics else 'removed'} "
            f"— {'created' if created else 'exists'}"
        )

        # --- Exam templates (metadata only — generated/registered below) ---
        print("\nExam Templates:")
        template_map: dict[str, ExamTemplate] = {}
        for tdata in EXAM_TEMPLATES + SCALE_EXAM_TEMPLATES:
            tmpl, created = await get_or_create_exam_template(session, tdata, professor)
            template_map[tdata["name"]] = tmpl
            tag = "[+]" if created else "[=]"
            print(f"  {tag} '{tmpl.name}'  ({tmpl.total_questions}q, {tmpl.n_versions} versions) — {'created' if created else 'exists'}")

        # --- Courses, enrolments, exams ---
        messy_midterm: Exam | None = None
        messy_midterm_template: ExamTemplate | None = None
        messy_midterm_course: Course | None = None
        released_final: Exam | None = None
        released_final_template: ExamTemplate | None = None
        released_final_course: Course | None = None
        stats_showcase_exam: Exam | None = None
        stats_showcase_template: ExamTemplate | None = None
        historical_midterms: list[tuple[Exam, ExamTemplate]] = []
        retention_demo_exam: tuple[Exam, ExamTemplate] | None = None
        all_exams: list[tuple[Exam, ExamTemplate]] = []
        courses_to_archive: list[tuple[Course, datetime]] = []

        courses_to_seed = COURSES + [build_scale_course_def()]
        for course_def in courses_to_seed:
            year_label = f", {course_def['academic_year_start']}" if course_def.get("historical") else ""
            print(f"\nCourse: {course_def['name']} ({course_def['term_name']}{year_label})")
            prof = user_map[course_def["professor_email"]]
            course, created = await get_or_create_course(
                session,
                course_def["name"],
                course_def["term_name"],
                prof.id,
                course_def.get("academic_year_start", datetime.now(timezone.utc).year),
                None,
                None,
            )
            tag = "[+]" if created else "[=]"
            print(f"  {tag} '{course.name}' ({course.academic_term.name})  invite={course.invite_link} — {'created' if created else 'exists'}")

            archived_at = course_def.get("archived_at")
            if archived_at is not None and course.archived_at is None:
                courses_to_archive.append((course, archived_at))
            if course.retention_processed_at is not None:
                print("  [=] retention already processed; archived student records left removed")
                continue

            print("  Enrolments:")
            # The scale course has ~200 enrolments -- summarize instead of one
            # line per student, same reasoning as the Users section above.
            summarize = course_def.get("summarize_enrolments", False)
            enrolled_count = 0
            for email, role in course_def["enrolments"]:
                user = user_map.get(email)
                if not user:
                    continue
                if role == "student":
                    enrolled = await get_or_create_roster_entry(session, user, course, prof)
                else:
                    enrolled = await get_or_create_enrolment(session, user, course, role)
                enrolled_count += enrolled
                if not summarize:
                    tag = "[+]" if enrolled else "[=]"
                    print(f"    {tag} {user.full_name} as {role} — {'enrolled' if enrolled else 'exists'}")
            if summarize:
                print(f"    [+] {enrolled_count} newly enrolled, {len(course_def['enrolments']) - enrolled_count} already existed")

            print("  Exams:")
            for exam_def in course_def["exams"]:
                tmpl = template_map.get(exam_def.get("template_name", ""))
                exam, created = await get_or_create_exam(
                    session,
                    name=exam_def["name"],
                    description=exam_def["description"],
                    course=course,
                    professor=prof,
                    template=tmpl,
                    start_offset_days=exam_def["start_offset_days"],
                    duration_hours=exam_def["duration_hours"],
                )
                tag = "[+]" if created else "[=]"
                tmpl_label = f"  template='{exam_def.get('template_name')}'" if tmpl else ""
                print(f"    {tag} '{exam_def['name']}'{tmpl_label} — {'created' if created else 'exists'}")

                if tmpl and exam_def.get("seed_answer_keys", True):
                    all_exams.append((exam, tmpl))
                elif tmpl:
                    print("      [=] answer key intentionally left undefined")

                # Capture the exams that need scan/re-grade-request seeding.
                # Matching by exam name plus historical/current is
                # unambiguous since exam names are unique per course and only
                # one non-historical course of each kind exists. The scale
                # course's exams need no capturing here because they
                # deliberately receive no seeded scans.
                if not course_def.get("historical"):
                    if exam_def["name"] == "Midterm Exam":
                        messy_midterm = exam
                        messy_midterm_template = tmpl
                        messy_midterm_course = course
                    elif exam_def["name"] == "Final Exam":
                        released_final = exam
                        released_final_template = tmpl
                        released_final_course = course
                    elif exam_def["name"] == "Database Systems Final Exam":
                        stats_showcase_exam = exam
                        stats_showcase_template = tmpl
                elif exam_def["name"] == "Midterm Exam" and tmpl:
                    historical_midterms.append((exam, tmpl))
                if course_def.get("retention_demo") and tmpl:
                    retention_demo_exam = (exam, tmpl)

        # --- Answer keys ---
        print("\nAnswer Keys:")
        for exam, tmpl in all_exams:
            n = await seed_answer_keys_for_exam(session, exam, tmpl)
            tag = "[+]" if n else "[=]"
            print(f"  {tag} '{exam.name}' ({tmpl.name}) — {n} version(s) created" if n else f"  {tag} '{exam.name}' ({tmpl.name}) — exist")

        # --- Register templates with the OMR service (generate PDF + finalize) ---
        # This is the exact flow the frontend uses, so every seeded template is
        # a genuine drop-in replacement for one built through the UI.
        print("\nOMR Template Registration:")
        for tmpl in template_map.values():
            registered = await ensure_template_registered(session, tmpl)
            tag = "[+]" if registered else "[=]"
            print(f"  {tag} '{tmpl.name}' — {'registered with OMR service' if registered else 'already registered'}")

        # --- Scans ---
        graded_pairs: list[tuple[ExamGrade, User]] = []

        # Midterm Exam keeps the full messy pipeline (needs_review + failed
        # scans included) so it stays UNRELEASED -- Batch B/C mean it can
        # never reach "Graded", and get_release_blockers() would reject
        # release() the same way it would for a real professor. This is the
        # demo exam for Processing/ScanFailed/needs-review states, and the
        # exam the 3 physical bubble sheets (see EXAM_TEMPLATES) target.
        if messy_midterm and messy_midterm_template:
            print("\nScans (Midterm Exam):")
            n = await seed_scans(
                session,
                exam=messy_midterm,
                exam_template=messy_midterm_template,
                omr_template_id=messy_midterm_template.omr_template_id,
                uploader=professor,
                students=students,
                real_scans=True,
                course=messy_midterm_course,
            )
            if n:
                print(f"  [+] {n} scan(s) created")
                print("       Batch A (3) — completed, one per student (Joe Blow/Mama/Shmoe); Joe Blow's Q1 double-bubbled (ambiguous)")
                print("       Batch B (3) — needs_review: ambiguous ID, double-bubble, missing version")
                print("       Batch C (3) — failed: blurry page, marking error, blank page")
                print("  [=] left unreleased — Batch B/C block release, same as a real exam would")
            else:
                print("  [=] scans already exist")

        # Final Exam is clean-scans-only (no ambiguous marks, no
        # needs_review/failed scans) so it reaches a genuinely unblemished
        # "Graded" state and can be released for real -- the demo exam for
        # released/regrade-badge states, once the professor has already
        # addressed everything Batch A/B/C would have raised. Cohort is
        # widened to 8 students: six exercise every seeded review-request
        # scenario, while Taylor and Jordan remain clean for separate video
        # and live-presentation student flows.
        if released_final and released_final_template:
            print("\nScans (Final Exam):")
            n = await seed_scans(
                session,
                exam=released_final,
                exam_template=released_final_template,
                omr_template_id=released_final_template.omr_template_id,
                uploader=professor,
                students=released_students,
                include_flagged_and_failed=False,
                real_scans=True,
                course=released_final_course,
            )
            if n:
                print(f"  [+] {n} scan(s) created")
                print("       Batch A (8) — completed and cleanly matched, one per student; no ambiguous marks")
            else:
                print("  [=] scans already exist")

            released = await release_exam_for_seed(session, released_final, professor)
            print(f"  {'[+]' if released else '[=]'} exam {'released' if released else 'already released'}")
            graded_pairs += await collect_graded_students(
                session,
                released_final,
                released_students[: len(REVIEW_REQUEST_SCENARIOS)],
            )

        # The scale course deliberately seeds no scans. Every student shows as
        # not submitted, so the generated presentation upload stands out in
        # the grade sheet. The roster still exercises pagination and search.

        # A larger, intentionally varied data set for manually checking every
        # overview, question, warning, tooltip, and version-comparison state.
        if stats_showcase_exam and stats_showcase_template:
            print("\nScans (Database Systems Final Exam):")
            n = await seed_statistics_showcase(
                session,
                exam=stats_showcase_exam,
                exam_template=stats_showcase_template,
                uploader=professor,
                students=stats_showcase_students,
            )
            if n:
                print(f"  [+] {n} clean scan(s) created across versions A, B, and C")
                print(
                    "       24 questions with easy, difficult, "
                    "negative-discrimination, and weak-distractor scenarios"
                )
            else:
                print("  [=] statistics showcase scans already exist")

        # Historical offerings of the same course provide archived, graded
        # data for the course comparison UI. Cohort sizes differ per year so
        # the historical averages and sample counts are visibly distinct.
        # Always fabricated (never real_scans): nobody inspects an archived
        # scan file from a past term, only its aggregate grade, so
        # routing these through the real render/OMR pipeline would only slow
        # down the consolidated seed for no additional test coverage.
        historical_cohort_sizes = [6, 4]
        for index, (historical_midterm, historical_template) in enumerate(historical_midterms):
            historical_students = released_students[: historical_cohort_sizes[index]]
            print(f"\nScans (Archived Historical Midterm {index + 1}):")
            n = await seed_scans(
                session,
                exam=historical_midterm,
                exam_template=historical_template,
                omr_template_id=historical_template.omr_template_id,
                uploader=professor,
                students=historical_students,
                include_flagged_and_failed=False,
                real_scans=False,
            )
            if n:
                print(f"  [+] {n} clean historical scan(s) created for performance comparison")
            else:
                print("  [=] historical scans already exist")

        if retention_demo_exam:
            demo_exam, demo_template = retention_demo_exam
            print("\nScans (Overdue Retention Cleanup Demo):")
            n = await seed_scans(
                session,
                exam=demo_exam,
                exam_template=demo_template,
                omr_template_id=demo_template.omr_template_id,
                uploader=professor,
                students=students[:1],
                include_flagged_and_failed=False,
            )
            if n:
                print(f"  [+] {n} cleanup-demo scan(s) created")
            else:
                print("  [=] cleanup-demo scan already exists")

        # --- Re-grade (review) requests, spread across both courses/days/statuses ---
        if graded_pairs:
            print("\nRe-grade Requests:")
            n = await seed_review_requests(session, graded_pairs, professor)
            if n:
                print(f"  [+] {n} review request(s) created (mix of pending/resolved/rejected)")
            else:
                print("  [=] review requests already exist")

        if courses_to_archive:
            print("\nArchived Courses:")
            for course, archived_at in courses_to_archive:
                _apply_archive_retention(
                    course,
                    archived_at=archived_at,
                    archived_by_user_id=course.created_by,
                    retention_policy=retention_policy,
                )
                print(
                    f"  [+] '{course.name}' archived {archived_at.date()}; "
                    f"retention due {course.exam_records_retention_until.date()}"
                )

        await session.commit()

    scale_note = (
        f"\nScale course: 'COSC 499 - Capstone Project', ~{SCALE_STUDENT_COUNT} students, "
        "no scans seeded (intentional -- run `make presentation-data` for the "
        "default and mixed upload batches)\n"
    )
    print(f"""
=== Done ===

Default password for all accounts: {DEFAULT_PASSWORD!r}

Logins:
  admin@example.com         (admin)
  test.prof@example.com     (professor, course owner)
  empty.prof@example.com    (professor, empty presentation account)
  test.coprof@example.com   (professor, promoted co-professor)
  taylor.morgan@example.com (student, released result; no review request)
  jordan.lee@example.com    (student, released result; no review request)
  joe.blow@example.com      (student  ID: 12345678)
  joe.mama@example.com      (student  ID: 67676767)
  joe.shmoe@example.com     (student  ID: 11111111)
{scale_note}""")


if __name__ == "__main__":
    asyncio.run(seed())
