import io
import uuid
from datetime import datetime
from unittest.mock import AsyncMock
import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient
from sqlalchemy.future import select
from models.course import Course
from models.course_roster_entry import CourseRosterEntry
from models.enrolment import Enrolment
from models.user import User
from models.user import UserRole
from services import course_invites
from services.email_service import EmailDeliveryError

UBC_TERM_ID = "00000000-0000-0000-0007-000000000001"

@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_success(authenticated_client, db_session: AsyncSession):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    
    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers
    )
    assert course_resp.status_code == status.HTTP_201_CREATED
    course_id = course_resp.json()["id"]

    # mock csv payload
    existing_email = f"alpha_{uuid.uuid4().hex[:4]}@ubco.ca"
    new_email = f"beta_{uuid.uuid4().hex[:4]}@ubco.ca"
    
    existing_user = User(
        email=existing_email,
        first_name="Existing",
        last_name="User",
        password_hash="mockhash",
        role="student",
        student_number="87654321",
    )
    db_session.add(existing_user)
    await db_session.commit()

    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{existing_email},Existing,User,87654321\n"
        f"{new_email},Brand,Student,12345678\n"
    )
    
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}
    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers
    )
    
    # check responses are valid
    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 2
    assert res_json["linked"] == 1
    assert res_json["pending"] == 1
    assert res_json["skipped"] == 0
    assert len(res_json["errors"]) == 0

    roster_query = await db_session.execute(
        select(CourseRosterEntry).filter(CourseRosterEntry.course_id == course_id)
    )
    roster_entries = roster_query.scalars().all()
    assert len(roster_entries) == 2

    enrolment_query = await db_session.execute(
        select(Enrolment).filter(Enrolment.course_id == course_id)
    )
    enrolments = enrolment_query.scalars().all()
    assert len(enrolments) == 1

    pending_user = await db_session.execute(select(User).where(User.email == new_email))
    assert pending_user.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_skips_duplicates(authenticated_client, db_session: AsyncSession):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    
    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers
    )
    course_id = course_resp.json()["id"]

    email = f"duplicate_{uuid.uuid4().hex[:4]}@ubco.ca"
    student = User(
        email=email,
        first_name="Repeated",
        last_name="Student",
        password_hash="hash",
        role="student",
        student_number="11112222",
    )
    db_session.add(student)
    await db_session.commit()

    csv_data = f"email,first_name,last_name,student_number\n{email},Repeated,Student,11112222\n"
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    first_response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers
    )
    second_response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers
    )

    assert first_response.status_code == status.HTTP_200_OK
    assert first_response.json()["enrolled"] == 1
    assert second_response.status_code == status.HTTP_200_OK
    res_json = second_response.json()
    assert res_json["enrolled"] == 0
    assert res_json["skipped"] == 1


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_rejects_malformed_student_number(authenticated_client, db_session: AsyncSession):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers
    )
    course_id = course_resp.json()["id"]

    new_email = f"gamma_{uuid.uuid4().hex[:4]}@ubco.ca"
    csv_data = f"email,first_name,last_name,student_number\n{new_email},Bad,Number,not-8-digits\n"
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 0
    assert len(res_json["errors"]) == 1

    user_result = await db_session.execute(select(User).filter(User.email == new_email))
    assert user_result.scalar_one_or_none() is None
    roster_result = await db_session.execute(
        select(CourseRosterEntry).filter(CourseRosterEntry.email == new_email)
    )
    assert roster_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_rejects_existing_non_student_user(
    authenticated_client,
    db_session: AsyncSession,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    professor_email = f"professor_{uuid.uuid4().hex[:4]}@ubco.ca"
    existing_professor = User(
        email=professor_email,
        first_name="Existing",
        last_name="Professor",
        password_hash="mockhash",
        role=UserRole.PROFESSOR.value,
    )
    db_session.add(existing_professor)
    await db_session.commit()

    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{professor_email},Existing,Professor,87654321\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 0
    assert len(res_json["errors"]) == 1

    roster_result = await db_session.execute(
        select(CourseRosterEntry).filter(CourseRosterEntry.email == professor_email)
    )
    assert roster_result.scalar_one_or_none() is None

    enrolment_result = await db_session.execute(
        select(Enrolment).filter(
            Enrolment.course_id == course_id,
            Enrolment.user_id == existing_professor.id,
        )
    )
    assert enrolment_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_invalid_headers(authenticated_client):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    #create real course for router first
    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499", "academic_term_id": UBC_TERM_ID},
        headers=headers
    )
    assert course_resp.status_code == status.HTTP_201_CREATED
    course_id = course_resp.json()["id"]
    # Malformed headers
    broken_csv = "username,fullname\ntyson,Tyson\n"
    files = {"file": ("bad_headers.csv", broken_csv.encode("utf-8"), "text/csv")}
    
    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers
    )
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_invalid_file_extension(authenticated_client):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    
    fake_course_id = str(uuid.uuid4())
    files = {"file": ("data.txt", b"plain text", "text/plain")}
    
    response = await client.post(
        f"/api/courses/{fake_course_id}/students/upload-csv",
        files=files,
        headers=headers
    )
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST

