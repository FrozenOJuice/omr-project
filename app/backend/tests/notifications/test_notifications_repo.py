"""Integration tests for repositories/notifications.py."""
from datetime import datetime, timedelta, timezone
import uuid

import pytest

from repositories.notifications import count_unread, list_for_user, mark_all_read, mark_read
from services.notifications import notify_user

pytestmark = pytest.mark.db


class TestListForUser:
    async def test_only_returns_own_notifications(self, db_session, make_user):
        user = await make_user()
        other = await make_user()
        await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="Mine")
        await notify_user(db_session, recipient_user_id=other.id, type="grade_ready", title="Not mine")

        rows, total = await list_for_user(db_session, user.id, page=1, page_size=10)
        assert total == 1
        assert rows[0][0].title == "Mine"

    async def test_orders_newest_first(self, db_session, make_user):
        user = await make_user()
        # created_at has a server_default of now(); within a single fast test
        # transaction that can tie, so set it explicitly to make order deterministic.
        first = await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="First")
        second = await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="Second")
        first.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        second.created_at = datetime.now(timezone.utc)
        await db_session.commit()

        rows, _total = await list_for_user(db_session, user.id, page=1, page_size=10)
        assert [n.id for n, _ in rows] == [second.id, first.id]

    async def test_paginates(self, db_session, make_user):
        user = await make_user()
        for i in range(5):
            await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title=f"N{i}")

        page1, total = await list_for_user(db_session, user.id, page=1, page_size=2)
        page2, _ = await list_for_user(db_session, user.id, page=2, page_size=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {n.id for n, _ in page1}.isdisjoint({n.id for n, _ in page2})

    async def test_includes_course_label(self, db_session, make_user, make_course):
        user = await make_user()
        course, _prof = await make_course()
        await notify_user(
            db_session, recipient_user_id=user.id, type="grade_ready", title="Graded", course_id=course.id
        )

        rows, _total = await list_for_user(db_session, user.id, page=1, page_size=10)
        _notification, course_label = rows[0]
        assert course_label == course.name


class TestCountUnread:
    async def test_counts_only_unread(self, db_session, make_user):
        user = await make_user()
        n1 = await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="A")
        await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="B")
        await mark_read(db_session, n1.id, user.id)

        count = await count_unread(db_session, user.id)
        assert count == 1


class TestMarkRead:
    async def test_marks_owned_notification_read(self, db_session, make_user):
        user = await make_user()
        notification = await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="A")

        updated = await mark_read(db_session, notification.id, user.id)
        assert updated is not None
        assert updated.is_read is True

    async def test_returns_none_for_unowned_notification(self, db_session, make_user):
        owner = await make_user()
        other = await make_user()
        notification = await notify_user(db_session, recipient_user_id=owner.id, type="grade_ready", title="A")

        result = await mark_read(db_session, notification.id, other.id)
        assert result is None

    async def test_returns_none_for_nonexistent_notification(self, db_session, make_user):
        user = await make_user()
        result = await mark_read(db_session, uuid.uuid4(), user.id)
        assert result is None


class TestMarkAllRead:
    async def test_marks_all_unread_and_returns_count(self, db_session, make_user):
        user = await make_user()
        n1 = await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="A")
        await notify_user(db_session, recipient_user_id=user.id, type="grade_ready", title="B")
        await mark_read(db_session, n1.id, user.id)

        updated_count = await mark_all_read(db_session, user.id)
        assert updated_count == 1

        remaining_unread = await count_unread(db_session, user.id)
        assert remaining_unread == 0

    async def test_does_not_affect_other_users(self, db_session, make_user):
        user = await make_user()
        other = await make_user()
        await notify_user(db_session, recipient_user_id=other.id, type="grade_ready", title="A")

        updated_count = await mark_all_read(db_session, user.id)
        assert updated_count == 0
        assert await count_unread(db_session, other.id) == 1
