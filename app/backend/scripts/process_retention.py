#!/usr/bin/env python3
"""Process due archive retention stages once; intended for a scheduled job."""
import asyncio
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

from db.session import AsyncSessionLocal
from dependencies.storage_dep import get_storage_repo
from services.retention_processor import process_due_retention


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await process_due_retention(db, get_storage_repo())
        print(f"Retention processed: {result}")


if __name__ == "__main__":
    asyncio.run(main())