@pytest.mark.asyncio
async def test_enroll_via_csv_invalid_auth(client: AsyncClient):
    response = await client.post(
        "/api/courses",
        json={"name": "COSC 499", "academic_term_id": UBC_TERM_ID},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_skips_blank_trailing_rows(
    authenticated_client, db_session: AsyncSession
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    new_email = f"realstudent_{uuid.uuid4().hex[:4]}@ubco.ca"
    # Excel/Google Sheets exports commonly pad trailing rows with
    # comma-only blank lines; these must not be reported as errors.
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{new_email},Real,Student,12345678\n"
        ",,,\n"
        ",,,\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 1
    assert res_json["errors"] == []


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_skips_blank_row_with_extra_columns(
    authenticated_client, db_session: AsyncSession
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    new_email = f"realstudent_{uuid.uuid4().hex[:4]}@ubco.ca"
    # A blank row with more trailing commas than the header has columns
    # collects the overflow into DictReader's restkey (None) as a list,
    # which must not crash the blank-row check.
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{new_email},Real,Student,12345678\n"
        ",,,,,\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 1
    assert res_json["errors"] == []


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_reports_clean_message_for_student_number_conflict(
    authenticated_client, db_session: AsyncSession
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    # An existing student with no student_number yet, whose CSV row will try
    # to set a student_number already claimed by a different existing user.
    # This conflict is only detectable at the DB constraint level, not by any
    # application-level pre-check, so it must be translated into a clean
    # message rather than the raw asyncpg/SQLAlchemy exception text.
    linkme_email = f"linkme_{uuid.uuid4().hex[:4]}@ubco.ca"
    other_email = f"other_{uuid.uuid4().hex[:4]}@ubco.ca"

    linkme_user = User(
        email=linkme_email, first_name="Link", last_name="Me",
        password_hash="hash", role="student", student_number=None,
    )
    other_user = User(
        email=other_email, first_name="Other", last_name="Student",
        password_hash="hash", role="student", student_number="99999999",
    )
    db_session.add(linkme_user)
    db_session.add(other_user)
    await db_session.commit()

    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{linkme_email},Link,Me,99999999\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert len(res_json["errors"]) == 1
    assert res_json["errors"][0] == "Row 1: Student number is already in use by another account."


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_invites_only_pending_students(
    authenticated_client,
    db_session: AsyncSession,
    monkeypatch,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]
    invite_link = course_resp.json()["invite_link"]

    linked_email = f"linked_{uuid.uuid4().hex[:4]}@ubco.ca"
    pending_email = f"pending_{uuid.uuid4().hex[:4]}@ubco.ca"
    db_session.add(
        User(
            email=linked_email,
            first_name="Linked",
            last_name="Student",
            password_hash="mockhash",
            role="student",
            student_number="87654321",
        )
    )
    await db_session.commit()

    delivered: list[tuple[str, dict]] = []

    async def deliver(email: str, **kwargs) -> None:
        delivered.append((email, kwargs))

    monkeypatch.setattr(course_invites, "send_course_invitation_email", deliver)

    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{linked_email},Linked,Student,87654321\n"
        f"{pending_email},Pending,Student,12345678\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 2
    assert res_json["invited"] == 1
    assert res_json["invite_failed"] == 0

    # A student who matched an existing account is already enrolled and needs no
    # join link; only the pending roster entry is emailed.
    assert [email for email, _ in delivered] == [pending_email]
    assert delivered[0][1]["course_name"] == "COSC 499 Capstone"
    assert delivered[0][1]["join_url"].endswith(f"/join/{invite_link}")
    assert delivered[0][1]["expires_at"] == datetime.fromisoformat(
        course_resp.json()["invite_link_expires_at"]
    )

    roster_result = await db_session.execute(
        select(CourseRosterEntry).filter(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.email == pending_email,
        )
    )
    assert roster_result.scalar_one().invited_at is not None


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_reupload_does_not_resend_invites(
    authenticated_client,
    monkeypatch,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    delivered: list[str] = []

    async def deliver(email: str, **kwargs) -> None:
        delivered.append(email)

    monkeypatch.setattr(course_invites, "send_course_invitation_email", deliver)

    student_email = f"pending_{uuid.uuid4().hex[:4]}@ubco.ca"
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{student_email},Pending,Student,12345678\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    first = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )
    second = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert first.json()["invited"] == 1
    # The second upload skips the row as a duplicate, so no new invite goes out.
    assert second.json()["skipped"] == 1
    assert second.json()["invited"] == 0
    assert len(second.json()["warnings"]) == 1
    assert "already a part of the class" in second.json()["warnings"][0]
    assert delivered == [student_email]


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_survives_invite_delivery_failure(
    authenticated_client,
    db_session: AsyncSession,
    monkeypatch,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    async def fail(email: str, **kwargs) -> None:
        raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(course_invites, "send_course_invitation_email", fail)

    student_email = f"pending_{uuid.uuid4().hex[:4]}@ubco.ca"
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{student_email},Pending,Student,12345678\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    # The upload still succeeds: enrolment must not depend on the mail server.
    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 1
    assert res_json["invited"] == 0
    assert res_json["invite_failed"] == 1

    roster_result = await db_session.execute(
        select(CourseRosterEntry).filter(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.email == student_email,
        )
    )
    entry = roster_result.scalar_one()
    assert entry is not None
    # Left pending so a retry can pick it up rather than silently dropping it.
    assert entry.invited_at is None


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_warns_and_skips_students_already_in_class(
    authenticated_client,
    db_session: AsyncSession,
    monkeypatch,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    attempts: list[str] = []

    async def deliver(email: str, **kwargs) -> None:
        attempts.append(email)

    monkeypatch.setattr(course_invites, "send_course_invitation_email", deliver)

    student_email = f"pending_{uuid.uuid4().hex[:4]}@ubco.ca"
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{student_email},Ada,Lovelace,12345678\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    first = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )
    assert first.json()["enrolled"] == 1

    # Re-uploading the same file must not re-add or re-email a student who is
    # already on the roster: it skips them and warns the uploader by name,
    # rather than retrying.
    second = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )
    res_json = second.json()
    assert res_json["enrolled"] == 0
    assert res_json["skipped"] == 1
    assert res_json["invited"] == 0
    assert res_json["invite_failed"] == 0
    assert len(res_json["warnings"]) == 1
    warning = res_json["warnings"][0]
    assert student_email in warning
    assert "Ada Lovelace" in warning
    assert "already a part of the class" in warning

    # Emailed exactly once (the first upload), never again on re-upload.
    assert attempts == [student_email]


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_uploads_new_students_and_warns_on_existing(
    authenticated_client,
    db_session: AsyncSession,
    monkeypatch,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    monkeypatch.setattr(
        course_invites, "send_course_invitation_email", AsyncMock()
    )

    existing_email = f"existing_{uuid.uuid4().hex[:4]}@ubco.ca"
    new_email_1 = f"newone_{uuid.uuid4().hex[:4]}@ubco.ca"
    new_email_2 = f"newtwo_{uuid.uuid4().hex[:4]}@ubco.ca"

    # Seed the roster so one student in the upload is already in the class.
    seed_csv = (
        "email,first_name,last_name,student_number\n"
        f"{existing_email},Grace,Hopper,20250001\n"
    )
    await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files={"file": ("seed.csv", seed_csv.encode("utf-8"), "text/csv")},
        headers=headers,
    )

    # This file mixes the already-enrolled student with two brand-new ones.
    mixed_csv = (
        "email,first_name,last_name,student_number\n"
        f"{existing_email},Grace,Hopper,20250001\n"
        f"{new_email_1},Alan,Turing,20250002\n"
        f"{new_email_2},Katherine,Johnson,20250003\n"
    )
    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files={"file": ("roster.csv", mixed_csv.encode("utf-8"), "text/csv")},
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()

    # The two new students are enrolled; the already-enrolled one is skipped.
    assert res_json["enrolled"] == 2
    assert res_json["skipped"] == 1
    assert res_json["errors"] == []

    # The uploader is told, by name, exactly who was already in the class.
    assert len(res_json["warnings"]) == 1
    assert existing_email in res_json["warnings"][0]
    assert "already a part of the class" in res_json["warnings"][0]

    # A duplicate in the middle of the file never stops the rest from loading:
    # both new students landed on the roster.
    roster = await db_session.execute(
        select(CourseRosterEntry).filter(
            CourseRosterEntry.course_id == course_id,
        )
    )
    emails = {entry.email for entry in roster.scalars().all()}
    assert new_email_1 in emails
    assert new_email_2 in emails


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_rejects_non_utf8_file(authenticated_client):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    # 0xFF is not valid UTF-8; a Latin-1/Excel export can produce bytes like it.
    files = {"file": ("students.csv", b"email,first_name\n\xff\xfe,bad\n", "text/csv")}
    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "UTF-8" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_bulk_enroll_via_csv_fails_invites_when_origin_unset(
    authenticated_client,
    db_session: AsyncSession,
    monkeypatch,
):
    # Without FRONTEND_ORIGIN there is no usable join link. Delivery must fail
    # closed (leaving the entry pending) rather than mail a localhost URL.
    monkeypatch.setattr(course_invites.settings, "frontend_origin", None)

    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    student_email = f"pending_{uuid.uuid4().hex[:4]}@ubco.ca"
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{student_email},Pending,Student,12345678\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    response = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    res_json = response.json()
    assert res_json["enrolled"] == 1
    assert res_json["invited"] == 0
    assert res_json["invite_failed"] == 1

    roster_result = await db_session.execute(
        select(CourseRosterEntry).filter(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.email == student_email,
        )
    )
    # Still pending, so a retry once the origin is configured can deliver it.
    assert roster_result.scalar_one().invited_at is None


@pytest.mark.asyncio
async def test_resend_pending_invites_retries_failed_delivery(
    authenticated_client,
    db_session: AsyncSession,
    monkeypatch,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    attempts: list[str] = []

    async def deliver(email: str, **kwargs) -> None:
        attempts.append(email)
        # Fail the first (upload) attempt, succeed on the manual retry.
        if len(attempts) == 1:
            raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(course_invites, "send_course_invitation_email", deliver)

    student_email = f"pending_{uuid.uuid4().hex[:4]}@ubco.ca"
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{student_email},Ada,Lovelace,12345678\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    upload = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )
    assert upload.json()["invite_failed"] == 1

    # Manual retry path (non-Canvas course): re-sends only the still-pending
    # student, without needing a CSV re-upload.
    resend = await client.post(
        f"/api/courses/{course_id}/students/resend-invites",
        headers=headers,
    )
    assert resend.status_code == 200
    assert resend.json() == {"invited": 1, "invite_failed": 0}
    assert attempts == [student_email, student_email]

    roster_result = await db_session.execute(
        select(CourseRosterEntry).filter(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.email == student_email,
        )
    )
    assert roster_result.scalar_one().invited_at is not None


@pytest.mark.asyncio
async def test_resend_pending_invites_noop_when_all_already_invited(
    authenticated_client,
    monkeypatch,
):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    course_resp = await client.post(
        "/api/courses",
        json={"name": "COSC 499 Capstone", "academic_term_id": UBC_TERM_ID},
        headers=headers,
    )
    course_id = course_resp.json()["id"]

    monkeypatch.setattr(
        course_invites, "send_course_invitation_email", AsyncMock()
    )

    student_email = f"pending_{uuid.uuid4().hex[:4]}@ubco.ca"
    csv_data = (
        "email,first_name,last_name,student_number\n"
        f"{student_email},Ada,Lovelace,12345678\n"
    )
    files = {"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")}

    upload = await client.post(
        f"/api/courses/{course_id}/students/upload-csv",
        files=files,
        headers=headers,
    )
    assert upload.json()["invited"] == 1

    # Everyone was already invited on upload, so a manual resend sends nothing.
    resend = await client.post(
        f"/api/courses/{course_id}/students/resend-invites",
        headers=headers,
    )
    assert resend.status_code == 200
    assert resend.json() == {"invited": 0, "invite_failed": 0}
