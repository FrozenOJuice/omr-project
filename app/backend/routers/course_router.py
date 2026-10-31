from uuid import UUID

from fastapi import APIRouter, Depends, Query, status, File, UploadFile, HTTPException

from dependencies.auth_dep import get_current_user
from db.session import get_db
from models.user import User
from schemas.course_schema import AddStudentRequest
from schemas.course_schema import ArchiveCourseRequest
from schemas.course_schema import CourseResponse
from schemas.course_schema import CreateCourseRequest
from schemas.course_schema import EnrolledStudentResponse
from schemas.course_schema import UpdateCourseRequest
from schemas.course_stats import CourseStatsResponse
from services import course
from services.course_stats import get_course_stats
from services import course_comparisons
from schemas.course_comparison import CourseComparisonCreate, CourseComparisonResponse, CourseComparisonUpdate
from services.course import CourseInviteService
from dependencies.auth_dep import require_admin_or_prof

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    request: CreateCourseRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course.create_new_course(
        db,
        request.name,
        request.academic_term_id,
        request.academic_year_start,
        user,
    )


@router.get("", response_model=list[CourseResponse])
async def list_courses(
    include_archived: bool = Query(False),
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await course.list_courses_for_user(db, user, include_archived=include_archived)


@router.get("/{course_id}/stats", response_model=CourseStatsResponse)
async def course_stats(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await get_course_stats(db, course_id, user.id)


@router.post("/{course_id}/comparisons", response_model=CourseComparisonResponse, status_code=status.HTTP_201_CREATED)
async def create_course_comparison(course_id: UUID, request: CourseComparisonCreate, db=Depends(get_db), user: User = Depends(require_admin_or_prof)):
    return await course_comparisons.create_comparison(db, course_id, request.comparison_course_id, user)


@router.get("/{course_id}/comparisons", response_model=list[CourseComparisonResponse])
async def list_course_comparisons(course_id: UUID, db=Depends(get_db), user: User = Depends(require_admin_or_prof)):
    return await course_comparisons.list_comparisons(db, course_id, user)


@router.get("/{course_id}/comparisons/{comparison_id}", response_model=CourseComparisonResponse)
async def get_course_comparison(course_id: UUID, comparison_id: UUID, db=Depends(get_db), user: User = Depends(require_admin_or_prof)):
    return await course_comparisons.get_comparison(db, course_id, comparison_id, user)


@router.patch("/{course_id}/comparisons/{comparison_id}", response_model=CourseComparisonResponse)
async def update_course_comparison(course_id: UUID, comparison_id: UUID, request: CourseComparisonUpdate, db=Depends(get_db), user: User = Depends(require_admin_or_prof)):
    return await course_comparisons.update_comparison(db, course_id, comparison_id, request, user)


@router.delete("/{course_id}/comparisons/{comparison_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course_comparison(course_id: UUID, comparison_id: UUID, db=Depends(get_db), user: User = Depends(require_admin_or_prof)):
    await course_comparisons.delete_comparison(db, course_id, comparison_id, user)


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await course.get_course(db, course_id, user)


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: UUID,
    request: UpdateCourseRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course.update_existing_course(
        db,
        course_id,
        user,
        request.name,
        request.academic_term_id,
        request.academic_year_start,
    )


@router.post("/{course_id}/archive", response_model=CourseResponse)
async def archive_course(
    course_id: UUID,
    request: ArchiveCourseRequest | None = None,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course.archive_existing_course(
        db,
        course_id,
        user,
        confirmed=request.confirmed if request else False,
        override_active_course=request.override_active_course if request else False,
    )


@router.post("/{course_id}/restore", response_model=CourseResponse)
async def restore_course(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course.restore_existing_course(db, course_id, user)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    await course.delete_existing_course(db, course_id, user)

@router.get("/{course_id}/students", response_model=list[EnrolledStudentResponse])
async def list_course_students(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await course.list_course_roster(db, course_id, user)


@router.post(
    "/{course_id}/students",
    response_model=EnrolledStudentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_course_student(
    course_id: UUID,
    request: AddStudentRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course.add_student_to_course(db, course_id, request, user)


@router.post("/{course_id}/students/upload-csv", status_code=status.HTTP_200_OK)
async def upload_students_csv(
    course_id: UUID,
    file: UploadFile = File(...),
    db = Depends(get_db),
    user: User = Depends(require_admin_or_prof)
):
    # Ensure it's a CSV file (case-insensitive: STUDENTS.CSV is still a CSV).
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Please upload a .csv file."
        )
    
    MAX_FILE_SIZE = 1_000_000  
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is too large. Maximum allowed size is 1MB."
        )
    
    await file.seek(0) # sets pointer back to start

    return await CourseInviteService.bulk_enroll_via_csv(db, course_id, file, user)


@router.post("/{course_id}/students/resend-invites", status_code=status.HTTP_200_OK)
async def resend_course_invites(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await CourseInviteService.resend_pending_invites(db, course_id, user)

@router.delete("/{course_id}/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_course_student(
    course_id: UUID,
    student_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    await course.unenroll_student(db, course_id, student_id, user)


@router.post("/{course_id}/students/{student_id}/promote", status_code=status.HTTP_204_NO_CONTENT)
async def promote_course_student(
    course_id: UUID,
    student_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    await course.promote_student_to_professor(db, course_id, student_id, user)
