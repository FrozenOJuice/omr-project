"""Grades a completed OMR marking against the matching exam answer key.

OMRDetectedMark rows are typed by field_type/field_index (see
services/omr_field_ids.py), decoded from the OMR service's questionId
convention (e.g. "Q7" -> question 7, "V1" -> version). QUESTION marks are
scored here; VERSION, name, and student id marks are cross-checked to decide
whether the exam can be confidently assigned to a student or must be flagged
for review.
"""
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.session import AsyncSessionLocal
from errors.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from integrations.omr_client import OMRClientError, get_question_snippet, get_scan_page_image
from models.user import User, UserRole
from repositories.courses import get_by_id as get_course_by_id, get_enrolment, get_student_enrolment
from repositories.exam_answer_keys import (
    get_answer_key_by_id,
    get_exam_ids_by_answer_key_ids,
    get_exam_versions_by_answer_key_ids,
    get_template_sections_by_answer_key_ids,
    list_answer_keys_by_exam,
)
from repositories.exam_grades import (
    acquire_student_grade_lock,
    create_grade,
    get_exam_for_grade,
    get_grade_by_id,
    get_grade_by_omr_marking,
    list_grades_by_exam,
    student_has_grade_for_exam,
)
from repositories.grade_audit_entries import create_audit_entry, list_audit_entries_by_grade
from repositories.exam_templates import get_exam_template_by_omr_template_id
from repositories.exams import get_exam_by_id
from repositories.omr_markings import (
    get_detected_marks,
    get_detected_marks_by_marking_ids,
    get_identity_marks,
    get_identity_marks_for_page,
    get_omr_marking_by_id,
    get_omr_markings_by_ids,
    get_page_counts_by_marking_ids,
    get_question_marks_for_page,
    get_scan_for_marking,
    get_scans_by_ids,
    get_version_mark_for_page,
)
from repositories.omr_templates import get_omr_template_by_id
from repositories.users import get_users_by_ids
from schemas.exam_grades import (
    ExamGradeResponse,
    GradeAuditEntryResponse,
    GradeSectionResult,
    IdentityAnnotations,
    IdentityFieldAnnotation,
    OptionBox,
    QuestionAnnotation,
    UpdateExamGradeRequest,
    VersionAnnotation,
)
from services.answer_key_status import (
    answer_key_is_complete as _answer_key_is_complete,
    incomplete_answer_key_versions,
)
from services.course_lifecycle import ensure_course_id_writable, ensure_course_writable
from services.notifications import notify_course_staff
from services.omr_field_ids import split_detected_value
from services.omr_mark_parsing import (
    detect_version,
    detect_version_from_q1,
    parse_question_selections,
)
from services.course import list_enrolled_students
from services.student_identity_decoder import DecodedIdentity, decode_identity_fields
from services.student_matcher import (
    IdentityMatchResult,
    MatchStatus,
    match_candidates,
    match_student_identity_for_course,
)

logger = logging.getLogger(__name__)

_GRADE_COMMIT_CHUNK_SIZE = 10


def _incomplete_answer_key_versions(exam_template, answer_keys: list) -> list[str]:
    return incomplete_answer_key_versions(exam_template.n_versions, answer_keys)


def _select_answer_key(answer_keys: list, detected_version: str | None):
    """Find the answer key for the detected version; fall back to the default
    key, or the first one created if the exam has no default configured."""
    for key in answer_keys:
        if key.exam_version == detected_version:
            return key
    for key in answer_keys:
        if key.exam_version is None:
            return key
    return answer_keys[0] if answer_keys else None


def _version_flag_reason(answer_keys: list, detected_version: str | None) -> str | None:
    """Flags a version mismatch, unless the exam doesn't use versioned keys at all."""
    if not any(key.exam_version is not None for key in answer_keys):
        return None
    if detected_version is None:
        return "version_not_detected"
    if not any(key.exam_version == detected_version for key in answer_keys):
        return "version_not_recognized"
    return None


def _name_flag_reason(match_status: MatchStatus) -> str | None:
    if match_status == MatchStatus.NO_MATCH:
        return "name_no_match"
    if match_status == MatchStatus.AMBIGUOUS:
        return "name_ambiguous"
    return None


def _student_id_flag_reason(match_result: IdentityMatchResult) -> str | None:
    """Flags a student-id mismatch, unless no one on the roster has a
    student_number on file yet (rolling out gradually — see the migration
    that introduced it, which leaves pre-existing accounts unset).
    """
    if not match_result.student_id_available:
        return None
    if match_result.student_id.status == MatchStatus.NO_MATCH:
        return "student_id_no_match"
    if match_result.student_id.status == MatchStatus.AMBIGUOUS:
        return "student_id_ambiguous"
    return None


def _identity_mismatch_flag_reason(match_result: IdentityMatchResult) -> str | None:
    """Flags the case where name and student id each cleanly match — but to
    two different students.
    """
    name_result, id_result = match_result.name, match_result.student_id
    if (
        name_result.status == MatchStatus.MATCHED
        and id_result.status == MatchStatus.MATCHED
        and name_result.student.id != id_result.student.id
    ):
        return "identity_mismatch"
    return None


