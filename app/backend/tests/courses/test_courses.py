import pytest
from datetime import datetime, timezone
from sqlalchemy import select, update

from models.course_roster_entry import CourseRosterEntry
from models.course import Course
from models.enrolment import Enrolment
from models.user import User
from models.user import UserRole
from services import course_invites


pytestmark = pytest.mark.db

class TestCreateCourse:
    async def test_create_course_success(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "COSC 499"
        assert response.json()["academic_year_start"] == datetime.now(timezone.utc).year
        assert response.json()["archived_at"] is None
        assert response.json()["source"] == "omr"
        assert response.json()["canvas_link"] is None
        assert datetime.fromisoformat(
            response.json()["invite_link_expires_at"]
        ) > datetime.now(timezone.utc)

    async def test_create_course_with_academic_year_start(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/courses",
            json={
                "name": "COSC 499",
                "academic_term_id": "00000000-0000-0000-0007-000000000001",
                "academic_year_start": 2026,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        assert response.json()["academic_term"]["name"] == "Winter Session 1"
        assert response.json()["academic_year_start"] == 2026

    async def test_create_course_unauthenticated(self, client):
        response = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
        )
        assert response.status_code == 401

    async def test_create_course_requires_an_academic_term_id(self, authenticated_client):
        client, token = await authenticated_client()

        response = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "semester": "Winter Session 1"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422


class TestListCourses:
    async def test_list_courses(self, authenticated_client):
        client, token = await authenticated_client()
        await client.post("/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers={"Authorization": f"Bearer {token}"})
        await client.post("/api/courses", json={"name": "COSC 310", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers={"Authorization": f"Bearer {token}"})
        response = await client.get("/api/courses", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_courses_unauthenticated(self, client):
        response = await client.get("/api/courses")
        assert response.status_code == 401


class TestCourseAccess:
    async def test_get_course_forbidden_for_non_owner_professor(self, authenticated_client):
        owner_client, owner_token = await authenticated_client(email="owner@example.com")
        other_client, other_token = await authenticated_client(email="other@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}

        create = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = create.json()["id"]

        response = await other_client.get(f"/api/courses/{course_id}", headers=other_headers)

        assert response.status_code == 403

    async def test_get_course_allowed_for_enrolled_student(
        self,
        authenticated_client,
        register_user,
        db_session,
    ):
        owner_client, owner_token = await authenticated_client(email="owner@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        create = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = create.json()["id"]

        student_email = "student@example.com"
        student_response = await register_user(email=student_email)
        student_token = student_response.json()["access_token"]
        result = await db_session.execute(select(User).where(User.email == student_email))
        student = result.scalar_one()

        db_session.add(Enrolment(course_id=course_id, user_id=student.id, role="student"))
        await db_session.commit()

        response = await owner_client.get(
            f"/api/courses/{course_id}",
            headers={"Authorization": f"Bearer {student_token}"},
        )

        assert response.status_code == 200
        assert response.json()["id"] == course_id

    async def test_get_course_allowed_for_enrolled_co_professor(
        self,
        authenticated_client,
        db_session,
    ):
        owner_client, owner_token = await authenticated_client(email="owner3@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        co_prof_client, co_prof_token = await authenticated_client(email="coprof3@example.com")

        create = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = create.json()["id"]

        result = await db_session.execute(select(User).where(User.email == "coprof3@example.com"))
        co_prof = result.scalar_one()
        db_session.add(Enrolment(course_id=course_id, user_id=co_prof.id, role="professor"))
        await db_session.commit()

        response = await co_prof_client.get(
            f"/api/courses/{course_id}",
            headers={"Authorization": f"Bearer {co_prof_token}"},
        )

        assert response.status_code == 200
        assert response.json()["id"] == course_id

    async def test_archived_course_is_hidden_from_student(
        self,
        authenticated_client,
        register_user,
        db_session,
    ):
        owner_client, owner_token = await authenticated_client(email="archive-owner@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        created = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = created.json()["id"]

        student_email = "archived-student@example.com"
        student_response = await register_user(email=student_email)
        student_token = student_response.json()["access_token"]
        student = (
            await db_session.execute(select(User).where(User.email == student_email))
        ).scalar_one()
        db_session.add(Enrolment(course_id=course_id, user_id=student.id, role="student"))
        await db_session.commit()

        policy = await owner_client.put(
            "/api/retention-policy",
            json={},
            headers=owner_headers,
        )
        assert policy.status_code == 200

        archived = await owner_client.post(
            f"/api/courses/{course_id}/archive",
            json={"confirmed": True},
            headers=owner_headers,
        )
        assert archived.status_code == 200

        student_headers = {"Authorization": f"Bearer {student_token}"}
        listing = await owner_client.get("/api/courses?include_archived=true", headers=student_headers)
        detail = await owner_client.get(f"/api/courses/{course_id}", headers=student_headers)
        owner_listing = await owner_client.get("/api/courses?include_archived=true", headers=owner_headers)

        assert listing.status_code == 200
        assert all(course["id"] != course_id for course in listing.json())
        assert detail.status_code == 404
        assert any(
            course["id"] == course_id and course["archived_at"] is not None
            for course in owner_listing.json()
        )

    async def test_owner_can_archive_and_restore_course(self, authenticated_client):
        client, token = await authenticated_client(email="lifecycle-owner@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = created.json()["id"]

        policy = await client.put(
            "/api/retention-policy",
            json={},
            headers=headers,
        )
        assert policy.status_code == 200

        archived = await client.post(
            f"/api/courses/{course_id}/archive",
            json={"confirmed": True},
            headers=headers,
        )
        archived_again = await client.post(
            f"/api/courses/{course_id}/archive",
            json={"confirmed": True},
            headers=headers,
        )
        restored = await client.post(f"/api/courses/{course_id}/restore", headers=headers)
        restored_again = await client.post(f"/api/courses/{course_id}/restore", headers=headers)

        assert archived.status_code == 200
        assert archived.json()["archived_at"] is not None
        assert archived.json()["retention_policy_id"] == policy.json()["id"]
        assert archived.json()["scanned_images_retention_until"] is not None
        assert archived.json()["exam_records_retention_until"] is not None
        assert archived_again.status_code == 200
        assert archived_again.json()["archived_at"] == archived.json()["archived_at"]
        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None
        assert restored.json()["retention_policy_id"] is None
        assert restored.json()["scanned_images_retention_until"] is None
        assert restored.json()["exam_records_retention_until"] is None
        assert restored_again.status_code == 200
        assert restored_again.json()["archived_at"] is None

    async def test_owner_can_permanently_delete_empty_course(
        self,
        authenticated_client,
        db_session,
    ):
        client, token = await authenticated_client(email="delete-owner@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = created.json()["id"]

        deleted = await client.delete(f"/api/courses/{course_id}", headers=headers)
        remaining = await db_session.execute(
            select(Course).where(Course.id == course_id)
        )

        assert deleted.status_code == 204
        assert remaining.scalar_one_or_none() is None

    async def test_course_with_enrolment_history_must_be_archived(
        self,
        authenticated_client,
        register_user,
        db_session,
    ):
        client, token = await authenticated_client(email="history-owner@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = created.json()["id"]
        student_email = "history-student@example.com"
        await register_user(email=student_email)
        student = (
            await db_session.execute(select(User).where(User.email == student_email))
        ).scalar_one()
        db_session.add(Enrolment(course_id=course_id, user_id=student.id, role="student"))
        await db_session.commit()

        deleted = await client.delete(f"/api/courses/{course_id}", headers=headers)

        assert deleted.status_code == 409
        assert deleted.json()["error"]["code"] == "course_has_history"
        assert await db_session.get(Course, course_id) is not None

    async def test_non_owner_cannot_archive_or_restore_course(self, authenticated_client):
        owner_client, owner_token = await authenticated_client(email="router-owner@example.com")
        other_client, other_token = await authenticated_client(email="router-other@example.com")
        created = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        course_id = created.json()["id"]
        other_headers = {"Authorization": f"Bearer {other_token}"}

        archive = await other_client.post(f"/api/courses/{course_id}/archive", headers=other_headers)
        restore = await other_client.post(f"/api/courses/{course_id}/restore", headers=other_headers)

        assert archive.status_code == 403
        assert restore.status_code == 403

    async def test_admin_can_manage_any_course(self, authenticated_client):
        owner_client, owner_token = await authenticated_client(email="owner@example.com")
        admin_client, admin_token = await authenticated_client(
            email="admin@example.com",
            role=UserRole.ADMIN,
        )

        create = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        course_id = create.json()["id"]

        response = await admin_client.delete(
            f"/api/courses/{course_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 204


class TestListEnrolledStudents:
    async def test_list_enrolled_students_returns_first_last_and_student_number(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post("/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers)
        course_id = create.json()["id"]

        csv_data = "email,first_name,last_name,student_number\nroster@ubco.ca,Roster,Student,87651234\n"
        files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}
        await client.post(f"/api/courses/{course_id}/students/upload-csv", files=files, headers=headers)

        response = await client.get(f"/api/courses/{course_id}/students", headers=headers)

        assert response.status_code == 200
        students = response.json()
        assert len(students) == 1
        assert students[0]["first_name"] == "Roster"
        assert students[0]["last_name"] == "Student"
        assert students[0]["email"] == "roster@ubco.ca"
        assert students[0]["student_number"] == "87651234"
        assert students[0]["role"] == "student"
        assert students[0]["account_status"] == "pending"
        assert students[0]["user_id"] is None

    async def test_list_enrolled_students_forbidden_for_enrolled_student(
        self,
        authenticated_client,
        register_user,
        db_session,
    ):
        owner_client, owner_token = await authenticated_client()
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        create = await owner_client.post("/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=owner_headers)
        course_id = create.json()["id"]

        student_email = "student-roster@example.com"
        student_response = await register_user(email=student_email)
        student_token = student_response.json()["access_token"]
        result = await db_session.execute(select(User).where(User.email == student_email))
        student = result.scalar_one()

        db_session.add(Enrolment(course_id=course_id, user_id=student.id, role="student"))
        await db_session.commit()

        response = await owner_client.get(
            f"/api/courses/{course_id}/students",
            headers={"Authorization": f"Bearer {student_token}"},
        )

        assert response.status_code == 403

    async def test_list_enrolled_students_allowed_for_enrolled_co_professor(
        self,
        authenticated_client,
        db_session,
    ):
        owner_client, owner_token = await authenticated_client(email="owner4@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        co_prof_client, co_prof_token = await authenticated_client(email="coprof4@example.com")

        create = await owner_client.post("/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=owner_headers)
        course_id = create.json()["id"]

        csv_data = "email,first_name,last_name,student_number\nroster4@ubco.ca,Roster,Student,87651236\n"
        files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}
        await owner_client.post(f"/api/courses/{course_id}/students/upload-csv", files=files, headers=owner_headers)

        result = await db_session.execute(select(User).where(User.email == "coprof4@example.com"))
        co_prof = result.scalar_one()
        db_session.add(Enrolment(course_id=course_id, user_id=co_prof.id, role="professor"))
        await db_session.commit()

        response = await co_prof_client.get(
            f"/api/courses/{course_id}/students",
            headers={"Authorization": f"Bearer {co_prof_token}"},
        )

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["first_name"] == "Roster"


class TestAddCourseStudent:
    async def test_add_course_student_creates_pending_roster_entry_and_sends_invite(
        self,
        authenticated_client,
        db_session,
        monkeypatch,
    ):
        delivered = []

        async def capture(email, **kwargs):
            delivered.append((email, kwargs))

        monkeypatch.setattr(
            course_invites,
            "send_course_invitation_email",
            capture,
        )
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        response = await client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "manual-new@example.com",
                "first_name": "Manual",
                "last_name": "Student",
                "student_number": "12345678",
            },
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["email"] == "manual-new@example.com"
        assert response.json()["role"] == "student"
        assert response.json()["account_status"] == "pending"
        assert response.json()["user_id"] is None

        result = await db_session.execute(select(User).where(User.email == "manual-new@example.com"))
        assert result.scalar_one_or_none() is None

        roster_entry = (
            await db_session.execute(
                select(CourseRosterEntry).where(
                    CourseRosterEntry.course_id == course_id,
                    CourseRosterEntry.email == "manual-new@example.com",
                )
            )
        ).scalar_one()
        enrolment = (
            await db_session.execute(
                select(Enrolment).where(
                    Enrolment.course_id == course_id,
                    Enrolment.role == "student",
                )
            )
        ).scalar_one_or_none()
        assert roster_entry.user_id is None
        assert roster_entry.invited_at is not None
        assert enrolment is None
        assert len(delivered) == 1
        email, invitation = delivered[0]
        assert email == "manual-new@example.com"
        assert invitation["course_name"] == "COSC 499"
        assert invitation["join_url"].endswith(f"/join/{create.json()['invite_link']}")

    async def test_add_course_student_enrolls_existing_student(
        self,
        authenticated_client,
        register_user,
        db_session,
        monkeypatch,
    ):
        delivered = []

        async def capture(email, **kwargs):
            delivered.append((email, kwargs))

        monkeypatch.setattr(
            course_invites,
            "send_course_invitation_email",
            capture,
        )
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        await register_user(
            email="manual-existing@example.com",
            first_name="Existing",
            last_name="Student",
            student_number="12345679",
        )

        response = await client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "manual-existing@example.com",
                "first_name": "Existing",
                "last_name": "Student",
                "student_number": "12345679",
            },
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["email"] == "manual-existing@example.com"
        assert response.json()["account_status"] == "linked"
        assert response.json()["user_id"] is not None

        listed = await client.get(f"/api/courses/{course_id}/students", headers=headers)
        assert len(listed.json()) == 1
        assert listed.json()[0]["account_status"] == "linked"

        student = (
            await db_session.execute(
                select(User).where(User.email == "manual-existing@example.com")
            )
        ).scalar_one()
        enrolment = (
            await db_session.execute(
                select(Enrolment).where(
                    Enrolment.course_id == course_id,
                    Enrolment.user_id == student.id,
                    Enrolment.role == "student",
                )
            )
        ).scalar_one_or_none()
        assert enrolment is not None
        assert delivered == []

    async def test_add_course_student_duplicate_returns_400(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]
        payload = {
            "email": "manual-duplicate@example.com",
            "first_name": "Duplicate",
            "last_name": "Student",
            "student_number": "12345680",
        }

        first = await client.post(f"/api/courses/{course_id}/students", json=payload, headers=headers)
        second = await client.post(f"/api/courses/{course_id}/students", json=payload, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 400

    async def test_add_course_student_forbidden_for_non_owner(self, authenticated_client):
        owner_client, owner_token = await authenticated_client(email="owner@example.com")
        other_client, other_token = await authenticated_client(email="other@example.com")

        create = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        course_id = create.json()["id"]

        response = await other_client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "blocked@example.com",
                "first_name": "Blocked",
                "last_name": "Student",
                "student_number": "12345681",
            },
            headers={"Authorization": f"Bearer {other_token}"},
        )

        assert response.status_code == 403

    async def test_admin_can_add_course_student(self, authenticated_client):
        owner_client, owner_token = await authenticated_client(email="owner@example.com")
        admin_client, admin_token = await authenticated_client(
            email="admin@example.com",
            role=UserRole.ADMIN,
        )

        create = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        course_id = create.json()["id"]

        response = await admin_client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "admin-added@example.com",
                "first_name": "Admin",
                "last_name": "Student",
                "student_number": "12345682",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 201

    async def test_add_course_student_rejects_existing_non_student(
        self,
        authenticated_client,
        db_session,
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        professor = User(
            email="not-student@example.com",
            first_name="Not",
            last_name="Student",
            password_hash="mockhash",
            role=UserRole.PROFESSOR.value,
        )
        db_session.add(professor)
        await db_session.commit()
        professor_id = professor.id

        response = await client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "not-student@example.com",
                "first_name": "Not",
                "last_name": "Student",
                "student_number": "12345683",
            },
            headers=headers,
        )

        assert response.status_code == 400
        enrolment = (
            await db_session.execute(
                select(Enrolment).where(
                    Enrolment.course_id == course_id,
                    Enrolment.user_id == professor_id,
                )
            )
        ).scalar_one_or_none()
        assert enrolment is None

    async def test_add_course_student_rejects_existing_student_number_mismatch(
        self,
        authenticated_client,
        register_user,
        db_session,
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        await register_user(
            email="manual-mismatch@example.com",
            first_name="Mismatch",
            last_name="Student",
            student_number="12345686",
        )

        response = await client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "manual-mismatch@example.com",
                "first_name": "Mismatch",
                "last_name": "Student",
                "student_number": "12345687",
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "student_number_mismatch"

        roster_entry = (
            await db_session.execute(
                select(CourseRosterEntry).where(
                    CourseRosterEntry.course_id == course_id,
                    CourseRosterEntry.email == "manual-mismatch@example.com",
                )
            )
        ).scalar_one_or_none()
        assert roster_entry is None


class TestCourseRosterClaiming:
    async def test_register_claims_pending_roster_entry(
        self,
        authenticated_client,
        register_user,
        db_session,
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        await client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "claim-register@example.com",
                "first_name": "Claim",
                "last_name": "Register",
                "student_number": "12345684",
            },
            headers=headers,
        )

        response = await register_user(
            email="claim-register@example.com",
            first_name="Claim",
            last_name="Register",
            student_number="12345684",
        )

        assert response.status_code == 200
        student = (
            await db_session.execute(
                select(User).where(User.email == "claim-register@example.com")
            )
        ).scalar_one()
        roster_entry = (
            await db_session.execute(
                select(CourseRosterEntry).where(
                    CourseRosterEntry.course_id == course_id,
                    CourseRosterEntry.email == "claim-register@example.com",
                )
            )
        ).scalar_one()
        enrolment = (
            await db_session.execute(
                select(Enrolment).where(
                    Enrolment.course_id == course_id,
                    Enrolment.user_id == student.id,
                    Enrolment.role == "student",
                )
            )
        ).scalar_one_or_none()

        assert roster_entry.user_id == student.id
        assert enrolment is not None

    async def test_register_does_not_claim_mismatched_student_number(
        self,
        authenticated_client,
        register_user,
        db_session,
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        await client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": "claim-mismatch@example.com",
                "first_name": "Claim",
                "last_name": "Mismatch",
                "student_number": "12345688",
            },
            headers=headers,
        )

        response = await register_user(
            email="claim-mismatch@example.com",
            first_name="Claim",
            last_name="Mismatch",
            student_number="12345689",
        )

        assert response.status_code == 200
        student = (
            await db_session.execute(
                select(User).where(User.email == "claim-mismatch@example.com")
            )
        ).scalar_one()
        roster_entry = (
            await db_session.execute(
                select(CourseRosterEntry).where(
                    CourseRosterEntry.course_id == course_id,
                    CourseRosterEntry.email == "claim-mismatch@example.com",
                )
            )
        ).scalar_one()
        enrolment = (
            await db_session.execute(
                select(Enrolment).where(
                    Enrolment.course_id == course_id,
                    Enrolment.user_id == student.id,
                    Enrolment.role == "student",
                )
            )
        ).scalar_one_or_none()

        assert roster_entry.user_id is None
        assert enrolment is None

    async def test_login_claims_pending_roster_entry(
        self,
        authenticated_client,
        create_user,
        login_user,
        db_session,
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        student = await create_user(
            email="claim-login@example.com",
            first_name="Claim",
            last_name="Login",
            password="Password123!",
            student_number="12345685",
        )
        db_session.add(
            CourseRosterEntry(
                course_id=course_id,
                email="claim-login@example.com",
                first_name="Claim",
                last_name="Login",
                student_number="12345685",
                source="manual",
            )
        )
        await db_session.commit()

        response = await login_user(
            email="claim-login@example.com",
            password="Password123!",
        )

        assert response.status_code == 200
        roster_entry = (
            await db_session.execute(
                select(CourseRosterEntry).where(
                    CourseRosterEntry.course_id == course_id,
                    CourseRosterEntry.email == "claim-login@example.com",
                )
            )
        ).scalar_one()
        enrolment = (
            await db_session.execute(
                select(Enrolment).where(
                    Enrolment.course_id == course_id,
                    Enrolment.user_id == student.id,
                    Enrolment.role == "student",
                )
            )
        ).scalar_one_or_none()

        assert roster_entry.user_id == student.id
        assert enrolment is not None


class TestUnenrollStudents:
    async def test_unenroll_student_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]

        csv_data = "email,first_name,last_name,student_number\nroster@ubco.ca,Roster,Student,87651234\n"
        files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}
        await client.post(f"/api/courses/{course_id}/students/upload-csv", files=files, headers=headers)

        listed = await client.get(f"/api/courses/{course_id}/students", headers=headers)
        student_id = listed.json()[0]["id"]

        response = await client.delete(
            f"/api/courses/{course_id}/students/{student_id}",
            headers=headers,
        )

        assert response.status_code == 204
        listed_after = await client.get(f"/api/courses/{course_id}/students", headers=headers)
        assert listed_after.json() == []

    async def test_unenroll_student_forbidden_for_non_owner(self, authenticated_client):
        owner_client, owner_token = await authenticated_client(email="owner@example.com")
        other_client, other_token = await authenticated_client(email="other@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}

        create = await owner_client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = create.json()["id"]

        csv_data = "email,first_name,last_name,student_number\nroster@ubco.ca,Roster,Student,87651234\n"
        files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}
        await owner_client.post(f"/api/courses/{course_id}/students/upload-csv", files=files, headers=owner_headers)

        listed = await owner_client.get(f"/api/courses/{course_id}/students", headers=owner_headers)
        student_id = listed.json()[0]["id"]

        response = await other_client.delete(
            f"/api/courses/{course_id}/students/{student_id}",
            headers=other_headers,
        )

        assert response.status_code == 403
        listed_after = await owner_client.get(f"/api/courses/{course_id}/students", headers=owner_headers)
        assert len(listed_after.json()) == 1

    async def test_unenroll_missing_student_enrolment_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = create.json()["id"]
        missing_student_id = "00000000-0000-0000-0000-000000000000"

        response = await client.delete(
            f"/api/courses/{course_id}/students/{missing_student_id}",
            headers=headers,
        )

        assert response.status_code == 404


class TestPromoteStudent:
    async def _enroll_linked_student(self, client, headers, course_id, register_user, email):
        await register_user(email=email, first_name="Linked", last_name="Student", student_number="19283746")
        response = await client.post(
            f"/api/courses/{course_id}/students",
            json={
                "email": email,
                "first_name": "Linked",
                "last_name": "Student",
                "student_number": "19283746",
            },
            headers=headers,
        )
        assert response.status_code == 201
        return response.json()["id"]

    async def test_promote_student_success(self, authenticated_client, register_user, db_session):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        create = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers,
        )
        course_id = create.json()["id"]
        email = "promotable@example.com"
        student_id = await self._enroll_linked_student(client, headers, course_id, register_user, email)

        response = await client.post(
            f"/api/courses/{course_id}/students/{student_id}/promote",
            headers=headers,
        )
        assert response.status_code == 204

        listed_after = await client.get(f"/api/courses/{course_id}/students", headers=headers)
        assert listed_after.json() == []

        user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.role == UserRole.PROFESSOR.value

        enrolment = (
            await db_session.execute(
                select(Enrolment).where(Enrolment.course_id == course_id, Enrolment.user_id == user.id)
            )
        ).scalar_one()
        assert enrolment.role == "professor"

    async def test_promote_student_forbidden_for_non_owner(
        self, authenticated_client, register_user
    ):
        owner_client, owner_token = await authenticated_client(email="owner2@example.com")
        other_client, other_token = await authenticated_client(email="other2@example.com")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}

        create = await owner_client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=owner_headers,
        )
        course_id = create.json()["id"]
        student_id = await self._enroll_linked_student(
            owner_client, owner_headers, course_id, register_user, "promotable2@example.com"
        )

        response = await other_client.post(
            f"/api/courses/{course_id}/students/{student_id}/promote",
            headers=other_headers,
        )
        assert response.status_code == 403

        listed_after = await owner_client.get(f"/api/courses/{course_id}/students", headers=owner_headers)
        assert len(listed_after.json()) == 1

    async def test_promote_pending_roster_entry_returns_400(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        create = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers,
        )
        course_id = create.json()["id"]

        csv_data = "email,first_name,last_name,student_number\npending@ubco.ca,Pending,Student,87651235\n"
        files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}
        await client.post(f"/api/courses/{course_id}/students/upload-csv", files=files, headers=headers)

        listed = await client.get(f"/api/courses/{course_id}/students", headers=headers)
        student_id = listed.json()[0]["id"]

        response = await client.post(
            f"/api/courses/{course_id}/students/{student_id}/promote",
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "student_not_linked"

    async def test_promote_already_staff_returns_400(
        self, authenticated_client, register_user, db_session
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        create = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers,
        )
        course_id = create.json()["id"]
        email = "already-staff@example.com"
        student_id = await self._enroll_linked_student(client, headers, course_id, register_user, email)

        await db_session.execute(
            update(User).where(User.email == email).values(role=UserRole.PROFESSOR.value)
        )
        await db_session.commit()

        response = await client.post(
            f"/api/courses/{course_id}/students/{student_id}/promote",
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "already_staff"

    async def test_promote_missing_roster_entry_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        create = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers,
        )
        course_id = create.json()["id"]
        missing_student_id = "00000000-0000-0000-0000-000000000000"

        response = await client.post(
            f"/api/courses/{course_id}/students/{missing_student_id}/promote",
            headers=headers,
        )
        assert response.status_code == 404


class TestDeleteCourse:
    async def test_delete_course_success(self, authenticated_client):
        client, token = await authenticated_client()
        create = await client.post("/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers={"Authorization": f"Bearer {token}"})
        course_id = create.json()["id"]
        response = await client.delete(f"/api/courses/{course_id}", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 204

    async def test_delete_course_forbidden(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="a@example.com")
        client_b, token_b = await authenticated_client(email="b@example.com")
        
        create = await client_a.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        course_id = create.json()["id"]
        
        response = await client_b.delete(
            f"/api/courses/{course_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 403
