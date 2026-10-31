from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.canvas_connection import CanvasConnection
from models.course import Course
from models.user import User, UserRole
from repositories import canvas_course_links

pytestmark = pytest.mark.db


async def create_linked_course(
    authenticated_client,
    db_session,
    *,
    email: str,
    canvas_course_id: str = "42",
):
    client, token = await authenticated_client(email=email)
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/api/courses",
        json={"name": "CANVAS 101 - Imported Course", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
        headers=headers,
    )
    course = await db_session.get(Course, created.json()["id"])
    user = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    connection = CanvasConnection(
        user_id=user.id,
        access_token_encrypted="encrypted-access-token",
    )
    db_session.add(connection)
    await db_session.flush()
    link = await canvas_course_links.create(
        db_session,
        course=course,
        canvas_connection_id=connection.id,
        canvas_course_id=canvas_course_id,
        synced_at=datetime.now(timezone.utc),
    )
    await db_session.commit()
    return client, headers, course, connection, link


async def test_canvas_link_metadata_is_returned_with_an_omr_course(
    authenticated_client,
    db_session,
):
    client, headers, course, _, _ = await create_linked_course(
        authenticated_client,
        db_session,
        email="canvas-course-owner@example.com",
    )

    detail = await client.get(f"/api/courses/{course.id}", headers=headers)
    listing = await client.get("/api/courses", headers=headers)

    assert detail.status_code == 200
    assert detail.json()["source"] == "canvas"
    assert detail.json()["can_manage_canvas"] is True
    assert detail.json()["canvas_link"] == {
        "canvas_course_id": "42",
        "last_synced_at": detail.json()["canvas_link"]["last_synced_at"],
        "connection_status": "connected",
    }
    listed = next(item for item in listing.json() if item["id"] == str(course.id))
    assert listed["source"] == "canvas"
    assert listed["canvas_link"]["canvas_course_id"] == "42"
    assert listed["can_manage_canvas"] is True


async def test_admin_cannot_manage_another_users_canvas_connection(
    authenticated_client,
    db_session,
):
    client, _, course, _, _ = await create_linked_course(
        authenticated_client,
        db_session,
        email="canvas-course-professor@example.com",
    )
    _, token = await authenticated_client(
        email="canvas-course-admin@example.com",
        role=UserRole.ADMIN,
    )
    headers = {"Authorization": f"Bearer {token}"}

    detail = await client.get(f"/api/courses/{course.id}", headers=headers)
    listing = await client.get("/api/courses", headers=headers)

    assert detail.status_code == 200
    assert detail.json()["can_manage_canvas"] is False
    listed = next(item for item in listing.json() if item["id"] == str(course.id))
    assert listed["can_manage_canvas"] is False


async def test_deleting_a_canvas_connection_preserves_the_omr_course(
    authenticated_client,
    db_session,
):
    client, headers, course, connection, link = await create_linked_course(
        authenticated_client,
        db_session,
        email="disconnected-course-owner@example.com",
    )

    await db_session.delete(connection)
    await db_session.commit()
    await db_session.refresh(link)

    response = await client.get(f"/api/courses/{course.id}", headers=headers)

    assert await db_session.get(Course, course.id) is not None
    assert link.canvas_connection_id is None
    assert response.status_code == 200
    assert response.json()["source"] == "canvas"
    assert response.json()["canvas_link"]["connection_status"] == "disconnected"


async def test_different_instructors_can_import_the_same_canvas_course(
    authenticated_client,
    db_session,
):
    _, _, first_course, _, _ = await create_linked_course(
        authenticated_client,
        db_session,
        email="first-canvas-owner@example.com",
        canvas_course_id="duplicate-course",
    )
    client, token = await authenticated_client(email="second-canvas-owner@example.com")
    created = await client.post(
        "/api/courses",
        json={"name": "Duplicate", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    course = await db_session.get(Course, created.json()["id"])
    user = (
        await db_session.execute(
            select(User).where(User.email == "second-canvas-owner@example.com")
        )
    ).scalar_one()
    connection = CanvasConnection(user_id=user.id)
    db_session.add(connection)
    await db_session.flush()

    link = await canvas_course_links.create(
        db_session,
        course=course,
        canvas_connection_id=connection.id,
        canvas_course_id="duplicate-course",
        synced_at=datetime.now(timezone.utc),
    )
    await db_session.commit()

    assert link.owner_user_id == user.id
    forbidden = await client.post(
        f"/api/canvas/imported-courses/{first_course.id}/roster/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "canvas_course_owner_required"


async def test_one_instructor_cannot_import_the_same_canvas_course_twice(
    authenticated_client,
    db_session,
):
    client, headers, _, connection, first_link = await create_linked_course(
        authenticated_client,
        db_session,
        email="canvas-owner@example.com",
        canvas_course_id="duplicate-course",
    )
    created = await client.post(
        "/api/courses",
        json={"name": "Duplicate", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
        headers=headers,
    )
    course = await db_session.get(Course, created.json()["id"])

    with pytest.raises(IntegrityError):
        await canvas_course_links.create(
            db_session,
            course=course,
            canvas_connection_id=connection.id,
            canvas_course_id=first_link.canvas_course_id,
            synced_at=datetime.now(timezone.utc),
        )
    await db_session.rollback()