def _name_confidence_flag_reason(decoded_identity: DecodedIdentity) -> str | None:
    """Flags a low-confidence name decode (blank/multi-marked/faint bubble)
    even if the decoded value still happens to match a real student — a
    lucky match doesn't mean the OMR read it correctly.
    """
    if decoded_identity.first_name.ambiguous or decoded_identity.last_name.ambiguous:
        return "name_low_confidence"
    return None


def _student_id_confidence_flag_reason(
    decoded_identity: DecodedIdentity, match_result: IdentityMatchResult
) -> str | None:
    """Flags a low-confidence student-id decode, unless no one on the roster
    has a student_number on file yet (same rollout gate as
    _student_id_flag_reason — an unreliable read of a column nobody's using
    for matching yet isn't worth flagging).
    """
    if not match_result.student_id_available:
        return None
    if decoded_identity.student_id.ambiguous:
        return "student_id_low_confidence"
    return None


def _score_question(
    student_answers: list[str],
    correct_answers: list[str],
    grading_type: str,
    points: float,
    partial_weights: dict[str, float],
) -> float:
    student_set = set(student_answers)
    correct_set = set(correct_answers)

    if grading_type in ("single", "multiple"):
        return points if student_set == correct_set else 0.0

    if grading_type == "partial":
        score = sum(
            partial_weights.get(ans, 0.0) for ans in student_answers if ans in correct_set
        ) * points
        return min(max(score, 0.0), points)

    return 0.0


def _is_ambiguous(student_answers: list[str], grading_type: str) -> bool:
    """A "single" question with more than one bubble marked is scored wrong
    like any other mismatch, but it's a distinct failure mode (the student or
    the scanner produced an unresolvable read) worth flagging for a human to
    look at, rather than silently indistinguishable from a clean wrong answer.
    """
    return grading_type == "single" and len(student_answers) > 1


def _compute_scores(
    answers_by_q: dict[int, list[str]],
    answer_key,
    default_points: float,
) -> tuple[dict, float, float]:
    """Compute per-question results dict, total_score, and max_score."""
    question_results: dict = {}
    total_score = 0.0
    max_score = 0.0

    for q_num_str, ak_item in answer_key.answer_key.items():
        q_num = int(q_num_str)
        student_answers = sorted(answers_by_q.get(q_num, []))
        correct_answers = sorted(ak_item.get("correct_choices", []))
        grading_type = ak_item.get("grading_type", "single")
        points = ak_item.get("points") or default_points
        partial_weights = ak_item.get("partial_weights") or {}

        score = _score_question(student_answers, correct_answers, grading_type, points, partial_weights)

        question_results[q_num_str] = {
            "grading_type": grading_type,
            "student_answers": student_answers,
            "correct_answers": correct_answers,
            "correct": score >= points,
            "score": round(score, 4),
            "max_score": points,
            "ambiguous": _is_ambiguous(student_answers, grading_type),
        }
        total_score += score
        max_score += points

    return question_results, round(total_score, 4), round(max_score, 4)


