import pytest
from sqlalchemy import update
from models.user import User, UserRole
import uuid

@pytest.fixture
def authenticated_client(client, register_user, db_session):
    async def _authenticated_client(
        *,
        email: str = None,
        password: str = "Password123!",
    ):
        if email is None:
            email = f"user_{uuid.uuid4().hex[:8]}@example.com"
            
        response = await register_user(email=email, password=password)
        assert response.status_code == 200, response.json()
        token = response.json()["access_token"]
    
        await db_session.execute(
            update(User).where(User.email == email).values(role=UserRole.ADMIN.value)
        )
        await db_session.commit()
        
        return client, token

    return _authenticated_client
