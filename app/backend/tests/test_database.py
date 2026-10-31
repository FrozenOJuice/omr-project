import pytest
from sqlalchemy import text, select
import uuid
from models.user import User
from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.enrolment import Enrolment

pytestmark = pytest.mark.db


@pytest.mark.asyncio
async def test_db_connects(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_tables_exist(db_session):
    result = await db_session.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """))
    tables = [row[0] for row in result.fetchall()]

    expected = [
        "users", "courses", "academic_terms", "enrolments", "exams",
        "exam_templates", "scans", "omr_templates",
        "omr_markings", "omr_detected_marks",
        "exam_grades", "review_requests", "site_branding"
    ]

    for table in expected:
        assert table in tables, f"Missing table: {table}"


@pytest.mark.asyncio
async def test_academic_term_migration_seeds_presets_and_course_constraint(db_session):
    presets = await db_session.execute(text("""
        SELECT institution, count(*)
        FROM academic_terms
        WHERE term_type = 'preset' AND is_active = true
        GROUP BY institution
    """))
    assert dict(presets.all()) == {"ubc": 6, "generic": 1}

    column = await db_session.execute(text("""
        SELECT is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'courses'
          AND column_name = 'academic_term_id'
    """))
    is_nullable, column_default = column.one()
    assert is_nullable == "NO"
    assert column_default is None

    removed_semester = await db_session.execute(text("""
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'courses'
          AND column_name = 'semester'
    """))
    assert removed_semester.scalar_one() == 0

    foreign_key = await db_session.execute(text("""
        SELECT count(*)
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'courses'
          AND constraint_name = 'fk_courses_academic_term_id_academic_terms'
          AND constraint_type = 'FOREIGN KEY'
    """))
    assert foreign_key.scalar_one() == 1


@pytest.mark.asyncio
async def test_create_user(db_session):
    user = User(
        email="test@test.com",
        first_name="Test",
        last_name="User",
        password_hash="hashed_password",
        role="student"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    result = await db_session.execute(
        select(User).where(User.email == "test@test.com")
    )
    fetched = result.scalar_one()

    assert fetched.email == "test@test.com"
    assert fetched.role == "student"
    assert fetched.id is not None
    assert fetched.created_at is not None


@pytest.mark.asyncio
async def test_create_course(db_session):
    instructor = User(
        email="instructor@test.com",
        first_name="Instructor",
        last_name="One",
        password_hash="hash",
        role="professor"
    )
    db_session.add(instructor)
    await db_session.commit()
    await db_session.refresh(instructor)

    course = Course(
        name="CPSC 101",
        academic_term_id=UBC_WINTER_SESSION_1_TERM_ID,
        created_by=instructor.id
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)

    result = await db_session.execute(
        select(Course).where(Course.name == "CPSC 101")
    )
    fetched = result.scalar_one()

    assert fetched.name == "CPSC 101"
    assert fetched.academic_term_id == UBC_WINTER_SESSION_1_TERM_ID
    assert fetched.id is not None


@pytest.mark.asyncio
async def test_enrolment_foreign_key(db_session):
    instructor = User(
        email="instructor@test.com",
        first_name="Instructor",
        last_name="One",
        password_hash="hash",
        role="professor"
    )
    user = User(
        email="student@test.com",
        first_name="Student",
        last_name="One",
        password_hash="hash",
        role="student"
    )
    db_session.add_all([instructor, user])
    await db_session.commit()
    await db_session.refresh(instructor)
    await db_session.refresh(user)

    course = Course(name="CPSC 201", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=instructor.id)
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)

    enrolment = Enrolment(
        user_id=user.id,
        course_id=course.id,
        role="student"
    )
    db_session.add(enrolment)
    await db_session.commit()
    await db_session.refresh(enrolment)

    assert enrolment.id is not None
    assert enrolment.user_id == user.id
    assert enrolment.course_id == course.id


@pytest.mark.asyncio
async def test_invalid_foreign_key_fails(db_session):
    from sqlalchemy.exc import IntegrityError

    enrolment = Enrolment(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        role="student"
    )
    db_session.add(enrolment)

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_user_email_unique(db_session):
    from sqlalchemy.exc import IntegrityError

    user1 = User(email="same@test.com", first_name="User", last_name="One", password_hash="hash", role="student")
    user2 = User(email="same@test.com", first_name="User", last_name="Two", password_hash="hash", role="student")

    db_session.add(user1)
    await db_session.commit()

    db_session.add(user2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
