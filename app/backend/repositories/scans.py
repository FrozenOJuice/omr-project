import uuid
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from sqlalchemy.future import select
from models.scan import Scan


class ScanRepository:
    @staticmethod
    async def create(
        db: AsyncSession,
        exam_id: uuid.UUID,
        exam_template_id,
        uploader_user_id: uuid.UUID,
        path: str,
        page_count: Optional[int] = None,
        batch_id: Optional[uuid.UUID] = None,
        batch_index: Optional[int] = None,
    ) -> Scan:
        scan = Scan(
            exam_id=exam_id,
            exam_template_id=exam_template_id,
            uploader_user_id=uploader_user_id,
            path=path,
            page_count=page_count,
            batch_id=batch_id,
            batch_index=batch_index,
        )
        db.add(scan)
        await db.flush()
        return scan

    @staticmethod
    async def create_many(db: AsyncSession, records: list[dict]) -> list[Scan]:
        scans = [Scan(**record) for record in records]
        db.add_all(scans)
        await db.flush()
        return scans

    @staticmethod
    async def get_by_id(db: AsyncSession, scan_id: uuid.UUID) -> Optional[Scan]:
        result = await db.execute(select(Scan).filter(Scan.id == scan_id))
        return result.scalars().first()

    @staticmethod
    async def get_by_ids(
        db: AsyncSession, scan_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Scan]:
        result = await db.execute(select(Scan).where(Scan.id.in_(scan_ids)))
        return {scan.id: scan for scan in result.scalars().all()}

    @staticmethod
    async def get_by_exam(db: AsyncSession, exam_id: uuid.UUID) -> Sequence[Scan]:
        result = await db.execute(select(Scan).filter(Scan.exam_id == exam_id))
        return result.scalars().all()
    
    @staticmethod
    async def get_by_template(db: AsyncSession, exam_template_id: uuid.UUID) -> Sequence[Scan]:
        result = await db.execute(select(Scan).filter(Scan.exam_template_id == exam_template_id))
        return result.scalars().all()

    @staticmethod
    async def count_others_with_path(db: AsyncSession, path: str, scan_id: uuid.UUID) -> int:
        result = await db.execute(
            select(func.count()).select_from(Scan).where(Scan.path == path, Scan.id != scan_id)
        )
        return int(result.scalar_one())

    @staticmethod
    async def delete(db: AsyncSession, scan: Scan) -> None:
        await db.delete(scan)

    @staticmethod
    async def set_omr_scan_id(db: AsyncSession, scan_id: uuid.UUID, omr_scan_id: str) -> Optional[Scan]:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan:
            return None
        scan.omr_scan_id = omr_scan_id
        await db.flush()
        return scan

    @staticmethod
    async def set_omr_job_id(db: AsyncSession, scan_id: uuid.UUID, omr_job_id: str) -> Optional[Scan]:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan:
            return None
        scan.omr_job_id = omr_job_id
        await db.flush()
        return scan

    @staticmethod
    async def set_status(db: AsyncSession, scan_id: uuid.UUID, status: str) -> Optional[Scan]:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan:
            return None
        scan.status = status
        await db.flush()
        return scan

    @staticmethod
    async def count_batch_progress(db: AsyncSession, batch_id: uuid.UUID) -> tuple[int, int]:
        """(total scans sharing this batch_id, how many are still 'pending').

        A batch's scans stay 'pending' until grading resolves them (see
        scan_processing._trigger_marking), so this is what tells whether the
        whole pipeline -- not just OMR preprocessing -- has actually finished.
        """
        result = await db.execute(
            select(
                func.count(Scan.id),
                func.count(Scan.id).filter(Scan.status == "pending"),
            ).where(Scan.batch_id == batch_id)
        )
        total, pending = result.one()
        return total, pending

    @staticmethod
    async def set_failed(
        db: AsyncSession, scan_id: uuid.UUID, failure_code: str, failure_detail: str
    ) -> Optional[Scan]:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan:
            return None
        scan.status = "failed"
        scan.failure_code = failure_code
        scan.failure_detail = failure_detail
        await db.flush()
        return scan
