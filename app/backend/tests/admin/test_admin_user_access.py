import pytest

from core.tokens import hash_token
from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.user import AccountStatus
from models.user import UserRole

pytestmark = pytest.mark.db


async def test_admin_updates_user_role(
    client,
    admin_headers,
    create_user,
    get_user_by_email,
):
    user = await create_user(email="promoted-admin@example.com", role=UserRole.STUDENT)

    response = await client.patch(
        f"/api/admin/users/{user.id}/role",
        headers=await admin_headers(),
        json={"role": UserRole.ADMIN.value},
    )
    updated_user = await get_user_by_email("promoted-admin@example.com")

    assert response.status_code == 200
    assert response.json()["role"] == UserRole.ADMIN.value
    assert updated_user.role == UserRole.ADMIN.value


async def test_admin_cannot_change_own_role(
    client,
    admin_headers,
    get_user_by_email,
):
    headers = await admin_headers()
    admin = await get_user_by_email("admin@example.com")

    response = await client.patch(
        f"/api/admin/users/{admin.id}/role",
        headers=headers,
        json={"role": UserRole.PROFESSOR.value},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_change_own_role"


async def test_admin_can_demote_another_admin_when_active_admin_remains(
    client,
    auth_headers,
    create_user,
    login_user,
):
    target_admin = await create_user(email="target@example.com", role=UserRole.ADMIN)
    await create_user(email="admin@example.com", role=UserRole.ADMIN)
    login_response = await login_user(email="admin@example.com")

    response = await client.patch(
        f"/api/admin/users/{target_admin.id}/role",
        headers=auth_headers(login_response.json()["access_token"]),
        json={"role": UserRole.PROFESSOR.value},
    )

    assert response.status_code == 200
    assert response.json()["role"] == UserRole.PROFESSOR.value


async def test_admin_updates_user_status_and_revokes_sessions(
    client,
    admin_headers,
    create_user,
    login_user,
    get_refresh_token_by_hash,
    get_user_by_email,
):
    user = await create_user(email="student@example.com", role=UserRole.STUDENT)
    login_response = await login_user(email="student@example.com")
    refresh_token = login_response.json()["refresh_token"]

    response = await client.patch(
        f"/api/admin/users/{user.id}/status",
        headers=await admin_headers(),
        json={"status": AccountStatus.DISABLED.value},
    )
    persisted_refresh_token = await get_refresh_token_by_hash(hash_token(refresh_token))
    disabled_user = await get_user_by_email("student@example.com")
    disabled_login = await login_user(email="student@example.com")
    refresh_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    assert response.json()["status"] == AccountStatus.DISABLED.value
    assert disabled_user.status == AccountStatus.DISABLED.value
    assert persisted_refresh_token.revoked_at is not None
    assert disabled_login.status_code == 401
    assert refresh_response.status_code == 401


async def test_admin_cannot_disable_own_account(
    client,
    admin_headers,
    get_user_by_email,
):
    headers = await admin_headers()
    admin = await get_user_by_email("admin@example.com")

    response = await client.patch(
        f"/api/admin/users/{admin.id}/status",
        headers=headers,
        json={"status": AccountStatus.DISABLED.value},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_disable_self"


async def test_admin_can_disable_another_admin_when_active_admin_remains(
    client,
    auth_headers,
    create_user,
    login_user,
):
    target_admin = await create_user(email="target@example.com", role=UserRole.ADMIN)
    await create_user(email="admin@example.com", role=UserRole.ADMIN)
    login_response = await login_user(email="admin@example.com")

    response = await client.patch(
        f"/api/admin/users/{target_admin.id}/status",
        headers=auth_headers(login_response.json()["access_token"]),
        json={"status": AccountStatus.DISABLED.value},
    )

    assert response.status_code == 200
    assert response.json()["status"] == AccountStatus.DISABLED.value


async def test_admin_deletes_user_account(
    client,
    admin_headers,
    create_user,
    get_user_by_email,
):
    user = await create_user(email="student@example.com", role=UserRole.STUDENT)

    response = await client.delete(
        f"/api/admin/users/{user.id}",
        headers=await admin_headers(),
    )
    deleted_user = await get_user_by_email("student@example.com")

    assert response.status_code == 204
    assert deleted_user is None


async def test_admin_cannot_delete_own_account(
    client,
    admin_headers,
    get_user_by_email,
):
    headers = await admin_headers()
    admin = await get_user_by_email("admin@example.com")

    response = await client.delete(
        f"/api/admin/users/{admin.id}",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_delete_self"


async def test_admin_delete_blocks_users_with_owned_records(
    client,
    admin_headers,
    create_user,
    db_session,
    get_user_by_email,
):
    professor = await create_user(email="professor@example.com", role=UserRole.PROFESSOR)
    course = Course(
        name="COSC 304 - Introduction to Databases",
        academic_term_id=UBC_WINTER_SESSION_1_TERM_ID,
        created_by=professor.id,
    )
    db_session.add(course)
    await db_session.commit()

    response = await client.delete(
        f"/api/admin/users/{professor.id}",
        headers=await admin_headers(),
    )
    persisted_user = await get_user_by_email("professor@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_has_records"
    assert persisted_user is not None


async def test_admin_reenables_user_and_login_succeeds(
    client,
    admin_headers,
    create_user,
    login_user,
    get_user_by_email,
):
    user = await create_user(email="reenable@example.com", role=UserRole.STUDENT)
    headers = await admin_headers()

    disable_response = await client.patch(
        f"/api/admin/users/{user.id}/status",
        headers=headers,
        json={"status": AccountStatus.DISABLED.value},
    )
    assert disable_response.status_code == 200

    disabled_login = await login_user(email="reenable@example.com")
    assert disabled_login.status_code == 401

    enable_response = await client.patch(
        f"/api/admin/users/{user.id}/status",
        headers=headers,
        json={"status": AccountStatus.ACTIVE.value},
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["status"] == AccountStatus.ACTIVE.value

    reenabled_user = await get_user_by_email("reenable@example.com")
    assert reenabled_user.status == AccountStatus.ACTIVE.value

    reenabled_login = await login_user(email="reenable@example.com")
    assert reenabled_login.status_code == 200, reenabled_login.json()


async def test_reenable_clears_stale_rate_limit_from_disabled_attempts(
    client,
    admin_headers,
    create_user,
    login_user,
):
    user = await create_user(email="ratelimited@example.com", role=UserRole.STUDENT)
    headers = await admin_headers()

    await client.patch(
        f"/api/admin/users/{user.id}/status",
        headers=headers,
        json={"status": AccountStatus.DISABLED.value},
    )

    # Simulate a user retrying login a few times while disabled (e.g. reloading,
    # double-submitting) — each attempt counts against the per-email rate limit.
    for _ in range(5):
        attempt = await login_user(email="ratelimited@example.com")
        assert attempt.status_code == 401

    await client.patch(
        f"/api/admin/users/{user.id}/status",
        headers=headers,
        json={"status": AccountStatus.ACTIVE.value},
    )

    reenabled_login = await login_user(email="ratelimited@example.com")
    assert reenabled_login.status_code == 200, reenabled_login.json()


async def test_admin_cannot_switch_professor_to_student(
    client,
    admin_headers,
    create_user,
):
    professor = await create_user(email="professor@example.com", role=UserRole.PROFESSOR)

    response = await client.patch(
        f"/api/admin/users/{professor.id}/role",
        headers=await admin_headers(),
        json={"role": UserRole.STUDENT.value},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "professor_student_switch_forbidden"


async def test_admin_can_switch_student_to_professor(
    client,
    admin_headers,
    create_user,
    get_user_by_email,
):
    student = await create_user(
        email="student@example.com",
        role=UserRole.STUDENT,
        student_number="12345678",
    )

    response = await client.patch(
        f"/api/admin/users/{student.id}/role",
        headers=await admin_headers(),
        json={"role": UserRole.PROFESSOR.value},
    )

    updated_user = await get_user_by_email("student@example.com")

    assert response.status_code == 200
    assert response.json()["role"] == UserRole.PROFESSOR.value
    assert response.json()["student_number"] is None
    assert updated_user.role == UserRole.PROFESSOR.value
    assert updated_user.student_number is None


async def test_admin_can_still_switch_admin_to_professor_and_student(
    client,
    admin_headers,
    create_user,
):
    admin_a = await create_user(email="admin-a@example.com", role=UserRole.ADMIN)
    admin_b = await create_user(email="admin-b@example.com", role=UserRole.ADMIN)
    headers = await admin_headers()

    to_professor = await client.patch(
        f"/api/admin/users/{admin_a.id}/role",
        headers=headers,
        json={"role": UserRole.PROFESSOR.value},
    )
    assert to_professor.status_code == 200
    assert to_professor.json()["role"] == UserRole.PROFESSOR.value

    to_student = await client.patch(
        f"/api/admin/users/{admin_b.id}/role",
        headers=headers,
        json={"role": UserRole.STUDENT.value},
    )
    assert to_student.status_code == 200
    assert to_student.json()["role"] == UserRole.STUDENT.value
