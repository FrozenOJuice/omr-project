import pytest

from models.user import Institution, UserRole


pytestmark = pytest.mark.db


async def _headers(create_user, login_user, *, email: str, role: UserRole, institution=Institution.UBC):
    await create_user(
        email=email,
        role=role,
        institution=institution,
        student_number=None if role != UserRole.STUDENT else None,
    )
    response = await login_user(email=email)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_lists_seeded_presets_for_the_users_institution(
    client, create_user, login_user
):
    ubc_headers = await _headers(
        create_user,
        login_user,
        email="ubc-prof@example.com",
        role=UserRole.PROFESSOR,
    )
    generic_headers = await _headers(
        create_user,
        login_user,
        email="generic-prof@example.com",
        role=UserRole.PROFESSOR,
        institution=Institution.GENERIC,
    )

    ubc = await client.get("/api/academic-terms", headers=ubc_headers)
    generic = await client.get("/api/academic-terms", headers=generic_headers)

    assert ubc.status_code == 200
    assert len(ubc.json()) == 6
    assert all(term["institution"] == "ubc" for term in ubc.json())
    assert all(term["in_use"] is False for term in ubc.json())
    assert generic.status_code == 200
    assert [term["name"] for term in generic.json()] == ["General"]


async def test_professor_can_create_and_manage_an_owner_scoped_custom_term(
    client, create_user, login_user
):
    owner_headers = await _headers(
        create_user,
        login_user,
        email="term-owner@example.com",
        role=UserRole.PROFESSOR,
    )
    other_headers = await _headers(
        create_user,
        login_user,
        email="other-prof@example.com",
        role=UserRole.PROFESSOR,
    )

    created = await client.post(
        "/api/academic-terms",
        headers=owner_headers,
        json={"name": "Fall Intensive", "year_format": "start_year"},
    )
    term_id = created.json()["id"]
    owner_list = await client.get("/api/academic-terms", headers=owner_headers)
    other_list = await client.get("/api/academic-terms", headers=other_headers)
    forbidden = await client.patch(
        f"/api/academic-terms/{term_id}",
        headers=other_headers,
        json={"name": "Changed"},
    )
    updated = await client.patch(
        f"/api/academic-terms/{term_id}",
        headers=owner_headers,
        json={"name": "Fall Block", "is_active": False},
    )
    deleted = await client.delete(
        f"/api/academic-terms/{term_id}", headers=owner_headers
    )

    assert created.status_code == 201
    assert created.json()["term_type"] == "custom"
    assert any(term["id"] == term_id for term in owner_list.json())
    assert all(term["id"] != term_id for term in other_list.json())
    assert forbidden.status_code == 403
    assert updated.status_code == 200
    assert updated.json()["name"] == "Fall Block"
    assert updated.json()["is_active"] is False
    assert deleted.status_code == 204


async def test_professor_cannot_manage_preset_terms(client, create_user, login_user):
    headers = await _headers(
        create_user,
        login_user,
        email="preset-prof@example.com",
        role=UserRole.PROFESSOR,
    )
    terms = (await client.get("/api/academic-terms", headers=headers)).json()
    preset_id = terms[0]["id"]

    create = await client.post(
        "/api/academic-terms",
        headers=headers,
        json={"name": "New Preset", "term_type": "preset"},
    )
    update_response = await client.patch(
        f"/api/academic-terms/{preset_id}",
        headers=headers,
        json={"name": "Changed Preset"},
    )

    assert create.status_code == 403
    assert update_response.status_code == 403


async def test_admin_can_create_rename_and_archive_a_preset(
    client, create_user, login_user
):
    headers = await _headers(
        create_user,
        login_user,
        email="term-admin@example.com",
        role=UserRole.ADMIN,
    )
    created = await client.post(
        "/api/academic-terms",
        headers=headers,
        json={
            "name": "Trimester 1",
            "term_type": "preset",
            "institution": "generic",
            "year_format": "start_year",
        },
    )
    updated = await client.patch(
        f"/api/academic-terms/{created.json()['id']}",
        headers=headers,
        json={"name": "First Trimester", "is_active": False},
    )
    listed = await client.get(
        "/api/academic-terms?institution=generic&include_archived=true",
        headers=headers,
    )

    assert created.status_code == 201
    assert created.json()["code"] == "trimester-1"
    assert updated.status_code == 200
    assert updated.json()["name"] == "First Trimester"
    assert updated.json()["is_active"] is False
    assert any(term["id"] == created.json()["id"] for term in listed.json())


async def test_last_active_preset_cannot_be_archived(client, create_user, login_user):
    headers = await _headers(
        create_user,
        login_user,
        email="last-preset-admin@example.com",
        role=UserRole.ADMIN,
    )
    terms = (
        await client.get(
            "/api/academic-terms?institution=generic", headers=headers
        )
    ).json()

    response = await client.patch(
        f"/api/academic-terms/{terms[0]['id']}",
        headers=headers,
        json={"is_active": False},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "academic_term_last_preset"


async def test_course_uses_selected_term_and_reflects_preset_changes(
    client, create_user, login_user
):
    professor_headers = await _headers(
        create_user,
        login_user,
        email="course-term-prof@example.com",
        role=UserRole.PROFESSOR,
    )
    admin_headers = await _headers(
        create_user,
        login_user,
        email="course-term-admin@example.com",
        role=UserRole.ADMIN,
    )
    terms = (await client.get("/api/academic-terms", headers=professor_headers)).json()
    term = next(item for item in terms if item["name"] == "Winter Session 1")

    created = await client.post(
        "/api/courses",
        headers=professor_headers,
        json={"name": "COSC 499", "academic_term_id": term["id"]},
    )
    renamed = await client.patch(
        f"/api/academic-terms/{term['id']}",
        headers=admin_headers,
        json={"name": "Winter Term One"},
    )
    fetched = await client.get(
        f"/api/courses/{created.json()['id']}", headers=professor_headers
    )

    assert created.status_code == 201
    assert created.json()["academic_term_id"] == term["id"]
    assert created.json()["academic_term"]["name"] == "Winter Session 1"
    assert renamed.status_code == 200
    assert fetched.json()["academic_term"]["name"] == "Winter Term One"


async def test_course_rejects_a_term_from_another_institution(
    client, create_user, login_user
):
    headers = await _headers(
        create_user,
        login_user,
        email="generic-course-prof@example.com",
        role=UserRole.PROFESSOR,
        institution=Institution.GENERIC,
    )
    ubc_term_id = "00000000-0000-0000-0007-000000000001"

    response = await client.post(
        "/api/courses",
        headers=headers,
        json={"name": "Generic Course", "academic_term_id": ubc_term_id},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "academic_term_unavailable"


async def test_custom_term_used_by_a_course_cannot_be_deleted(
    client, create_user, login_user
):
    headers = await _headers(
        create_user,
        login_user,
        email="used-term-prof@example.com",
        role=UserRole.PROFESSOR,
    )
    term = await client.post(
        "/api/academic-terms",
        headers=headers,
        json={"name": "Reading Week"},
    )
    course = await client.post(
        "/api/courses",
        headers=headers,
        json={"name": "Special Topics", "academic_term_id": term.json()["id"]},
    )
    listed = await client.get("/api/academic-terms", headers=headers)
    listed_term = next(item for item in listed.json() if item["id"] == term.json()["id"])
    deleted = await client.delete(
        f"/api/academic-terms/{term.json()['id']}", headers=headers
    )

    assert course.status_code == 201
    assert listed_term["in_use"] is True
    assert deleted.status_code == 409
    assert deleted.json()["error"]["code"] == "academic_term_in_use"
