import pytest

from models.user import Institution
from repositories import users


pytestmark = pytest.mark.db


async def test_update_account_persists_institution(db_session, create_user):
    user = await create_user(email="preference@example.com")

    updated_user = await users.update_account(
        db_session,
        user,
        institution=Institution.GENERIC,
    )
    await db_session.commit()

    assert updated_user.institution == Institution.GENERIC.value


async def test_current_user_defaults_to_ubc(client, register_user):
    register_response = await register_user(email="default@example.com")
    access_token = register_response.json()["access_token"]

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["institution"] == Institution.UBC.value


async def test_current_user_updates_institution(
    client,
    register_user,
    get_user_by_email,
):
    register_response = await register_user(email="preference@example.com")
    access_token = register_response.json()["access_token"]

    response = await client.patch(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"institution": Institution.GENERIC.value},
    )
    updated_user = await get_user_by_email("preference@example.com")

    assert response.status_code == 200
    assert response.json()["institution"] == Institution.GENERIC.value
    assert updated_user.institution == Institution.GENERIC.value


async def test_current_user_rejects_unknown_institution(client, register_user):
    register_response = await register_user(email="invalid@example.com")
    access_token = register_response.json()["access_token"]

    response = await client.patch(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"institution": "unknown"},
    )

    assert response.status_code == 422