async def _grade_loaded_marking(
    db: AsyncSession,
    marking,
    detected_marks: list,
    exam_template,
    exam,
    answer_keys: list,
    match_identity,
    commit: bool = True,
) -> object:
    """Grades one already-loaded, already-known-completed OMR marking against
    already-loaded exam context (exam template, answer keys).

    `match_identity` is an async callable taking the marking's decoded
    identity and returning an IdentityMatchResult -- it's called at the same
    point grade_marking always resolved identity (after the answer-key
    checks below), just with each caller's own way of getting there:
    grade_marking wraps match_student_identity_for_course (a fresh roster
    query), grade_markings_batch wraps a synchronous lookup against a roster
    it already queried once for the whole batch.

    This is the shared core of grade_marking (single marking, one-off) and
    grade_markings_batch (many markings from one batch-upload pipeline run,
    with exam/template/answer-key/roster data loaded once per exam and
    reused across every marking in the batch). Commits `db` on success; the
    caller is responsible for rolling back on failure.

    Steps:
    1. Parse detected marks to build a {field_index: [labels]} map for QUESTION marks.
    2. Detect exam version from the VERSION-type mark.
    3. Select the answer key for that exam matching the detected version (fallback: default key).
    4. Score each question.
    5. Decode the name and student id fields and match them against the roster.
    6. Flag the grade for manual review on a version, name, or student id mismatch
       (including a name/id pointing at two different students, or either decoding
       with low confidence even if it still happened to match); otherwise assign
       it to the matched student.
    """
    answers_by_q = parse_question_selections(detected_marks)

    detected_version = (
        detect_version_from_q1(detected_marks)
        if exam_template.version_from_q1
        else detect_version(detected_marks)
    )

    answer_key = _select_answer_key(answer_keys, detected_version)
    if not answer_key:
        raise NotFoundError(
            "No answer key found for this exam", code="answer_key_not_found"
        )
    incomplete_versions = _incomplete_answer_key_versions(exam_template, answer_keys)
    if incomplete_versions:
        raise BadRequestError(
            "Complete every answer-key version before grading this exam.",
            code="answer_keys_incomplete",
            details={"versions": incomplete_versions},
        )

    scoring_rules = answer_key.scoring_rules or {}
    default_points = scoring_rules.get("default_points_per_question", 1.0)

    question_results, total_score, max_score = _compute_scores(
        answers_by_q, answer_key, default_points
    )

    decoded_identity = decode_identity_fields(detected_marks)
    match_result = await match_identity(decoded_identity)

    flag_reasons = [
        reason
        for reason in (
            _version_flag_reason(answer_keys, detected_version),
            _name_flag_reason(match_result.name.status),
            _student_id_flag_reason(match_result),
            _identity_mismatch_flag_reason(match_result),
            _name_confidence_flag_reason(decoded_identity),
            _student_id_confidence_flag_reason(decoded_identity, match_result),
        )
        if reason
    ]
    matched_student = match_result.name.student
    if not flag_reasons and matched_student is not None:
        # Serialize the check and create below. Without this transaction-level
        # pair lock, two scan workers can both observe no existing grade before
        # either transaction commits.
        await acquire_student_grade_lock(db, exam.id, matched_student.id)
        if await student_has_grade_for_exam(db, exam.id, matched_student.id):
            # Keep the second scan in the review queue rather than silently
            # producing two released grades for one student. Staff can inspect
            # the scans and explicitly confirm the assignment if intentional.
            flag_reasons.append("duplicate_student_grade")

    grade_status = "needs_review" if flag_reasons else "graded"
    matched_student_id = matched_student.id if matched_student is not None and grade_status == "graded" else None

    grade = await create_grade(
        db,
        omr_marking_id=marking.id,
        exam_answer_key_id=answer_key.id,
        question_results=question_results,
        total_score=total_score,
        max_score=max_score,
        template_version=exam_template.version,
        student_id=matched_student_id,
        status=grade_status,
        flag_reason=",".join(flag_reasons) or None,
        flush=commit,
    )
    await create_audit_entry(
        db,
        exam_grade_id=grade.id,
        actor_user_id=None,
        event_type="initial_grade",
        previous_total_score=None,
        new_total_score=total_score,
        changes={
            "questions": {
                q_num: {"before": None, "after": result}
                for q_num, result in question_results.items()
            },
            "student_id": {"before": None, "after": str(matched_student_id) if matched_student_id else None},
            "status": {"before": None, "after": grade_status},
            "flag_reason": {"before": None, "after": ",".join(flag_reasons) or None},
        },
        flush=commit,
    )
    if commit:
        await db.commit()
    # grade_status is returned alongside grade (rather than leaving callers to
    # read grade.status back off the object create_grade returned) so a
    # caller can tell whether this grade needs review without depending on
    # create_grade's return value actually carrying a live `status` attribute
    # -- notably, unit tests stub create_grade with a bare mock.
    return grade, grade_status


async def grade_marking(db: AsyncSession, marking_id: UUID) -> object:
    """Grade a single completed OMR marking and persist an ExamGrade record,
    notifying course staff immediately if it needs review.

    Loads exam/template/answer-key/roster context fresh for this one
    marking, then delegates the actual scoring/flagging to
    _grade_loaded_marking. For grading many markings from one batch-upload
    pipeline run, use grade_markings_batch instead: it shares that context
    across the whole batch (rather than reloading it per marking) and lets
    the caller send one aggregate notification instead of one per grade.
    """
    marking = await get_omr_marking_by_id(db, marking_id)
    if not marking:
        raise NotFoundError("OMR marking not found", code="marking_not_found")
    if marking.status != "completed":
        raise BadRequestError(
            f"Marking must be 'completed' before grading (current: '{marking.status}')",
            code="marking_not_completed",
        )

    detected_marks = await get_detected_marks(db, marking_id)

    exam_template = await get_exam_template_by_omr_template_id(db, marking.omr_template_id)
    if not exam_template:
        raise NotFoundError(
            "No exam template found for this OMR template", code="template_not_found"
        )

    scan = await get_scan_for_marking(db, marking)
    if not scan:
        raise NotFoundError("No scan found for this marking", code="scan_not_found")

    exam = await get_exam_by_id(db, scan.exam_id)
    if not exam:
        raise NotFoundError("No exam found for this scan", code="exam_not_found")
    await ensure_course_id_writable(db, exam.course_id)

    answer_keys = await list_answer_keys_by_exam(db, scan.exam_id)

    async def match_identity(decoded_identity: DecodedIdentity) -> IdentityMatchResult:
        return await match_student_identity_for_course(db, exam.course_id, decoded_identity)

    try:
        grade, grade_status = await _grade_loaded_marking(
            db, marking, detected_marks, exam_template, exam, answer_keys, match_identity
        )
    except Exception:
        await db.rollback()
        raise

    # A "graded" result isn't shown to the student yet -- see
    # services/exam.py's release_exam, which notifies each matched student
    # only once the instructor releases the exam's results.
    if grade_status == "needs_review":
        try:
            await notify_course_staff(
                db,
                course_id=exam.course_id,
                type="grade_needs_review",
                title="A grade needs manual review",
                body=exam.name,
                link_path="/courses",
                link_query=f"courseId={exam.course_id}&examId={exam.id}",
            )
        except Exception:
            logger.exception("Failed to send grading notification for grade %s", grade.id)

    return grade


