from datetime import datetime, timezone
import logging
import math
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import BadRequestError, ForbiddenError
from models.course import Course
from models.academic_term import AcademicTerm
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.review_request import ReviewRequest
from models.user import User
from repositories.exam_grades import get_grade_by_id
from repositories.grade_audit_entries import create_audit_entry
from services.notifications import notify_course_staff, notify_user
from services.course_lifecycle import (
    ensure_grade_course_writable,
    ensure_review_request_course_writable,
)

# A repository importing another repository is an exception to this file's
# usual layering. It mirrors how grading_service.py writes to
# grade_audit_entries one layer up. Review requests have no service layer of
# their own for the router to call through instead.
from repositories.review_request_audit_entries import create_review_request_audit_entry

logger = logging.getLogger(__name__)


async def _apply_grade_adjustment_on_resolve(
    db: AsyncSession,
    batch: list[ReviewRequest],
    actor_user_id: UUID,
    proposed_correct: dict[str, bool],
    proposed_scores: dict[str, float],
) -> None:
    """Applies staff's correct/incorrect decision to each disputed question
    in the grade's question_results (not just the grade's total) -- the same
    shape services.grading_service.apply_grade_corrections uses for manual
    corrections, since a resolved review request is effectively the same
    kind of human override.

    Each question's new score defaults to full/zero credit based on its own
    correct/incorrect decision; an explicit entry in proposed_scores (bounded
    by that question's own max_score) overrides just that question's score
    instead, for edge cases the simple default doesn't capture (e.g. partial
    credit). The grade's total is recomputed as the sum of every question's
    score. Mutates each row's proposed_score in place to reflect the score
    actually applied to its question.
    """
    review = batch[0]
    grade = await get_grade_by_id(db, review.exam_grade_id, for_update=True)
    if grade is None:
        raise BadRequestError(
            "The linked grade could not be found",
            code="exam_grade_not_found",
        )

    question_results = dict(grade.question_results)
    changed_questions: dict[str, dict] = {}

    for row in batch:
        current = question_results.get(row.question_number)
        if current is None:
            raise BadRequestError(
                f"Question {row.question_number} is not in this grade",
                code="question_not_in_grade",
            )

        is_correct = proposed_correct[row.question_number]
        override = proposed_scores.get(row.question_number)
        if override is not None:
            if override < 0 or override > current["max_score"]:
                raise BadRequestError(
                    f"Proposed score for question {row.question_number} must be "
                    f"between 0 and {current['max_score']}",
                    code="invalid_proposed_score",
                )
            new_score = round(float(override), 4)
        else:
            new_score = current["max_score"] if is_correct else 0.0

        updated = {
            **current,
            "correct": is_correct,
            "score": new_score,
            # A human has now looked at this question directly, so it no
            # longer needs the auto-grader's ambiguity flag -- otherwise
            # confirming a genuine multi-mark would just re-flag it.
            "ambiguous": False,
        }
        row.proposed_score = new_score
        if updated != current:
            question_results[row.question_number] = updated
            changed_questions[row.question_number] = {
                "before": current,
                "after": updated,
            }

    if not changed_questions:
        return

    previous_total_score = grade.total_score
    grade.question_results = question_results
    grade.total_score = round(sum(r["score"] for r in question_results.values()), 4)

    await create_audit_entry(
        db,
        exam_grade_id=grade.id,
        actor_user_id=actor_user_id,
        event_type="manual_correction",
        previous_total_score=previous_total_score,
        new_total_score=grade.total_score,
        changes={
            "questions": changed_questions,
            "total_score": {"before": previous_total_score, "after": grade.total_score},
            "source": {
                "before": None,
                "after": "review_request_resolution",
            },
            "review_request_id": {
                "before": None,
                "after": str(review.id),
            },
        },
    )


async def _course_id_for_grade(db: AsyncSession, exam_grade_id: UUID) -> UUID | None:
    query = (
        select(Exam.course_id)
        .select_from(ExamGrade)
        .join(ExamAnswerKey, ExamAnswerKey.id == ExamGrade.exam_answer_key_id)
        .join(Exam, Exam.id == ExamAnswerKey.exam_id)
        .where(ExamGrade.id == exam_grade_id)
    )
    return (await db.execute(query)).scalar_one_or_none()


