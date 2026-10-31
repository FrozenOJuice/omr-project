import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.settings import settings
from models.course import Course
from models.course_roster_entry import CourseRosterEntry
from models.enrolment import Enrolment
from models.user import User
from services.course_invites import join_url_for
from services.email_service import EmailDeliveryError


async def _create_course(client, token: str, db_session: AsyncSession) -> Course:
    response = await client.post(
        "/api/courses",
        json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_201_CREATED

    result = await db_session.execute(
        select(Course).where(Course.id == response.json()["id"])
    )
    course = result.scalar_one()
    assert course.invite_link
    assert course.invite_link_expires_at > datetime.now(timezone.utc)
    return course


async def _registered_student_token(register_user, email: str | None = None) -> str:
    response = await register_user(email=email or f"student_{uuid.uuid4().hex[:8]}@ubco.ca")
    assert response.status_code == status.HTTP_200_OK
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_authenticated_student_joins_via_link(
    authenticated_client,
    register_user,
    db_session: AsyncSession,
):
    client, professor_token = await authenticated_client()
    course = await _create_course(client, professor_token, db_session)
    student_email = f"student_{uuid.uuid4().hex[:8]}@ubco.ca"
    student_token = await _registered_student_token(register_user, student_email)

    response = await client.post(
        f"/api/students/join/{course.invite_link}",
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert "successfully joined" in response.json()["message"].lower()

    student = (
        await db_session.execute(select(User).where(User.email == student_email))
    ).scalar_one()
    enrolment = (
        await db_session.execute(
            select(Enrolment).where(
                Enrolment.course_id == course.id,
                Enrolment.user_id == student.id,
                Enrolment.role == "student",
            )
        )
    ).scalar_one_or_none()
    roster_entry = (
        await db_session.execute(
            select(CourseRosterEntry).where(
                CourseRosterEntry.course_id == course.id,
                CourseRosterEntry.user_id == student.id,
            )
        )
    ).scalar_one_or_none()
    assert enrolment is not None
    assert roster_entry is not None


@pytest.mark.asyncio
async def test_join_via_link_requires_authentication(
    authenticated_client,
    client: AsyncClient,
    db_session: AsyncSession,
):
    professor_client, professor_token = await authenticated_client()
    course = await _create_course(professor_client, professor_token, db_session)

    response = await client.post(f"/api/students/join/{course.invite_link}")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_join_via_link_uses_current_user_not_request_body(
    authenticated_client,
    register_user,
    db_session: AsyncSession,
):
    client, professor_token = await authenticated_client()
    course = await _create_course(client, professor_token, db_session)
    student_email = f"student_{uuid.uuid4().hex[:8]}@ubco.ca"
    student_token = await _registered_student_token(register_user, student_email)

    response = await client.post(
        f"/api/students/join/{course.invite_link}",
        headers={"Authorization": f"Bearer {student_token}"},
        json={
            "email": "other_student@ubco.ca",
            "first_name": "Other",
            "last_name": "Student",
            "student_number": "20000001",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED

    current_student = (
        await db_session.execute(select(User).where(User.email == student_email))
    ).scalar_one()
    body_user = (
        await db_session.execute(select(User).where(User.email == "other_student@ubco.ca"))
    ).scalar_one_or_none()
    enrolment = (
        await db_session.execute(
            select(Enrolment).where(
                Enrolment.course_id == course.id,
                Enrolment.user_id == current_student.id,
            )
        )
    ).scalar_one_or_none()

    assert enrolment is not None
    assert body_user is None


@pytest.mark.asyncio
async def test_join_via_link_is_idempotent(
    authenticated_client,
    register_user,
    db_session: AsyncSession,
):
    client, professor_token = await authenticated_client()
    course = await _create_course(client, professor_token, db_session)
    student_token = await _registered_student_token(register_user)
    headers = {"Authorization": f"Bearer {student_token}"}

    first_response = await client.post(f"/api/students/join/{course.invite_link}", headers=headers)
    second_response = await client.post(f"/api/students/join/{course.invite_link}", headers=headers)

    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_201_CREATED


@pytest.mark.asyncio
async def test_join_via_link_forbidden_for_professor(
    authenticated_client,
    db_session: AsyncSession,
):
    client, professor_token = await authenticated_client()
    course = await _create_course(client, professor_token, db_session)

    response = await client.post(
        f"/api/students/join/{course.invite_link}",
        headers={"Authorization": f"Bearer {professor_token}"},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_expired_invite_link_is_rejected(
    authenticated_client,
    register_user,
    db_session: AsyncSession,
):
    client, professor_token = await authenticated_client()
    course = await _create_course(client, professor_token, db_session)
    course.invite_link_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    student_token = await _registered_student_token(register_user)
    response = await client.post(
        f"/api/students/join/{course.invite_link}",
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "invalid_invite_link"


@pytest.mark.asyncio
async def test_regenerated_invite_link_invalidates_old_link(
    authenticated_client,
    register_user,
    db_session: AsyncSession,
):
    client, professor_token = await authenticated_client()
    professor_headers = {"Authorization": f"Bearer {professor_token}"}
    course = await _create_course(client, professor_token, db_session)
    old_link = course.invite_link
    course.invite_link_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    regenerate_response = await client.post(
        f"/api/courses/{course.id}/regenerate-link",
        headers=professor_headers,
    )
    assert regenerate_response.status_code == status.HTTP_200_OK
    new_link = regenerate_response.json()["invite_link"]
    new_expiry = datetime.fromisoformat(
        regenerate_response.json()["invite_link_expires_at"]
    )
    assert new_link != old_link
    assert new_expiry > datetime.now(timezone.utc)

    student_token = await _registered_student_token(register_user)
    student_headers = {"Authorization": f"Bearer {student_token}"}

    old_response = await client.post(f"/api/students/join/{old_link}", headers=student_headers)
    new_response = await client.post(f"/api/students/join/{new_link}", headers=student_headers)

    assert old_response.status_code == status.HTTP_404_NOT_FOUND
    assert new_response.status_code == status.HTTP_201_CREATED


@pytest.mark.asyncio
async def test_enroll_student_invalid_link(register_user, client: AsyncClient):
    student_token = await _registered_student_token(register_user)

    response = await client.post(
        "/api/students/join/fake-invalid-link-123",
        headers={"Authorization": f"Bearer {student_token}"},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "invalid_invite_link" in response.text


@pytest.mark.asyncio
async def test_join_via_link_idempotent_even_after_expiry(
    authenticated_client,
    register_user,
    db_session: AsyncSession,
):
    """An already-enrolled student re-opening an expired link is a no-op, not a 404."""
    client, professor_token = await authenticated_client()
    course = await _create_course(client, professor_token, db_session)
    student_token = await _registered_student_token(register_user)
    headers = {"Authorization": f"Bearer {student_token}"}

    first_response = await client.post(
        f"/api/students/join/{course.invite_link}", headers=headers
    )
    assert first_response.status_code == status.HTTP_201_CREATED

    course.invite_link_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    second_response = await client.post(
        f"/api/students/join/{course.invite_link}", headers=headers
    )
    assert second_response.status_code == status.HTTP_201_CREATED


def test_join_url_for_rejects_expired_link(monkeypatch):
    """An expired link must fail invite delivery instead of mailing a dead link."""
    monkeypatch.setattr(settings, "frontend_origin", "https://omr.example.com")
    course = SimpleNamespace(
        invite_link="abcd1234",
        invite_link_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(EmailDeliveryError, match="expired"):
        join_url_for(course)


def test_join_url_for_allows_active_link(monkeypatch):
    monkeypatch.setattr(settings, "frontend_origin", "https://omr.example.com")
    course = SimpleNamespace(
        invite_link="abcd1234",
        invite_link_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )

    assert join_url_for(course).endswith("/join/abcd1234")
