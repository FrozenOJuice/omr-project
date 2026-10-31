from fastapi import APIRouter

from core.settings import settings
from db.session import check_database_connection

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health/live")
async def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness():
    await check_database_connection()
    return {"status": "ready"}


@router.get("/health")
async def health():
    return await readiness()


if settings.debug:

    @router.get("/db-test")
    async def db_test():
        await check_database_connection()
        return {"db": "connected"}