async def grade_markings_batch(marking_ids: list[UUID]) -> dict[UUID, object]:
    """Grades many completed OMR markings from one batch-upload pipeline run.

    Shared grading context is loaded once per exam. Writes commit in chunks,
    with a savepoint keeping one invalid grade from affecting the others.

    Notification is the caller's job, not this function's -- see
    scan_processing._trigger_marking, which uses the returned per-marking
    results to send one aggregate "N grades need review" notification for
    the whole batch instead of one per grade.

    Returns {marking_id: grade_or_exception}, one entry per input id.
    """
    if not marking_ids:
        return {}

    results: dict[UUID, object] = {}

    async with AsyncSessionLocal() as read_db, AsyncSessionLocal() as write_db:
        markings = await get_omr_markings_by_ids(read_db, marking_ids)
        detected_marks_by_marking = await get_detected_marks_by_marking_ids(read_db, marking_ids)
        scans_by_id = await get_scans_by_ids(read_db, [m.scan_id for m in markings.values()])

        template_cache: dict[UUID, object] = {}
        exam_context_cache: dict[UUID, tuple | None] = {}
        pending_ids: list[UUID] = []

        for marking_id in marking_ids:
            marking = markings.get(marking_id)
            if marking is None:
                results[marking_id] = NotFoundError("OMR marking not found", code="marking_not_found")
                continue
            if marking.status != "completed":
                results[marking_id] = BadRequestError(
                    f"Marking must be 'completed' before grading (current: '{marking.status}')",
                    code="marking_not_completed",
                )
                continue

            if marking.omr_template_id not in template_cache:
                template_cache[marking.omr_template_id] = await get_exam_template_by_omr_template_id(
                    read_db, marking.omr_template_id
                )
            exam_template = template_cache[marking.omr_template_id]
            if not exam_template:
                results[marking_id] = NotFoundError(
                    "No exam template found for this OMR template", code="template_not_found"
                )
                continue

            scan = scans_by_id.get(marking.scan_id)
            if not scan:
                results[marking_id] = NotFoundError("No scan found for this marking", code="scan_not_found")
                continue

            if scan.exam_id not in exam_context_cache:
                exam = await get_exam_by_id(read_db, scan.exam_id)
                if not exam:
                    exam_context_cache[scan.exam_id] = None
                else:
                    try:
                        await ensure_course_id_writable(read_db, exam.course_id)
                    except Exception as exc:
                        exam_context_cache[scan.exam_id] = exc
                    else:
                        answer_keys = await list_answer_keys_by_exam(read_db, scan.exam_id)
                        roster = list(await list_enrolled_students(read_db, exam.course_id))
                        names = {}
                        student_numbers = {}
                        for user in roster:
                            key = (user.first_name.lower(), user.last_name.lower())
                            names.setdefault(key, []).append(user)
                            if user.student_number:
                                student_numbers.setdefault(user.student_number, []).append(user)
                        exam_context_cache[scan.exam_id] = (
                            exam, answer_keys, names, student_numbers
                        )

            context = exam_context_cache[scan.exam_id]
            if context is None:
                results[marking_id] = NotFoundError("No exam found for this scan", code="exam_not_found")
                continue
            if isinstance(context, Exception):
                results[marking_id] = context
                continue
            exam, answer_keys, names, student_numbers = context

            detected_marks = detected_marks_by_marking.get(marking_id, [])

            async def match_identity(decoded_identity: DecodedIdentity) -> IdentityMatchResult:
                name_key = (
                    decoded_identity.first_name.value.strip().lower(),
                    decoded_identity.last_name.value.strip().lower(),
                )
                student_number = decoded_identity.student_id.value.strip()
                return IdentityMatchResult(
                    name=(
                        match_candidates(names.get(name_key, []))
                        if all(name_key)
                        else match_candidates([])
                    ),
                    student_id=(
                        match_candidates(student_numbers.get(student_number, []))
                        if student_number
                        else match_candidates([])
                    ),
                    student_id_available=bool(student_numbers),
                )

            try:
                async with write_db.begin_nested():
                    grade, _grade_status = await _grade_loaded_marking(
                        write_db,
                        marking,
                        detected_marks,
                        exam_template,
                        exam,
                        answer_keys,
                        match_identity,
                        commit=False,
                    )
                results[marking_id] = grade
                pending_ids.append(marking_id)
            except Exception as exc:
                results[marking_id] = exc

            if len(pending_ids) >= _GRADE_COMMIT_CHUNK_SIZE:
                try:
                    await write_db.commit()
                except Exception as exc:
                    await write_db.rollback()
                    for pending_id in pending_ids:
                        results[pending_id] = exc
                pending_ids.clear()

        if pending_ids:
            try:
                await write_db.commit()
            except Exception as exc:
                await write_db.rollback()
                for pending_id in pending_ids:
                    results[pending_id] = exc

    return results


