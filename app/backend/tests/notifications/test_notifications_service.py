"""Integration tests for services/notifications.py."""
from unittest.mock import AsyncMock

import pytest

from models.user import UserRole
from services import notifications
from services.notifications import notify_course_staff, notify_course_students, notify_user

pytestmark = pytest.mark.db


class TestNotifyUser:
    async def test_creates_notification(self, db_session, make_user):
        user = await make_user()
        notification = await notify_user(
            db_session,
            recipient_user_id=user.id,
            type="grade_ready",
            title="Your exam has been graded",
            body="Midterm",
            link_path="/courses",
            link_query="courseId=abc&examId=def",
        )
        assert notification.id is not None
        assert notification.recipient_user_id == user.id
        assert notification.type == "grade_ready"
        assert notification.is_read is False
        assert notification.link_path == "/courses"
        assert notification.link_query == "courseId=abc&examId=def"

    async def test_delivers_email_when_notification_preferences_allow_it(
        self, db_session, make_user, monkeypatch
    ):
        user = await make_user()
        monkeypatch.setattr(notifications.settings, "email_from", "OMR <no-reply@example.com>")
        monkeypatch.setattr(notifications.settings, "resend_api_key", "test-key")
        calls = []

        async def capture(email: str, **kwargs) -> None:
            calls.append((email, kwargs))

        monkeypatch.setattr(notifications, "send_notification_email", capture)

        notification = await notify_user(
            db_session,
            recipient_user_id=user.id,
            type="grade_ready",
            title="Grades posted",
        )

        assert calls == [
            (
                user.email,
                {
                    "notification_id": str(notification.id),
                    "notification_type": "grade_ready",
                    "title": "Grades posted",
                    "body": None,
                    "link_path": None,
                    "link_query": None,
                },
            )
        ]

    @pytest.mark.parametrize(
        ("notification_type", "disabled_preference"),
        [
            ("review_request_created", "regrade_alerts_enabled"),
            ("grade_ready", "batch_job_complete_enabled"),
        ],
    )
    async def test_skips_email_for_a_disabled_notification_category(
        self,
        db_session,
        make_user,
        monkeypatch,
        notification_type,
        disabled_preference,
    ):
        user = await make_user()
        setattr(user, disabled_preference, False)
        await db_session.commit()
        monkeypatch.setattr(notifications.settings, "email_from", "OMR <no-reply@example.com>")
        monkeypatch.setattr(notifications.settings, "resend_api_key", "test-key")
        send_email = AsyncMock()
        monkeypatch.setattr(notifications, "send_notification_email", send_email)

        await notify_user(
            db_session,
            recipient_user_id=user.id,
            type=notification_type,
            title="Notification",
        )

        send_email.assert_not_awaited()

    async def test_skips_email_when_email_notifications_are_disabled(
        self, db_session, make_user, monkeypatch
    ):
        user = await make_user()
        user.email_notifications_enabled = False
        await db_session.commit()
        monkeypatch.setattr(notifications.settings, "email_from", "OMR <no-reply@example.com>")
        monkeypatch.setattr(notifications.settings, "resend_api_key", "test-key")
        send_email = AsyncMock()
        monkeypatch.setattr(notifications, "send_notification_email", send_email)

        await notify_user(
            db_session,
            recipient_user_id=user.id,
            type="grade_ready",
            title="Notification",
        )

        send_email.assert_not_awaited()


class TestNotifyCourseStaff:
    async def test_notifies_course_creator_and_enrolled_staff(
        self, db_session, make_user, make_course, enrol
    ):
        course, prof = await make_course()
        co_prof = await make_user(UserRole.PROFESSOR)
        await enrol(co_prof, course, "professor")
        student = await make_user(UserRole.STUDENT)
        await enrol(student, course, "student")

        notifications = await notify_course_staff(
            db_session,
            course_id=course.id,
            type="grade_needs_review",
            title="A grade needs manual review",
        )

        recipients = {n.recipient_user_id for n in notifications}
        assert recipients == {prof.id, co_prof.id}

    async def test_excludes_given_user(self, db_session, make_user, make_course, enrol):
        course, prof = await make_course()
        co_prof = await make_user(UserRole.PROFESSOR)
        await enrol(co_prof, course, "professor")

        notifications = await notify_course_staff(
            db_session,
            course_id=course.id,
            type="review_request_created",
            title="New re-grade request",
            exclude_user_id=co_prof.id,
        )

        recipients = {n.recipient_user_id for n in notifications}
        assert recipients == {prof.id}

    async def test_no_duplicate_when_creator_is_also_enrolled(
        self, db_session, make_course, enrol
    ):
        course, prof = await make_course()
        await enrol(prof, course, "professor")

        notifications = await notify_course_staff(
            db_session, course_id=course.id, type="grade_needs_review", title="Review"
        )

        assert len(notifications) == 1
        assert notifications[0].recipient_user_id == prof.id


class TestNotifyCourseStudents:
    async def test_notifies_only_students(self, db_session, make_user, make_course, enrol):
        course, _prof = await make_course()
        student = await make_user(UserRole.STUDENT)
        await enrol(student, course, "student")
        co_prof = await make_user(UserRole.PROFESSOR)
        await enrol(co_prof, course, "professor")

        notifications = await notify_course_students(
            db_session, course_id=course.id, type="grade_ready", title="Grades posted"
        )

        recipients = {n.recipient_user_id for n in notifications}
        assert recipients == {student.id}
