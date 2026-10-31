"""Integration tests for routers/notification_router.py."""
import pytest

from services.notifications import notify_user

pytestmark = pytest.mark.db


async def _get_user_id(get_user_by_email, email):
    user = await get_user_by_email(email)
    return user.id


class TestListNotifications:
    async def test_requires_auth(self, client):
        response = await client.get("/api/notifications")
        assert response.status_code == 401

    async def test_returns_own_notifications(
        self, db_session, authenticated_client, get_user_by_email
    ):
        email = "notify_list@example.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(get_user_by_email, email)
        await notify_user(db_session, recipient_user_id=user_id, type="grade_ready", title="Graded")
        await db_session.commit()

        response = await client.get(
            "/api/notifications", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "Graded"


class TestUnreadCount:
    async def test_returns_unread_count(
        self, db_session, authenticated_client, get_user_by_email
    ):
        email = "notify_unread@example.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(get_user_by_email, email)
        await notify_user(db_session, recipient_user_id=user_id, type="grade_ready", title="Graded")
        await db_session.commit()

        response = await client.get(
            "/api/notifications/unread-count", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["count"] == 1


class TestMarkRead:
    async def test_marks_notification_read(
        self, db_session, authenticated_client, get_user_by_email
    ):
        email = "notify_markread@example.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(get_user_by_email, email)
        notification = await notify_user(
            db_session, recipient_user_id=user_id, type="grade_ready", title="Graded"
        )
        await db_session.commit()

        response = await client.patch(
            f"/api/notifications/{notification.id}/read",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["is_read"] is True

    async def test_404_for_unowned_notification(
        self, db_session, authenticated_client, get_user_by_email, create_user
    ):
        owner = await create_user(email="notify_owner@example.com")
        notification = await notify_user(
            db_session, recipient_user_id=owner.id, type="grade_ready", title="Graded"
        )
        await db_session.commit()

        client, token = await authenticated_client(email="notify_other@example.com")
        response = await client.patch(
            f"/api/notifications/{notification.id}/read",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestMarkAllRead:
    async def test_marks_all_unread(self, db_session, authenticated_client, get_user_by_email):
        email = "notify_markall@example.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(get_user_by_email, email)
        await notify_user(db_session, recipient_user_id=user_id, type="grade_ready", title="A")
        await notify_user(db_session, recipient_user_id=user_id, type="grade_ready", title="B")
        await db_session.commit()

        response = await client.patch(
            "/api/notifications/read-all", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["updated"] == 2
