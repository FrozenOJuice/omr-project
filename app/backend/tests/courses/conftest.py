import pytest
import uuid

from sqlalchemy import update
from models.user import User, UserRole

@pytest.fixture
def authenticated_client(client, register_user, db_session):
    async def _authenticated_client(
        *,
        email: str = None,
        password: str = "Password123!",
        role: UserRole = UserRole.PROFESSOR,
    ):
        if email is None:
            email = f"user_{uuid.uuid4().hex[:8]}@example.com"
            
        response = await register_user(email=email, password=password)
        assert response.status_code == 200, response.json()
        token = response.json()["access_token"]
    
        await db_session.execute(
            update(User).where(User.email == email).values(role=role.value)
        )
        await db_session.commit()
        
        return client, token

    return _authenticated_client


@pytest.fixture
def create_course(authenticated_client):
    async def _create_course(
        *,
        name: str = "COSC 499",
        academic_term_id: str = "00000000-0000-0000-0007-000000000001",
    ):
        client, token = await authenticated_client()

        return await client.post(
            "/api/courses",
            json={"name": name, "academic_term_id": academic_term_id},
            headers={"Authorization": f"Bearer {token}"},
        )

    return _create_course