async def apply_grade_corrections(
    db: AsyncSession, grade_id: UUID, payload: UpdateExamGradeRequest, current_user: User
) -> object:
    """Apply an instructor's manual corrections to an existing grade.

    Only the professor who owns the grade's course may change it; an admin may
    change any grade. Any other caller (a TA, or a professor for a course they
    don't own) is rejected with a ForbiddenError.

    Corrections come in three (combinable) forms:
    - corrected_answers: overrides for what the OMR detected on specific
      questions. Each corrected question is re-scored against the grade's
      answer key with the same rules as the original grading pass, and the
      total is recomputed.
    - student_id: assigns the scan to a student, who must be enrolled in the
      exam's course -- this is the fix for name/student-id flags.
    - resolve_flag: marks the grade as reviewed (status "graded", flag
      cleared). Requires a student to be assigned, since a "graded" grade
      with no student would be invisible to that student and to exam stats.
    """
    # Locked for the duration of the correction: two concurrent PATCHes on the
    # same grade must serialize, otherwise the second writer's "before"
    # snapshot (and thus its audit entry) would be stale by the time it commits.
    grade = await get_grade_by_id(db, grade_id, for_update=True)
    if not grade:
        raise NotFoundError("Grade not found", code="grade_not_found")

    answer_key = await get_answer_key_by_id(db, grade.exam_answer_key_id)
    if not answer_key:
        raise NotFoundError(
            "No answer key found for this grade", code="answer_key_not_found"
        )

    exam = await get_exam_by_id(db, answer_key.exam_id)
    if not exam:
        raise NotFoundError("No exam found for this grade", code="exam_not_found")

    course = await get_course_by_id(db, exam.course_id)
    if not course:
        raise NotFoundError("No course found for this grade", code="course_not_found")
    ensure_course_writable(course)
    if current_user.role_enum != UserRole.ADMIN and course.created_by != current_user.id:
        raise ForbiddenError(
            "You do not have permission to modify grades for this course",
            code="grade_update_forbidden",
        )

    before_total_score = grade.total_score
    before_student_id = grade.student_id
    before_status = grade.status
    before_flag_reason = grade.flag_reason
    before_question_results = dict(grade.question_results)

    if payload.corrected_answers:
        scoring_rules = answer_key.scoring_rules or {}
        default_points = scoring_rules.get("default_points_per_question", 1.0)

        # Reassigned (not mutated) so SQLAlchemy detects the JSONB change.
        question_results = dict(grade.question_results)
        for q_num_str, corrected in payload.corrected_answers.items():
            ak_item = answer_key.answer_key.get(q_num_str)
            if ak_item is None:
                raise BadRequestError(
                    f"Question {q_num_str} is not in the answer key",
                    code="question_not_in_key",
                )

            student_answers = sorted(corrected)
            correct_answers = sorted(ak_item.get("correct_choices", []))
            grading_type = ak_item.get("grading_type", "single")
            points = ak_item.get("points") or default_points
            partial_weights = ak_item.get("partial_weights") or {}

            score = _score_question(
                student_answers, correct_answers, grading_type, points, partial_weights
            )
            question_results[q_num_str] = {
                "grading_type": grading_type,
                "student_answers": student_answers,
                "correct_answers": correct_answers,
                "correct": score >= points,
                "score": round(score, 4),
                "max_score": points,
                # A manual correction means a human has now looked at this
                # question's marks directly (see FlaggedScanReview), so it no
                # longer needs the auto-grader's ambiguity flag -- otherwise
                # confirming a genuine multi-mark would just re-flag it and
                # the review queue could never be cleared.
                "ambiguous": False,
            }

        grade.question_results = question_results
        grade.total_score = round(
            sum(result["score"] for result in question_results.values()), 4
        )

    if payload.student_id is not None:
        enrolment = await get_student_enrolment(db, exam.course_id, payload.student_id)
        if not enrolment:
            raise BadRequestError(
                "Student is not enrolled in this exam's course",
                code="student_not_enrolled",
            )

        if payload.student_id != before_student_id:
            # Different grade rows can be corrected concurrently, so the row
            # lock on `grade` alone is insufficient. Serialize all checks for
            # this exam/student pair before deciding whether confirmation is
            # required.
            await acquire_student_grade_lock(db, exam.id, payload.student_id)
            conflicting_grades = [
                other
                for other in await list_grades_by_exam(db, exam.id)
                if other.id != grade.id and other.student_id == payload.student_id
            ]
            if conflicting_grades and not payload.confirm_duplicate_assignment:
                raise ConflictError(
                    "This student already has a grade assigned for this exam",
                    code="duplicate_student_assignment",
                    details={"grade_ids": [str(other.id) for other in conflicting_grades]},
                )
        grade.student_id = payload.student_id

    if payload.resolve_flag:
        if not grade.student_id:
            raise BadRequestError(
                "Assign a student before resolving a flagged grade",
                code="student_required_to_resolve",
            )
        grade.status = "graded"
        grade.flag_reason = None

    changes: dict = {}
    if payload.corrected_answers:
        questions = {
            q_num: {"before": before_question_results.get(q_num), "after": grade.question_results[q_num]}
            for q_num in payload.corrected_answers
            if before_question_results.get(q_num) != grade.question_results[q_num]
        }
        if questions:
            changes["questions"] = questions
    if payload.student_id is not None and payload.student_id != before_student_id:
        changes["student_id"] = {
            "before": str(before_student_id) if before_student_id else None,
            "after": str(payload.student_id),
        }
    if payload.resolve_flag and (before_status != grade.status or before_flag_reason != grade.flag_reason):
        changes["status"] = {"before": before_status, "after": grade.status}
        changes["flag_reason"] = {"before": before_flag_reason, "after": grade.flag_reason}

    if changes:
        await create_audit_entry(
            db,
            exam_grade_id=grade.id,
            actor_user_id=current_user.id,
            event_type="manual_correction",
            previous_total_score=before_total_score,
            new_total_score=grade.total_score,
            changes=changes,
        )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await db.refresh(grade)
    return grade


