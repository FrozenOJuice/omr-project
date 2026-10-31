"""Throwaway: uploads showcase04 via the REAL production path and fetches the
actual warped picture the OMR service produced, to check whether ScanExamMats
(used in production) also produces the bad warp the CLI's scanner.Scan
(fixed-index, no page-order fallback) showed."""
import asyncio

import db.base  # noqa
from db.session import AsyncSessionLocal
from dependencies.storage_dep import get_storage_repo
from models.course import Course
from models.exam import Exam
from models.exam_template import ExamTemplate
from models.scan import Scan
from services.convert_to_images import run_finalize_pipeline_with_retry
from services.scans import ScanService
from integrations.omr_client import get_scan_page_image
from sqlalchemy import select
from db.session import engine as _app_engine

_app_engine.echo = False


async def main():
    storage_repo = get_storage_repo()
    async with AsyncSessionLocal() as db:
        exam = (
            await db.execute(
                select(Exam).join(Course, Exam.course_id == Course.id).where(
                    Course.name == "COSC 499 - Capstone Project",
                    Exam.name == "Capstone Final Exam",
                )
            )
        ).scalar_one()
        course = await db.get(Course, exam.course_id)
        template = await db.get(ExamTemplate, exam.exam_template_id)
        prof = exam.created_by

    path = "./data/sample_scans/ubc_showcase04_wilson_dpi191_d0.76.pdf"
    with open(path, "rb") as f:
        pdf_bytes = f.read()

    async with AsyncSessionLocal() as db:
        scan_records = await ScanService.upload_scan(
            db=db, storage_repo=storage_repo, exam_id=exam.id, exam_template_id=template.id,
            uploader_user_id=prof, contents=pdf_bytes, filename="showcase04_realtest.pdf",
        )

    scan_record = scan_records[0]
    await run_finalize_pipeline_with_retry(scan_record.path, scan_record.id, storage_repo)

    async with AsyncSessionLocal() as db:
        scan = await db.get(Scan, scan_record.id)
        print(f"status={scan.status} failure={scan.failure_detail} omr_scan_id={scan.omr_scan_id}")

    if scan.omr_scan_id:
        for page in (0, 1):
            img_bytes = await get_scan_page_image(scan.omr_scan_id, page)
            out_path = f"./data/sample_scans/_real_warp_page{page}.png"
            with open(out_path, "wb") as f:
                f.write(img_bytes)
            print(f"wrote {out_path} ({len(img_bytes)} bytes)")


asyncio.run(main())
