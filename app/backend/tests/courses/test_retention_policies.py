from datetime import datetime, timedelta, timezone

import pytest

from errors.exceptions import ConflictError
from services.course_lifecycle import ensure_exam_course_writable


class TestRetentionPolicyCrud:
    async def test_get_returns_ubc_recommendation_before_configuration(
        self,
        authenticated_client,
    ):
        client, token = await authenticated_client(email="policy-new@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/retention-policy", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["policy"] is None
        assert data["recommended"]["scanned_image_retention_months"] == 12
        assert data["recommended"]["exam_record_retention_months"] == 12
        assert data["recommended"]["maximum_retention_months"] == 72
        assert "TL7300-15" in data["recommended"]["basis"]

    async def test_put_creates_and_updates_one_policy_per_professor(
        self,
        authenticated_client,
    ):
        client, token = await authenticated_client(email="policy-owner@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.put(
            "/api/retention-policy",
            json={},
            headers=headers,
        )
        updated = await client.put(
            "/api/retention-policy",
            json={
                "scanned_image_retention_months": 24,
                "exam_record_retention_months": 36,
                "retain_anonymized_analytics": False,
            },
            headers=headers,
        )
        fetched = await client.get("/api/retention-policy", headers=headers)

        assert created.status_code == 200
        assert created.json()["source"] == "ubc_default"
        assert updated.status_code == 200
        assert updated.json()["id"] == created.json()["id"]
        assert updated.json()["source"] == "custom"
        assert fetched.json()["configured"] is True
        assert fetched.json()["policy"]["scanned_image_retention_months"] == 24
        assert fetched.json()["policy"]["exam_record_retention_months"] == 36
        assert fetched.json()["policy"]["retain_anonymized_analytics"] is False

    async def test_policy_rejects_retention_below_ubc_minimum(
        self,
        authenticated_client,
    ):
        client, token = await authenticated_client(email="policy-invalid@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.put(
            "/api/retention-policy",
            json={"scanned_image_retention_months": 6},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_delete_resets_first_archive_configuration_state(
        self,
        authenticated_client,
    ):
        client, token = await authenticated_client(email="policy-delete@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        await client.put("/api/retention-policy", json={}, headers=headers)

        deleted = await client.delete("/api/retention-policy", headers=headers)
        fetched = await client.get("/api/retention-policy", headers=headers)

        assert deleted.status_code == 204
        assert fetched.json()["configured"] is False


class TestArchiveRetentionPolicy:
    async def test_first_archive_requires_policy(
        self,
        authenticated_client,
    ):
        client, token = await authenticated_client(email="archive-no-policy@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )

        response = await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            json={"confirmed": True},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "retention_policy_required"

    async def test_configured_archive_requires_confirmation(
        self,
        authenticated_client,
    ):
        client, token = await authenticated_client(email="archive-confirm@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        await client.put("/api/retention-policy", json={}, headers=headers)
        created = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )

        response = await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "archive_confirmation_required"

    async def test_archive_snapshots_policy_and_deadlines(
        self,
        authenticated_client,
        db_session,
    ):
        from models.course import Course

        client, token = await authenticated_client(email="archive-policy@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        policy = await client.put(
            "/api/retention-policy",
            json={
                "scanned_image_retention_months": 18,
                "exam_record_retention_months": 24,
                "retain_anonymized_analytics": True,
            },
            headers=headers,
        )
        created = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )

        archived = await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            json={"confirmed": True},
            headers=headers,
        )

        assert archived.status_code == 200
        data = archived.json()
        assert data["retention_policy_id"] == policy.json()["id"]
        archived_at = datetime.fromisoformat(data["archived_at"])
        scan_until = datetime.fromisoformat(data["scanned_images_retention_until"])
        records_until = datetime.fromisoformat(data["exam_records_retention_until"])
        assert (scan_until.year, scan_until.month) == _months_after(archived_at, 18)
        assert (records_until.year, records_until.month) == _months_after(archived_at, 24)

        course = await db_session.get(Course, created.json()["id"])
        assert course.retention_policy_snapshot == {
            "scanned_image_retention_months": 18,
            "exam_record_retention_months": 24,
            "retain_anonymized_analytics": True,
            "source": "custom",
            "retention_anchor_at": course.retention_policy_snapshot["retention_anchor_at"],
            "active_course_override_used": False,
        }

    async def test_future_exam_requires_override_and_anchors_deadline_to_exam_end(
        self, authenticated_client, db_session
    ):
        from models.exam import Exam

        client, token = await authenticated_client(email="archive-active@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        await client.put("/api/retention-policy", json={}, headers=headers)
        created = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )
        exam_end = datetime.now(timezone.utc) + timedelta(days=30)
        db_session.add(Exam(
            name="Future Final", description="", start_time=exam_end - timedelta(hours=2),
            end_time=exam_end, role="professor", created_by=created.json()["created_by"],
            course_id=created.json()["id"], exam_template_id=None,
        ))
        await db_session.commit()

        blocked = await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            json={"confirmed": True}, headers=headers,
        )
        archived = await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            json={"confirmed": True, "override_active_course": True}, headers=headers,
        )

        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "course_still_active"
        assert archived.status_code == 200
        scan_until = datetime.fromisoformat(archived.json()["scanned_images_retention_until"])
        assert (scan_until.year, scan_until.month) == _months_after(exam_end, 12)

    async def test_archived_course_rejects_roster_mutation(
        self, authenticated_client
    ):
        client, token = await authenticated_client(email="archive-read-only@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        await client.put("/api/retention-policy", json={}, headers=headers)
        created = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )
        await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            json={"confirmed": True}, headers=headers,
        )

        response = await client.post(
            f"/api/courses/{created.json()['id']}/students",
            json={"email": "student@example.com", "first_name": "Test", "last_name": "Student", "student_number": "87654321"},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "course_archived_read_only"

    async def test_archived_course_rejects_exam_record_mutation_guard(
        self, authenticated_client, db_session
    ):
        from models.exam import Exam

        client, token = await authenticated_client(email="archive-exam-data@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        await client.put("/api/retention-policy", json={}, headers=headers)
        created = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )
        exam = Exam(
            name="Past Midterm", description="",
            start_time=datetime.now(timezone.utc) - timedelta(hours=2),
            end_time=datetime.now(timezone.utc) - timedelta(hours=1), role="professor",
            created_by=created.json()["created_by"], course_id=created.json()["id"],
            exam_template_id=None,
        )
        db_session.add(exam)
        await db_session.commit()
        await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            json={"confirmed": True}, headers=headers,
        )

        with pytest.raises(ConflictError) as exc_info:
            await ensure_exam_course_writable(db_session, exam.id)

        assert exc_info.value.code == "course_archived_read_only"

    async def test_restore_is_disabled_after_retention_processing(
        self, authenticated_client, db_session
    ):
        from models.course import Course

        client, token = await authenticated_client(email="archive-purged@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        await client.put("/api/retention-policy", json={}, headers=headers)
        created = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )
        await client.post(
            f"/api/courses/{created.json()['id']}/archive",
            json={"confirmed": True}, headers=headers,
        )
        course = await db_session.get(Course, created.json()["id"])
        course.scanned_images_purged_at = datetime.now(timezone.utc)
        await db_session.commit()

        restored = await client.post(
            f"/api/courses/{created.json()['id']}/restore", headers=headers
        )

        assert restored.status_code == 409
        assert restored.json()["error"]["code"] == "retention_already_processed"


def _months_after(value: datetime, months: int) -> tuple[int, int]:
    month_index = value.month - 1 + months
    return value.year + month_index // 12, month_index % 12 + 1