async def _exam_released_for_grade(db: AsyncSession, exam_grade_id: UUID) -> bool | None:
    query = (
        select(Exam.released)
        .select_from(ExamGrade)
        .join(ExamAnswerKey, ExamAnswerKey.id == ExamGrade.exam_answer_key_id)
        .join(Exam, Exam.id == ExamAnswerKey.exam_id)
        .where(ExamGrade.id == exam_grade_id)
    )
    return (await db.execute(query)).scalar_one_or_none()


async def create_review_request(
    db: AsyncSession,
    exam_grade_id: UUID,
    student_id: UUID,
    question_numbers: list[str],
    student_comment: str | None,
    proposed_scores: dict[str, float],
) -> list[ReviewRequest]:
    """Creates one row per question number. When there's more than one, all
    the rows share a batch_id so staff can view and resolve them together.
    """
    await ensure_grade_course_writable(db, exam_grade_id)
    # A student can't see a grade before its exam is released (see
    # grading_router.py's _filter_visible_grades), so a request against an
    # unreleased exam can only happen via a direct API call. Reject it
    # rather than let a re-grade badge appear before students can see why.
    if not await _exam_released_for_grade(db, exam_grade_id):
        raise BadRequestError(
            "Re-grade requests can only be submitted once results are released",
            code="exam_not_released",
        )

    grade = await db.execute(
        select(ExamGrade.question_results).where(ExamGrade.id == exam_grade_id)
    )
    grade_row = grade.one_or_none()
    if grade_row is None:
        raise BadRequestError(
            "The linked grade could not be found",
            code="exam_grade_not_found",
        )

    # One outstanding request per question at a time -- otherwise a second
    # submission on the same question before staff resolve the first would
    # leave two pending rows both claiming it, with no clear "current"
    # request for staff to act on.
    existing_pending = await db.execute(
        select(ReviewRequest.question_number).where(
            ReviewRequest.exam_grade_id == exam_grade_id,
            ReviewRequest.status == "pending",
            ReviewRequest.question_number.in_(question_numbers),
        )
    )
    already_pending = sorted({row[0] for row in existing_pending.all()}, key=int)
    if already_pending:
        raise BadRequestError(
            f"Question(s) {', '.join(already_pending)} already have a pending "
            "re-grade request",
            code="review_request_already_pending",
        )

    batch_id = uuid4() if len(question_numbers) > 1 else None
    reviews = []
    for question_number in question_numbers:
        question_result = grade_row.question_results.get(question_number)
        if question_result is None:
            raise BadRequestError(
                f"Question {question_number} is not in this grade",
                code="question_not_in_grade",
            )
        proposed = proposed_scores.get(question_number)
        if proposed is not None and (proposed < 0 or proposed > question_result["max_score"]):
            raise BadRequestError(
                f"Proposed score for question {question_number} must be "
                f"between 0 and {question_result['max_score']}",
                code="invalid_proposed_score",
            )
        reviews.append(
            ReviewRequest(
                exam_grade_id=exam_grade_id,
                student_id=student_id,
                batch_id=batch_id,
                question_number=question_number,
                student_comment=student_comment,
                current_score=question_result["score"],
                proposed_score=proposed,
            )
        )
    db.add_all(reviews)
    await db.commit()
    for review in reviews:
        await db.refresh(review)

    try:
        course_id = await _course_id_for_grade(db, exam_grade_id)
        if course_id is not None:
            question_label = (
                f"Question {question_numbers[0]}"
                if len(question_numbers) == 1
                else f"Questions {', '.join(question_numbers)}"
            )
            await notify_course_staff(
                db,
                course_id=course_id,
                type="review_request_created",
                title="New re-grade request",
                body=question_label,
                link_path="/regrade",
                link_query=f"requestId={reviews[0].id}",
                exclude_user_id=student_id,
            )
    except Exception:
        logger.exception("Failed to send review request notification for %s", reviews[0].id)

    return reviews


