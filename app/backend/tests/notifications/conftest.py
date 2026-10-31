import uuid

import pytest

from core.security import hash_password
from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.enrolment import Enrolment
from models.user import User, UserRole


@pytest.fixture
def make_user(db_session):
    async def _make_user(role: UserRole = UserRole.STUDENT):
        user = User(
            first_name="Test",
            last_name="User",
            email=f"user_{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("Password123!"),
            role=role.value,
            status="active",
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _make_user


@pytest.fixture
def make_course(db_session, make_user):
    async def _make_course(created_by=None):
        if created_by is None:
            created_by = await make_user(UserRole.PROFESSOR)
        course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=created_by.id)
        db_session.add(course)
        await db_session.flush()
        return course, created_by

    return _make_course


@pytest.fixture
def enrol(db_session):
    async def _enrol(user, course, role: str):
        enrolment = Enrolment(user_id=user.id, course_id=course.id, role=role)
        db_session.add(enrolment)
        await db_session.flush()
        return enrolment

    return _enrol
