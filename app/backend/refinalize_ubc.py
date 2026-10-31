import asyncio
from uuid import UUID
import db.base  # Register the complete SQLAlchemy model graph.
from db.session import AsyncSessionLocal
from services.exam_generator import finalize_exam_template
from dependencies.storage_dep import get_storage_repo

TEMPLATE_ID = UUID("7435b724-201b-4a38-adf1-ac8e072061aa")
CREATED_BY = UUID("1d81bcb6-6078-44e2-98a8-74a1a40ae1ba")

async def main():
    storage_repo = get_storage_repo()
    async with AsyncSessionLocal() as db:
        result = await finalize_exam_template(db, storage_repo, TEMPLATE_ID, CREATED_BY)
        print("omr_template_id:", result.omr_template_id)

asyncio.run(main())
