from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from dependencies.auth_dep import get_current_user, require_staff
from errors.exceptions import ForbiddenError, NotFoundError
from models.user import User, UserRole
from repositories.exam_grades import get_grade_by_id
from repositories.review_request_audit_entries import list_review_request_audit_entries
from repositories.review_requests import (
    create_review_request,
    get_review_request_by_id,
    is_staff_authorized_for_review_request,
    list_by_student,
    list_for_staff,
    update_review_request,
)
from repositories.users import get_users_by_ids
from schemas.review_requests import (
    CreateReviewRequestRequest,
    ReviewRequestAuditEntryResponse,
    ReviewRequestEnrichedResponse,
    ReviewRequestResponse,
    ReviewRequestStudentResponse,
    UpdateReviewRequestRequest,
)

router = APIRouter(prefix="/api", tags=["Review Requests"])


@router.post(
    "/grades/{grade_id}/review-requests",
    response_model=list[ReviewRequestResponse],
    status_code=status.HTTP_201_CREATED,
)
async def submit_review_request(
    grade_id: UUID,
    payload: CreateReviewRequestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    grade = await get_grade_by_id(db, grade_id)
    if not grade:
        raise NotFoundError("Grade not found", code="grade_not_found")
    if grade.student_id != current_user.id:
        raise ForbiddenError("Insufficient permissions", code="insufficient_permissions")

    return await create_review_request(
        db,
        exam_grade_id=grade_id,
        student_id=current_user.id,
        question_numbers=payload.question_numbers,
        student_comment=payload.student_comment,
        proposed_scores=payload.proposed_scores,
    )


@router.get(
    "/review-requests",
    response_model=list[ReviewRequestEnrichedResponse],
    status_code=status.HTTP_200_OK,
)
async def list_review_requests_for_staff(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    is_admin = current_user.role_enum == UserRole.ADMIN
    rows = await list_for_staff(db, current_user.id, is_admin)
    return [
        ReviewRequestEnrichedResponse(
            **ReviewRequestResponse.model_validate(review).model_dump(),
            student_name=student_name,
            course_id=course_id,
            course_code=course_code,
            term=term,
            exam_name=exam_name,
            max_score=max_score,
        )
        for review, student_name, course_id, course_code, term, exam_name, max_score in rows
    ]


@router.get(
    "/review-requests/me",
    response_model=list[ReviewRequestStudentResponse],
    status_code=status.HTTP_200_OK,
)
async def my_review_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await list_by_student(db, current_user.id)
    return [
        ReviewRequestStudentResponse(
            **ReviewRequestResponse.model_validate(review).model_dump(),
            course_id=course_id,
        )
        for review, course_id in rows
    ]


@router.get(
    "/review-requests/{review_request_id}",
    response_model=ReviewRequestResponse,
    status_code=status.HTTP_200_OK,
)
async def get_review_request(
    review_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    review = await get_review_request_by_id(db, review_request_id)
    if not review:
        raise NotFoundError("Review request not found", code="review_request_not_found")
    return review


@router.get(
    "/review-requests/{review_request_id}/history",
    response_model=list[ReviewRequestAuditEntryResponse],
    status_code=status.HTTP_200_OK,
)
async def get_review_request_history(
    review_request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = await get_review_request_by_id(db, review_request_id)
    if not review:
        raise NotFoundError("Review request not found", code="review_request_not_found")

    is_staff = current_user.role_enum in {UserRole.ADMIN, UserRole.PROFESSOR}
    can_view = review.student_id == current_user.id
    if not can_view and is_staff:
        can_view = await is_staff_authorized_for_review_request(
            db,
            review_request_id=review_request_id,
            user_id=current_user.id,
            is_admin=current_user.role_enum == UserRole.ADMIN,
        )
    if not can_view:
        raise ForbiddenError("Insufficient permissions", code="insufficient_permissions")

    entries = await list_review_request_audit_entries(db, review_request_id)
    actor_names: dict[UUID, str] = {}
    if is_staff:
        actor_ids = {entry.actor_user_id for entry in entries if entry.actor_user_id is not None}
        actors = await get_users_by_ids(db, list(actor_ids))
        actor_names = {actor.id: actor.full_name for actor in actors}

    return [
        ReviewRequestAuditEntryResponse(
            id=entry.id,
            review_request_id=entry.review_request_id,
            actor_user_id=entry.actor_user_id if is_staff else None,
            actor_name=actor_names.get(entry.actor_user_id) if is_staff else None,
            event_type=entry.event_type,
            changes=entry.changes,
            created_at=entry.created_at,
        )
        for entry in entries
    ]


@router.patch(
    "/review-requests/{review_request_id}",
    response_model=list[ReviewRequestResponse],
    status_code=status.HTTP_200_OK,
)
async def resolve_review_request(
    review_request_id: UUID,
    payload: UpdateReviewRequestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    batch = await update_review_request(
        db,
        review_request_id=review_request_id,
        user_id=current_user.id,
        is_admin=current_user.role_enum == UserRole.ADMIN,
        status=payload.status,
        instructor_response=payload.instructor_response,
        proposed_correct=payload.proposed_correct,
        proposed_scores=payload.proposed_scores,
    )
    if not batch:
        raise NotFoundError("Review request not found", code="review_request_not_found")
    return batch
