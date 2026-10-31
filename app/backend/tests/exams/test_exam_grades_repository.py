import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from repositories.exam_grades import acquire_student_grade_lock


pytestmark = pytest.mark.db


@pytest_asyncio.fixture
async def advisory_db_engine() -> AsyncEngine:
    """This lock test needs PostgreSQL, but no application schema."""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_student_grade_lock_serializes_the_same_exam_student_pair(
    advisory_db_engine: AsyncEngine,
):
    """A second transaction must wait until the first pair lock is released."""
    session_factory = async_sessionmaker(
        bind=advisory_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    exam_id = uuid.uuid4()
    student_id = uuid.uuid4()

    async with session_factory() as first, session_factory() as second:
        await acquire_student_grade_lock(first, exam_id, student_id)
        second_started = asyncio.Event()

        async def acquire_in_second_transaction():
            second_started.set()
            await acquire_student_grade_lock(second, exam_id, student_id)

        second_acquire = asyncio.create_task(acquire_in_second_transaction())
        try:
            await second_started.wait()
            await asyncio.sleep(0.05)
            assert not second_acquire.done()

            await first.commit()
            await asyncio.wait_for(second_acquire, timeout=1)
        finally:
            if not second_acquire.done():
                second_acquire.cancel()
                await asyncio.gather(second_acquire, return_exceptions=True)
            await first.rollback()
            await second.rollback()
