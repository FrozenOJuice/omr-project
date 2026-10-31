"""Runs the OMR service's /mark job for a scan and persists the raw result.

This is the step between "scan uploaded to the OMR service" (scan_processing.py)
and grading (grading_service.py): it fetches per-bubble marks from the Go OMR
service and stores them as OMRMarking + OMRDetectedMark rows, typed by
field_type/field_index via services/omr_field_ids.parse_question_id.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from db.session import AsyncSessionLocal
from integrations.omr_client import OMRClientError, run_marking_job
from models.omr_template import OMRTemplate
from repositories.exam_templates import get_exam_template_by_id
from repositories.omr_markings import create_detected_marks, create_marking
from repositories.omr_templates import get_omr_template_by_id
from repositories.scans import ScanRepository
from schemas.omr_schema import DetectedQuestionMark
from services.omr_field_ids import parse_question_id

logger = logging.getLogger(__name__)


class MarkingConfigError(Exception):
    """Raised when a scan isn't ready to be marked (not uploaded, template not registered)."""


async def _resolve_omr_template(db, scan) -> OMRTemplate:
    if not scan.exam_template_id:
        raise MarkingConfigError(f"Scan {scan.id} has no exam_template_id")

    exam_template = await get_exam_template_by_id(db, scan.exam_template_id)
    if not exam_template or not exam_template.omr_template_id:
        raise MarkingConfigError(f"Exam template {scan.exam_template_id} has no linked OMR template")

    omr_template = await get_omr_template_by_id(db, exam_template.omr_template_id)
    if not omr_template or not omr_template.mark_template_id:
        raise MarkingConfigError(
            f"OMR template {exam_template.omr_template_id} has no marking template registered"
        )

    return omr_template


def _to_detected_mark_fields(mark: DetectedQuestionMark) -> tuple:
    field_type, field_index = parse_question_id(mark.question_id)
    detected_value = ",".join(mark.selected) if mark.selected else None
    boxes = [box.model_dump() for box in mark.boxes]
    return (
        field_type, field_index, detected_value, mark.flagged,
        mark.page_index, mark.bounds.model_dump(), boxes, mark.confidence,
    )


async def run_and_store_marking(scan_ids: list[UUID]) -> tuple[dict[UUID, UUID], dict[UUID, Exception]]:
    """Runs one batched /mark call for many scans and persists an OMRMarking
    + its detected marks for each successfully-marked scan.

    Batching every ready scan into a single /mark request (instead of one
    request per scan) is what lets the OMR service mark them in parallel and
    cuts the per-scan network/disk round trip the old one-request-per-scan
    loop paid.

    Returns (marking_ids, failures), both keyed by scan_id: marking_ids for
    scans that were marked and persisted successfully, failures for scans
    that weren't ready to mark or that the OMR service itself rejected. A
    per-scan failure doesn't stop the rest of the batch from being marked.

    Raises OMRClientError if the batched request itself fails (bad marking
    template id, malformed request, upstream 5xx) - that's a batch-wide
    failure, unlike a single scan's marking failure.
    """
    if not scan_ids:
        return {}, {}

    async with AsyncSessionLocal() as db:
        omr_template = None
        scan_by_omr_id: dict[str, UUID] = {}
        marking_by_scan_id = {}
        failures: dict[UUID, Exception] = {}
        scans = await ScanRepository.get_by_ids(db, scan_ids)
        templates = {}

        for scan_id in scan_ids:
            scan = scans.get(scan_id)
            if not scan or not scan.omr_scan_id:
                failures[scan_id] = MarkingConfigError(
                    f"Scan {scan_id} has not been uploaded to the OMR service"
                )
                continue

            template = templates.get(scan.exam_template_id)
            if template is None:
                try:
                    template = await _resolve_omr_template(db, scan)
                    templates[scan.exam_template_id] = template
                except MarkingConfigError as exc:
                    failures[scan_id] = exc
                    continue

            if omr_template is None:
                omr_template = template
            elif template.id != omr_template.id:
                failures[scan_id] = MarkingConfigError(
                    f"Scan {scan_id} uses a different marking template than the rest of its batch"
                )
                continue

            scan_by_omr_id[scan.omr_scan_id] = scan_id
            marking = await create_marking(
                db, scan_id=scan_id, omr_template_id=omr_template.id, flush=False
            )
            marking.status = "processing"
            marking.started_at = datetime.now(timezone.utc)
            marking_by_scan_id[scan_id] = marking

        await db.flush()
        await db.commit()

        if not scan_by_omr_id:
            return {}, failures

        try:
            result = await run_marking_job(omr_template.mark_template_id, list(scan_by_omr_id.keys()))
        except OMRClientError:
            for marking in marking_by_scan_id.values():
                marking.status = "failed"
                marking.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise

        markings: dict[UUID, UUID] = {}
        for scan_marks in result.scans:
            scan_id = scan_by_omr_id.get(scan_marks.scan_id)
            if scan_id is None:
                continue
            marking = marking_by_scan_id[scan_id]
            detected = [_to_detected_mark_fields(m) for m in scan_marks.marks]
            await create_detected_marks(db, marking.id, detected, flush=False)
            marking.status = "completed"
            marking.finished_at = datetime.now(timezone.utc)
            markings[scan_id] = marking.id

        for error in result.errors:
            scan_id = scan_by_omr_id.get(error.scan_id)
            if scan_id is None or scan_id in markings:
                continue
            marking_by_scan_id[scan_id].status = "failed"
            marking_by_scan_id[scan_id].finished_at = datetime.now(timezone.utc)
            failures[scan_id] = MarkingConfigError(
                f"OMR marking failed for scan {error.scan_id}: {error.debug}"
            )

        for scan_id, marking in marking_by_scan_id.items():
            if scan_id not in markings and scan_id not in failures:
                marking.status = "failed"
                marking.finished_at = datetime.now(timezone.utc)
                failures[scan_id] = MarkingConfigError(
                    f"OMR service returned no marks for scan {scan_id}"
                )
        await db.flush()
        await db.commit()
        return markings, failures