# --- Viewing grades: response shaping, access control, and annotations ---
#
# Everything below serves the read side of the grading API (routers/grading_router.py):
# assembling ExamGradeResponse objects, deciding who may see a given grade, and
# building the per-page annotation/identity/version data the annotated-exam
# view overlays on a scan image.


def _question_sort_key(question_id: str) -> tuple[int, int | str]:
    return (0, int(question_id)) if question_id.isdigit() else (1, question_id)


def _with_section_results(
    grade,
    sections: list[dict],
    page_count: int | None,
    exam_id,
    exam_version: str | None = None,
    hide_correct_answers: bool = False,
) -> ExamGradeResponse:
    response = ExamGradeResponse.model_validate(grade).model_copy(
        update={"page_count": page_count, "exam_id": exam_id, "exam_version": exam_version}
    )
    question_results = response.question_results
    if hide_correct_answers:
        # Students see their own results, not the answer key: strip it here
        # rather than trust every caller of this response to hide it in the
        # UI. See also get_grade_page_annotations_view's identical guard.
        question_results = {
            question_id: result.model_copy(update={"correct_answers": []})
            for question_id, result in question_results.items()
        }
        response = response.model_copy(update={"question_results": question_results})
    section_specs: list[tuple[str, str, str | None, list[str]]] = []
    assigned_questions: set[str] = set()

    for section in sections:
        question_ids = [
            str(question_id)
            for question_id in section.get("question_ids", [])
            if str(question_id) in question_results
        ]
        if not question_ids:
            continue
        assigned_questions.update(question_ids)
        section_specs.append(
            (
                str(section.get("id", "section")),
                str(section.get("name", "Section")),
                section.get("type"),
                question_ids,
            )
        )

    unassigned = sorted(
        set(question_results) - assigned_questions,
        key=_question_sort_key,
    )
    if unassigned:
        section_specs.append(("other-questions", "Other questions", None, unassigned))

    section_results = [
        GradeSectionResult(
            id=section_id,
            name=name,
            type=section_type,
            question_ids=question_ids,
            score=round(sum(question_results[q].score for q in question_ids), 4),
            max_score=round(
                sum(question_results[q].max_score for q in question_ids), 4
            ),
        )
        for section_id, name, section_type, question_ids in section_specs
    ]

    return response.model_copy(update={"section_results": section_results})


async def build_grade_responses(
    db: AsyncSession, grades: list, hide_correct_answers: bool = False
) -> list[ExamGradeResponse]:
    sections_by_key = await get_template_sections_by_answer_key_ids(
        db, [grade.exam_answer_key_id for grade in grades]
    )
    page_counts_by_marking = await get_page_counts_by_marking_ids(
        db, [grade.omr_marking_id for grade in grades]
    )
    exam_ids_by_key = await get_exam_ids_by_answer_key_ids(
        db, [grade.exam_answer_key_id for grade in grades]
    )
    exam_versions_by_key = await get_exam_versions_by_answer_key_ids(
        db, [grade.exam_answer_key_id for grade in grades]
    )
    return [
        _with_section_results(
            grade,
            sections_by_key.get(grade.exam_answer_key_id, []),
            page_counts_by_marking.get(grade.omr_marking_id),
            exam_ids_by_key.get(grade.exam_answer_key_id),
            exam_versions_by_key.get(grade.exam_answer_key_id),
            hide_correct_answers=hide_correct_answers,
        )
        for grade in grades
    ]


async def build_grade_response(
    db: AsyncSession, grade, hide_correct_answers: bool = False
) -> ExamGradeResponse:
    return (await build_grade_responses(db, [grade], hide_correct_answers=hide_correct_answers))[0]


async def _can_access_grade(db: AsyncSession, user: User, grade) -> bool:
    if user.role_enum in {UserRole.PROFESSOR, UserRole.ADMIN}:
        return True
    if user.role_enum != UserRole.STUDENT or grade.student_id != user.id:
        return False
    exam = await get_exam_for_grade(db, grade.exam_answer_key_id)
    return exam is not None and exam.released


