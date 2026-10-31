"""Extract answer-key selections from a temporary batch of OMR scans."""

import logging
from collections import Counter
from dataclasses import dataclass
from string import ascii_uppercase
from uuid import UUID

import fitz
from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import (
    AppError,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from integrations.omr_client import (
    OMRClientError,
    OMRScanRejectedError,
    OMRTemplateNotFoundError,
    delete_scans,
    run_marking_job,
    upload_scan_pdf,
)
from models.omr_detected_mark import MarkFieldType
from repositories.exam_templates import get_exam_template_by_id
from repositories.exams import get_exam_by_id
from repositories.omr_templates import get_omr_template_by_id
from schemas.exam_answer_keys import (
    AnswerKeyScanWarning,
    AnswerKeyScanWarningCode,
    AnswerKeyVersionDetection,
    AnswerKeyVersionDetectionStatus,
    ExtractAnswerKeyScanBatchResponse,
    ExtractedAnswerKeyQuestion,
    ExtractedAnswerKeySheet,
)
from schemas.omr_schema import DetectedQuestionMark, MarkingResult
from services.course_lifecycle import ensure_exam_course_writable
from services.omr_field_ids import parse_question_id
from services.omr_mark_parsing import (
    detect_version,
    detect_version_from_q1,
    parse_question_selections,
)

logger = logging.getLogger(__name__)

MAX_ANSWER_KEY_SCAN_BYTES = 10_000_000
_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


@dataclass
class AnswerKeyScanUpload:
    filename: str | None
    content_type: str | None
    pdf_bytes: bytes


async def extract_answer_key_scan(
    db: AsyncSession,
    exam_id: UUID,
    requesting_user_id: UUID,
    *,
    files: list[AnswerKeyScanUpload],
    question_count: int,
) -> ExtractAnswerKeyScanBatchResponse:
    """Validate and extract every answer-key sheet across one or more uploaded PDFs.

    OMR scan records are temporary for this preview workflow. Every scan ID
    returned by preprocessing is deleted before this function returns or
    propagates an error.
    """
    if not files:
        raise BadRequestError("Please upload at least one PDF file", code="invalid_answer_key_scan_file")

    exam = await get_exam_by_id(db, exam_id)
    if not exam:
        raise NotFoundError("Exam not found", code="exam_not_found")
    if exam.created_by != requesting_user_id:
        raise ForbiddenError("Not authorized to modify this exam", code="forbidden")
    await ensure_exam_course_writable(db, exam_id)

    if not exam.exam_template_id:
        raise BadRequestError(
            "The exam must have an assigned template before extracting an answer key",
            code="exam_template_required",
        )
    template = await get_exam_template_by_id(db, exam.exam_template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if not template.omr_template_id:
        raise BadRequestError(
            "The exam template must be registered with OMR before extracting an answer key",
            code="omr_template_not_registered",
        )

    omr_template = await get_omr_template_by_id(db, template.omr_template_id)
    if not omr_template:
        raise NotFoundError("OMR template not found", code="omr_template_not_found")
    if not omr_template.preprocess_template_id or not omr_template.mark_template_id:
        raise BadRequestError(
            "The exam template's OMR registration is incomplete",
            code="omr_template_not_registered",
        )
    if omr_template.page_count < 1:
        raise BadRequestError(
            "The exam template has an invalid page count",
            code="invalid_template_page_count",
        )

    question_ids = _question_ids_for_extraction(template.question_config, question_count)

    # Validate every file up front, tagging failures with the originating
    # filename, so one bad file in a multi-file upload fails clearly instead
    # of producing one generic error for the whole batch.
    expected_sheet_counts: list[int] = []
    for upload in files:
        try:
            total_pages = _validate_pdf(upload.filename, upload.content_type, upload.pdf_bytes)
            if total_pages % omr_template.page_count != 0:
                raise BadRequestError(
                    f"PDF has {total_pages} page(s); expected a multiple of "
                    f"{omr_template.page_count} page(s) per answer-key sheet",
                    code="answer_key_scan_page_count_mismatch",
                    details={
                        "page_count": total_pages,
                        "pages_per_sheet": omr_template.page_count,
                    },
                )
        except AppError as exc:
            raise type(exc)(
                f"{upload.filename or 'Uploaded file'}: {exc.message}",
                code=exc.code,
                details=exc.details,
            ) from exc
        expected_sheet_counts.append(total_pages // omr_template.page_count)

    scan_ids: list[str] = []
    file_scan_ranges: list[tuple[str, list[str]]] = []
    operation_error: Exception | None = None
    try:
        try:
            for upload, expected_count in zip(files, expected_sheet_counts):
                file_scan_ids = await upload_scan_pdf(omr_template.preprocess_template_id, upload.pdf_bytes)
                scan_ids.extend(file_scan_ids)
                file_scan_ranges.append((upload.filename or "Uploaded file", file_scan_ids))
                if len(file_scan_ids) != expected_count:
                    raise BadRequestError(
                        f"{upload.filename or 'Uploaded file'}: OMR processed "
                        f"{len(file_scan_ids)} of {expected_count} answer-key sheet(s)",
                        code="answer_key_scan_incomplete",
                        details={
                            "expected_sheets": expected_count,
                            "processed_sheets": len(file_scan_ids),
                        },
                    )

            marking = await run_marking_job(omr_template.mark_template_id, scan_ids)
        except OMRScanRejectedError as exc:
            raise BadRequestError(
                "OMR could not recognize any complete answer-key sheets in the PDF",
                code="answer_key_scan_rejected",
                details=exc.errors,
            ) from exc
        except OMRTemplateNotFoundError as exc:
            raise ServiceUnavailableError(
                "The registered OMR template is unavailable",
                code="omr_template_unavailable",
            ) from exc
        except OMRClientError as exc:
            raise ServiceUnavailableError(
                "OMR could not extract the uploaded answer key",
                code="answer_key_scan_omr_failed",
            ) from exc

        _validate_marking_result(marking, scan_ids)
        return _build_response(
            marking,
            file_scan_ranges,
            question_ids=question_ids,
            version_count=template.n_versions,
            version_from_q1=template.version_from_q1,
            pages_per_sheet=omr_template.page_count,
        )
    except Exception as exc:
        operation_error = exc
        raise
    finally:
        if scan_ids:
            try:
                await delete_scans(scan_ids)
            except OMRClientError as exc:
                logger.exception(
                    "event=answer_key_scan_cleanup_failed exam_id=%s scan_count=%d",
                    exam_id,
                    len(scan_ids),
                )
                if operation_error is None:
                    raise ServiceUnavailableError(
                        "The answer key was extracted, but its temporary OMR scans could not be deleted",
                        code="answer_key_scan_cleanup_failed",
                    ) from exc


def _question_ids_for_extraction(question_config: dict, question_count: int) -> list[str]:
    if question_count < 1 or question_count > 200:
        raise BadRequestError(
            "Question count must be between 1 and 200",
            code="invalid_answer_key_question_count",
        )

    ordered_ids = sorted(
        question_config,
        key=lambda question_id: (
            (0, int(question_id)) if question_id.isdigit() else (1, question_id)
        ),
    )
    if question_count > len(ordered_ids):
        raise BadRequestError(
            f"Question count {question_count} exceeds the template's {len(ordered_ids)} questions",
            code="invalid_answer_key_question_count",
            details={
                "question_count": question_count,
                "template_question_count": len(ordered_ids),
            },
        )

    selected_ids = ordered_ids[:question_count]
    if any(not question_id.isdigit() for question_id in selected_ids):
        raise BadRequestError(
            "Answer-key scan extraction requires numeric template question IDs",
            code="unsupported_template_question_ids",
        )
    return selected_ids


def _validate_pdf(filename: str | None, content_type: str | None, pdf_bytes: bytes) -> int:
    if not filename or not filename.lower().endswith(".pdf"):
        raise BadRequestError(
            "Please upload a PDF file",
            code="invalid_answer_key_scan_file",
        )
    if content_type and content_type.lower() not in _PDF_CONTENT_TYPES:
        raise BadRequestError(
            "Please upload a PDF file",
            code="invalid_answer_key_scan_file",
        )
    if not pdf_bytes:
        raise BadRequestError(
            "The uploaded PDF is empty",
            code="invalid_answer_key_scan_file",
        )
    if len(pdf_bytes) > MAX_ANSWER_KEY_SCAN_BYTES:
        raise BadRequestError(
            "The uploaded PDF exceeds the 10 MB limit",
            code="answer_key_scan_too_large",
        )

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise BadRequestError(
            "The uploaded file is not a valid PDF",
            code="invalid_answer_key_scan_file",
        ) from exc

    try:
        if document.needs_pass:
            raise BadRequestError(
                "Password-protected PDFs are not supported",
                code="encrypted_answer_key_scan",
            )
        page_count = document.page_count
        if page_count < 1:
            raise BadRequestError(
                "The uploaded PDF has no pages",
                code="invalid_answer_key_scan_file",
            )
        return page_count
    finally:
        document.close()


def _validate_marking_result(marking: MarkingResult, scan_ids: list[str]) -> None:
    if marking.errors:
        raise BadRequestError(
            "OMR could not mark every answer-key sheet",
            code="answer_key_scan_marking_incomplete",
            details=[error.model_dump() for error in marking.errors],
        )

    returned_ids = [scan.scan_id for scan in marking.scans]
    if len(returned_ids) != len(scan_ids) or set(returned_ids) != set(scan_ids):
        raise ServiceUnavailableError(
            "OMR returned an incomplete answer-key marking result",
            code="answer_key_scan_marking_incomplete",
        )


def _build_response(
    marking: MarkingResult,
    file_scan_ranges: list[tuple[str, list[str]]],
    *,
    question_ids: list[str],
    version_count: int,
    version_from_q1: bool,
    pages_per_sheet: int,
) -> ExtractAnswerKeyScanBatchResponse:
    marks_by_scan = {scan.scan_id: scan.marks for scan in marking.scans}
    sheets: list[ExtractedAnswerKeySheet] = []
    sheet_index = 0
    for filename, file_scan_ids in file_scan_ranges:
        for local_sheet_index, scan_id in enumerate(file_scan_ids):
            sheets.append(
                _extract_sheet(
                    marks_by_scan[scan_id],
                    sheet_index=sheet_index,
                    local_sheet_index=local_sheet_index,
                    source_filename=filename,
                    question_ids=question_ids,
                    version_count=version_count,
                    version_from_q1=version_from_q1,
                    pages_per_sheet=pages_per_sheet,
                )
            )
            sheet_index += 1
    _add_duplicate_version_warnings(sheets)
    return ExtractAnswerKeyScanBatchResponse(
        pages_per_sheet=pages_per_sheet,
        sheets=sheets,
    )


def _extract_sheet(
    marks: list[DetectedQuestionMark],
    *,
    sheet_index: int,
    local_sheet_index: int,
    source_filename: str,
    question_ids: list[str],
    version_count: int,
    version_from_q1: bool,
    pages_per_sheet: int,
) -> ExtractedAnswerKeySheet:
    try:
        selections_by_question = parse_question_selections(marks)
        marks_by_field = {
            parse_question_id(mark.question_id): mark
            for mark in marks
        }
    except ValueError as exc:
        raise ServiceUnavailableError(
            "OMR returned an unsupported field identifier",
            code="invalid_omr_marking_result",
        ) from exc

    answers: dict[str, ExtractedAnswerKeyQuestion] = {}
    warnings: list[AnswerKeyScanWarning] = []
    included_confidences: list[float] = []

    for question_id in question_ids:
        question_number = int(question_id)
        mark = marks_by_field.get((MarkFieldType.QUESTION, question_number))
        selected = selections_by_question.get(question_number, [])
        confidence = mark.confidence if mark else 0.0
        flagged = mark.flagged if mark else True
        included_confidences.append(confidence)
        answers[question_id] = ExtractedAnswerKeyQuestion(
            selected_choices=selected,
            confidence=confidence,
            flagged=flagged,
        )

        if not selected:
            warnings.append(
                AnswerKeyScanWarning(
                    code=AnswerKeyScanWarningCode.BLANK_ANSWER,
                    message=f"Question {question_id} has no selected answer",
                    question_id=question_id,
                    confidence=confidence,
                )
            )
        elif flagged:
            warnings.append(
                AnswerKeyScanWarning(
                    code=AnswerKeyScanWarningCode.LOW_CONFIDENCE,
                    message=f"Question {question_id} should be reviewed",
                    question_id=question_id,
                    selected_choices=selected,
                    confidence=confidence,
                )
            )

    version, version_warning, version_confidence = _extract_version(
        marks,
        marks_by_field,
        version_count=version_count,
        version_from_q1=version_from_q1,
    )
    if version_warning:
        warnings.append(version_warning)
    if version_confidence is not None:
        included_confidences.append(version_confidence)

    page_start = local_sheet_index * pages_per_sheet + 1
    return ExtractedAnswerKeySheet(
        sheet_index=sheet_index,
        source_filename=source_filename,
        page_start=page_start,
        page_end=page_start + pages_per_sheet - 1,
        answers=answers,
        version=version,
        minimum_confidence=min(included_confidences) if included_confidences else None,
        warnings=warnings,
    )


def _extract_version(
    marks: list[DetectedQuestionMark],
    marks_by_field: dict[tuple[MarkFieldType, int], DetectedQuestionMark],
    *,
    version_count: int,
    version_from_q1: bool,
) -> tuple[AnswerKeyVersionDetection, AnswerKeyScanWarning | None, float | None]:
    if version_count == 1:
        return (
            AnswerKeyVersionDetection(status=AnswerKeyVersionDetectionStatus.NOT_APPLICABLE),
            None,
            None,
        )

    field = (MarkFieldType.QUESTION, 1) if version_from_q1 else (MarkFieldType.VERSION, 1)
    mark = marks_by_field.get(field)
    selected = list(mark.selected) if mark else []
    confidence = mark.confidence if mark else None
    detected = detect_version_from_q1(marks) if version_from_q1 else detect_version(marks)

    if not selected:
        return (
            AnswerKeyVersionDetection(
                status=AnswerKeyVersionDetectionStatus.MISSING,
                confidence=confidence,
            ),
            AnswerKeyScanWarning(
                code=AnswerKeyScanWarningCode.VERSION_NOT_DETECTED,
                message="No exam version was selected",
                confidence=confidence,
            ),
            confidence,
        )
    if len(selected) > 1:
        return (
            AnswerKeyVersionDetection(
                status=AnswerKeyVersionDetectionStatus.AMBIGUOUS,
                selected_choices=selected,
                confidence=confidence,
            ),
            AnswerKeyScanWarning(
                code=AnswerKeyScanWarningCode.VERSION_AMBIGUOUS,
                message="More than one exam version was selected",
                selected_choices=selected,
                confidence=confidence,
            ),
            confidence,
        )

    # Exactly one selection must agree with the shared parser. Invalid raw
    # labels cannot be represented by the public single-letter version schema.
    if detected is None or len(detected) != 1 or not detected.isalpha():
        raise ServiceUnavailableError(
            "OMR returned an invalid version field",
            code="invalid_omr_marking_result",
        )
    detected = detected.upper()
    version = AnswerKeyVersionDetection(
        status=AnswerKeyVersionDetectionStatus.DETECTED,
        selected_choices=[detected],
        detected_version=detected,
        confidence=confidence,
    )
    allowed_versions = ascii_uppercase[:version_count]
    if detected not in allowed_versions:
        return (
            version,
            AnswerKeyScanWarning(
                code=AnswerKeyScanWarningCode.VERSION_INVALID,
                message=f"Version {detected} is not used by this exam",
                selected_choices=[detected],
                confidence=confidence,
            ),
            confidence,
        )
    return version, None, confidence


def _add_duplicate_version_warnings(sheets: list[ExtractedAnswerKeySheet]) -> None:
    detected_versions = [
        sheet.version.detected_version
        for sheet in sheets
        if sheet.version.status == AnswerKeyVersionDetectionStatus.DETECTED
        and not any(
            warning.code == AnswerKeyScanWarningCode.VERSION_INVALID
            for warning in sheet.warnings
        )
    ]
    duplicates = {
        version for version, count in Counter(detected_versions).items() if count > 1
    }
    for sheet in sheets:
        version = sheet.version.detected_version
        if version in duplicates:
            sheet.warnings.append(
                AnswerKeyScanWarning(
                    code=AnswerKeyScanWarningCode.VERSION_DUPLICATE,
                    message=f"Version {version} was detected on more than one sheet",
                    selected_choices=[version],
                    confidence=sheet.version.confidence,
                )
            )