async def get_review_request_by_id(
    db: AsyncSession, review_request_id: UUID, *, for_update: bool = False
) -> ReviewRequest | None:
    query = select(ReviewRequest).where(ReviewRequest.id == review_request_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def list_by_grade(
    db: AsyncSession, exam_grade_id: UUID
) -> list[ReviewRequest]:
    result = await db.execute(
        select(ReviewRequest)
        .where(ReviewRequest.exam_grade_id == exam_grade_id)
        .order_by(ReviewRequest.created_at)
    )
    return list(result.scalars().all())


async def list_by_student(
    db: AsyncSession, student_id: UUID
) -> list[tuple[ReviewRequest, UUID]]:
    query = (
        select(ReviewRequest, Course.id.label("course_id"))
        .join(ExamGrade, ExamGrade.id == ReviewRequest.exam_grade_id)
        .join(ExamAnswerKey, ExamAnswerKey.id == ExamGrade.exam_answer_key_id)
        .join(Exam, Exam.id == ExamAnswerKey.exam_id)
        .join(Course, Course.id == Exam.course_id)
        .where(ReviewRequest.student_id == student_id)
        .order_by(ReviewRequest.created_at.desc())
    )
    result = await db.execute(query)
    return [tuple(row) for row in result.all()]


async def _is_staff_authorized_for_review_request(
    db: AsyncSession, review_request_id: UUID, user_id: UUID, is_admin: bool
) -> bool:
    if is_admin:
        return True

    query = (
        select(Course.created_by, Enrolment.id)
        .select_from(ReviewRequest)
        .join(ExamGrade, ExamGrade.id == ReviewRequest.exam_grade_id)
        .join(ExamAnswerKey, ExamAnswerKey.id == ExamGrade.exam_answer_key_id)
        .join(Exam, Exam.id == ExamAnswerKey.exam_id)
        .join(Course, Course.id == Exam.course_id)
        .outerjoin(
            Enrolment,
            (Enrolment.course_id == Course.id)
            & (Enrolment.user_id == user_id)
            & (Enrolment.role == "professor"),
        )
        .where(ReviewRequest.id == review_request_id)
    )
    row = (await db.execute(query)).first()
    if row is None:
        return False
    created_by, enrolment_id = row
    return created_by == user_id or enrolment_id is not None


async def is_staff_authorized_for_review_request(
    db: AsyncSession, review_request_id: UUID, user_id: UUID, is_admin: bool
) -> bool:
    return await _is_staff_authorized_for_review_request(
        db,
        review_request_id=review_request_id,
        user_id=user_id,
        is_admin=is_admin,
    )


async def update_review_request(
    db: AsyncSession,
    review_request_id: UUID,
    user_id: UUID,
    is_admin: bool,
    status: str,
    instructor_response: str,
    proposed_correct: dict[str, bool] | None = None,
    proposed_scores: dict[str, float] | None = None,
) -> list[ReviewRequest] | None:
    status = str(status)
    if status not in ("resolved", "rejected"):
        raise BadRequestError(
            "Review requests may only be resolved or rejected",
            code="invalid_review_request_transition",
        )

    # Serialize decision changes so each audit entry is based on the state
    # committed by the preceding updater.
    review = await get_review_request_by_id(db, review_request_id, for_update=True)
    if not review:
        return None

    if not await _is_staff_authorized_for_review_request(db, review_request_id, user_id, is_admin):
        raise ForbiddenError("Not authorized to update this review request", code="forbidden")
    await ensure_review_request_course_writable(db, review_request_id)

    # Every row created from the same submission is resolved as one request,
    # so staff see and act on the whole batch together, but each question
    # gets its own correct/incorrect decision and optional score.
    batch = [review]
    if review.batch_id is not None:
        siblings = await db.execute(
            select(ReviewRequest)
            .where(ReviewRequest.batch_id == review.batch_id, ReviewRequest.id != review.id)
            .with_for_update()
        )
        batch += list(siblings.scalars().all())

    proposed_correct = proposed_correct or {}
    proposed_scores = proposed_scores or {}

    if status == "resolved":
        missing = [row.question_number for row in batch if row.question_number not in proposed_correct]
        if missing:
            raise BadRequestError(
                f"Mark question(s) {', '.join(sorted(missing, key=int))} correct or "
                "incorrect to resolve this request",
                code="proposed_correct_required",
            )

    for score in proposed_scores.values():
        if not math.isfinite(score):
            raise BadRequestError(
                "Proposed score must be a finite number",
                code="invalid_proposed_score",
            )
    normalized_scores = {q: round(float(s), 4) for q, s in proposed_scores.items()}

    # Snapshotted up front because _apply_grade_adjustment_on_resolve mutates
    # each row's proposed_score in place (reflecting the score actually
    # applied, which may differ from what was passed in when it was omitted
    # and defaulted), so comparing against the live attribute afterwards
    # would always see it as "changed."
    before_by_row = {
        row.id: (row.status, row.instructor_response, row.proposed_correct, row.proposed_score)
        for row in batch
    }

    resolved_at = datetime.now(timezone.utc) if status != review.status else None
    for row in batch:
        row.status = status
        row.instructor_response = instructor_response
        if row.question_number in proposed_correct:
            row.proposed_correct = proposed_correct[row.question_number]
        if row.question_number in normalized_scores:
            row.proposed_score = normalized_scores[row.question_number]
        if resolved_at is not None:
            row.resolved_at = resolved_at

    if status == "resolved":
        await _apply_grade_adjustment_on_resolve(
            db,
            batch=batch,
            actor_user_id=user_id,
            proposed_correct=proposed_correct,
            proposed_scores=normalized_scores,
        )

    # One audit entry per row that actually changed, so an exact retry is
    # idempotent (no fabricated event) and a row untouched by this call (a
    # sibling question that already had its own decision) doesn't get a
    # misleading new entry either.
    any_changes = False
    for row in batch:
        before_status, before_response, before_correct, before_score = before_by_row[row.id]
        row_changes: dict = {}
        if before_status != row.status:
            row_changes["status"] = {"before": before_status, "after": row.status}
        if before_response != row.instructor_response:
            row_changes["instructor_response"] = {"before": before_response, "after": row.instructor_response}
        if before_correct != row.proposed_correct:
            row_changes["proposed_correct"] = {"before": before_correct, "after": row.proposed_correct}
        if before_score != row.proposed_score:
            row_changes["proposed_score"] = {"before": before_score, "after": row.proposed_score}

        if not row_changes:
            continue
        any_changes = True
        await create_review_request_audit_entry(
            db,
            review_request_id=row.id,
            actor_user_id=user_id,
            event_type=status,
            changes=row_changes,
        )

    if not any_changes:
        await db.commit()
        for row in batch:
            await db.refresh(row)
        return batch

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for row in batch:
        await db.refresh(row)

    try:
        question_label = (
            f"question {review.question_number}"
            if len(batch) == 1
            else f"{len(batch)} questions"
        )
        await notify_user(
            db,
            recipient_user_id=review.student_id,
            type="review_request_resolved",
            title=f"Your re-grade request for {question_label} was {status}",
            body=instructor_response,
            link_path="/regrade",
            link_query=f"requestId={review.id}",
        )
    except Exception:
        logger.exception("Failed to send review resolution notification for %s", review.id)

    return batch


async def list_for_staff(
    db: AsyncSession, user_id: UUID, is_admin: bool
) -> list[tuple[ReviewRequest, str, UUID, str, str, str, float]]:
    query = (
        select(
            ReviewRequest,
            func.concat(User.first_name, ' ', User.last_name).label("student_name"),
            Course.id.label("course_id"),
            Course.name.label("course_code"),
            AcademicTerm.name.label("term"),
            Exam.name.label("exam_name"),
            ExamGrade.max_score.label("max_score"),
        )
        .join(User, User.id == ReviewRequest.student_id)
        .join(ExamGrade, ExamGrade.id == ReviewRequest.exam_grade_id)
        .join(ExamAnswerKey, ExamAnswerKey.id == ExamGrade.exam_answer_key_id)
        .join(Exam, Exam.id == ExamAnswerKey.exam_id)
        .join(Course, Course.id == Exam.course_id)
        .join(AcademicTerm, AcademicTerm.id == Course.academic_term_id)
        .order_by(ReviewRequest.created_at.desc())
    )

    if not is_admin:
        query = query.outerjoin(
            Enrolment,
            (Enrolment.course_id == Course.id)
            & (Enrolment.user_id == user_id)
            & (Enrolment.role == "professor"),
        ).where((Course.created_by == user_id) | (Enrolment.id != None)).distinct()  # noqa: E711

    result = await db.execute(query)
    return [tuple(row) for row in result.all()]