async def _can_view_grade_history(db: AsyncSession, user: User, grade) -> bool:
    """Like _can_access_grade, but scopes staff access to the course that owns
    the grade: a professor from an unrelated course should not be able to
    learn who made a correction on a grade they have no business viewing.

    A student is also held to the same release gate as _can_access_grade --
    otherwise the history endpoint would leak previous/new scores for a grade
    the exam-grades endpoints are still hiding pre-release.
    """
    if user.role_enum == UserRole.ADMIN:
        return True

    answer_key = await get_answer_key_by_id(db, grade.exam_answer_key_id)
    if not answer_key:
        return False
    exam = await get_exam_by_id(db, answer_key.exam_id)
    if not exam:
        return False

    if user.role_enum == UserRole.STUDENT:
        return grade.student_id == user.id and exam.released

    course = await get_course_by_id(db, exam.course_id)
    if not course:
        return False
    if course.created_by == user.id:
        return True

    enrolment = await get_enrolment(db, course.id, user.id)
    return enrolment is not None and enrolment.role == "professor"


def _filter_visible_grades(user: User, grades, released: bool):
    if user.role_enum in {UserRole.PROFESSOR, UserRole.ADMIN}:
        return grades
    if user.role_enum == UserRole.STUDENT and released:
        return [grade for grade in grades if grade.student_id == user.id]
    return []


async def _get_accessible_grade(db: AsyncSession, grade_id: UUID, current_user: User):
    grade = await get_grade_by_id(db, grade_id)
    if not grade:
        raise NotFoundError("Grade not found", code="grade_not_found")
    if not await _can_access_grade(db, current_user, grade):
        raise ForbiddenError("Insufficient permissions", code="insufficient_permissions")
    return grade


async def get_grade_for_marking_view(db: AsyncSession, marking_id: UUID) -> ExamGradeResponse:
    grade = await get_grade_by_omr_marking(db, marking_id)
    if not grade:
        raise NotFoundError("No grade found for this marking", code="grade_not_found")
    return await build_grade_response(db, grade)


async def get_grade_view(db: AsyncSession, grade_id: UUID, current_user: User) -> ExamGradeResponse:
    grade = await _get_accessible_grade(db, grade_id, current_user)
    return await build_grade_response(
        db, grade, hide_correct_answers=current_user.role_enum == UserRole.STUDENT
    )


async def list_exam_grades_view(
    db: AsyncSession, exam_id: UUID, current_user: User
) -> list[ExamGradeResponse]:
    exam = await get_exam_by_id(db, exam_id)
    released = exam is not None and exam.released
    grades = _filter_visible_grades(
        current_user, await list_grades_by_exam(db, exam_id), released
    )
    return await build_grade_responses(
        db, grades, hide_correct_answers=current_user.role_enum == UserRole.STUDENT
    )


async def get_grade_history_view(
    db: AsyncSession, grade_id: UUID, current_user: User
) -> list[GradeAuditEntryResponse]:
    grade = await get_grade_by_id(db, grade_id)
    if not grade:
        raise NotFoundError("Grade not found", code="grade_not_found")
    if not await _can_view_grade_history(db, current_user, grade):
        raise ForbiddenError("Insufficient permissions", code="insufficient_permissions")

    entries = await list_audit_entries_by_grade(db, grade_id)

    # Students may view their own grade's history, but the identity of the
    # staff member behind a correction is not theirs to see.
    is_staff = current_user.role_enum in {UserRole.PROFESSOR, UserRole.ADMIN}
    actor_names: dict[UUID, str] = {}
    if is_staff:
        actor_ids = {entry.actor_user_id for entry in entries if entry.actor_user_id is not None}
        actors = await get_users_by_ids(db, list(actor_ids))
        actor_names = {user.id: user.full_name for user in actors}

    return [
        GradeAuditEntryResponse(
            id=entry.id,
            exam_grade_id=entry.exam_grade_id,
            actor_user_id=entry.actor_user_id if is_staff else None,
            actor_name=actor_names.get(entry.actor_user_id) if is_staff else None,
            event_type=entry.event_type,
            previous_total_score=entry.previous_total_score,
            new_total_score=entry.new_total_score,
            changes=entry.changes,
            created_at=entry.created_at,
        )
        for entry in entries
    ]


async def get_grade_question_snippet_bytes(
    db: AsyncSession, grade_id: UUID, question_number: int, current_user: User
) -> bytes:
    grade = await _get_accessible_grade(db, grade_id, current_user)

    marking = await get_omr_marking_by_id(db, grade.omr_marking_id)
    if not marking:
        raise NotFoundError("OMR marking not found", code="marking_not_found")

    template = await get_omr_template_by_id(db, marking.omr_template_id)
    if not template or not template.mark_template_id:
        raise NotFoundError("OMR marking template not found", code="omr_template_not_found")

    scan = await get_scan_for_marking(db, marking)
    if not scan or not scan.omr_scan_id:
        raise NotFoundError("OMR scan not found", code="omr_scan_not_found")

    try:
        return await get_question_snippet(template.mark_template_id, scan.omr_scan_id, f"Q{question_number}")
    except OMRClientError as exc:
        raise NotFoundError("Question snippet not found", code="snippet_not_found") from exc


async def get_grade_page_annotations_view(
    db: AsyncSession, grade_id: UUID, page_index: int, current_user: User
) -> list[QuestionAnnotation]:
    """Per-question coordinates and grade for every answer question on one
    page of a grade's scan.

    This is what a frontend overlays on that page's image, served by
    get_grade_page_image_bytes below.
    """
    grade = await _get_accessible_grade(db, grade_id, current_user)
    # Students see their own results, not the answer key.
    hide_correct_answers = current_user.role_enum == UserRole.STUDENT

    marks = await get_question_marks_for_page(db, grade.omr_marking_id, page_index)

    annotations = []
    for mark in marks:
        result = grade.question_results.get(str(mark.field_index))
        if result is None:
            # No answer-key entry for this question (e.g. an unscored bubble
            # row), so there's nothing to annotate it with.
            continue
        # mark.boxes' selected flags are the raw OMR detection, frozen at scan
        # time. A manual correction updates result["student_answers"] but
        # never that record, so they can go stale. Re-derive selected from
        # the current (possibly corrected) answer instead of trusting it.
        corrected_labels = set(result["student_answers"])
        boxes = [
            OptionBox(**{**box, "selected": box["label"] in corrected_labels})
            for box in mark.boxes
        ]
        annotations.append(QuestionAnnotation(
            question_id=str(mark.field_index),
            bounds=mark.bounds,
            boxes=boxes,
            confidence=mark.confidence_score,
            correct=result["correct"],
            ambiguous=result["ambiguous"],
            score=result["score"],
            max_score=result["max_score"],
            student_answers=result["student_answers"],
            correct_answers=[] if hide_correct_answers else result["correct_answers"],
        ))
    return annotations


def _build_identity_annotations(marks: list) -> IdentityAnnotations:
    decoded = decode_identity_fields(marks)
    return IdentityAnnotations(
        fields=[
            IdentityFieldAnnotation(
                field_type=mark.field_type,
                field_index=mark.field_index,
                bounds=mark.bounds,
                boxes=mark.boxes,
                confidence=mark.confidence_score,
            )
            for mark in marks
        ],
        last_name=decoded.last_name.value,
        first_name=decoded.first_name.value,
        student_id=decoded.student_id.value,
        page_index=marks[0].page_index if marks else None,
    )


async def get_grade_identity_view(
    db: AsyncSession, grade_id: UUID, current_user: User
) -> IdentityAnnotations:
    """The grade's name/student-ID bubble fields and decoded values,
    regardless of which page they're on. Used for a persistent "identify
    student" card, including which page to jump to.
    """
    grade = await _get_accessible_grade(db, grade_id, current_user)
    marks = await get_identity_marks(db, grade.omr_marking_id)
    return _build_identity_annotations(marks)


async def get_grade_page_identity_view(
    db: AsyncSession, grade_id: UUID, page_index: int, current_user: User
) -> IdentityAnnotations:
    """Per-character name/student-ID bubble coordinates for one page of a
    grade's scan, plus what OMR decoded them as. Empty (with blank decoded
    strings) on any page without name/ID fields, e.g. a plain question page.
    """
    grade = await _get_accessible_grade(db, grade_id, current_user)
    marks = await get_identity_marks_for_page(db, grade.omr_marking_id, page_index)
    return _build_identity_annotations(marks)


async def get_grade_page_version_view(
    db: AsyncSession, grade_id: UUID, page_index: int, current_user: User
) -> VersionAnnotation:
    """The version-selector bubble on one page of a grade's scan, if this
    template has one and it's on this page, plus what OMR decoded it as.
    Read-only: see VersionAnnotation for why.
    """
    grade = await _get_accessible_grade(db, grade_id, current_user)

    mark = await get_version_mark_for_page(db, grade.omr_marking_id, page_index)
    if not mark:
        return VersionAnnotation(field=None, detected_version=None)

    values = split_detected_value(mark.detected_value)
    return VersionAnnotation(
        field=IdentityFieldAnnotation(
            field_type=mark.field_type,
            field_index=mark.field_index,
            bounds=mark.bounds,
            boxes=mark.boxes,
            confidence=mark.confidence_score,
        ),
        detected_version=values[0] if len(values) == 1 else None,
    )


async def get_grade_page_image_bytes(
    db: AsyncSession, grade_id: UUID, page_index: int, current_user: User
) -> bytes:
    grade = await _get_accessible_grade(db, grade_id, current_user)

    marking = await get_omr_marking_by_id(db, grade.omr_marking_id)
    if not marking:
        raise NotFoundError("OMR marking not found", code="marking_not_found")

    scan = await get_scan_for_marking(db, marking)
    if not scan or not scan.omr_scan_id:
        raise NotFoundError("OMR scan not found", code="omr_scan_not_found")

    try:
        return await get_scan_page_image(scan.omr_scan_id, page_index)
    except OMRClientError as exc:
        raise NotFoundError("Page image not found", code="page_image_not_found") from exc
