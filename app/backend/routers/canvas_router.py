import io
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from fastapi.responses import StreamingResponse

from db.session import get_db
from dependencies.auth_dep import require_admin_or_prof
from models.user import User
from schemas.canvas_schema import (
    CanvasAssignmentResponse,
    CanvasCapabilitiesResponse,
    CanvasConnectionRequest,
    CanvasConnectionResponse,
    CanvasCourseResponse,
    CanvasExamAssignmentRequest,
    CanvasGradeReleaseResponse,
    CanvasRosterInvitationResponse,
    CanvasRosterResponse,
    CanvasRosterSyncResponse,
    CanvasStudentAccessRequest,
    CanvasId,
)
from schemas.exam_grades import (
    ExamGradeResponse,
    IdentityAnnotations,
    QuestionAnnotation,
    VersionAnnotation,
)
from schemas.course_schema import (
    CanvasCourseImportRequest,
    CanvasCourseImportResponse,
    CourseResponse,
)
from services import canvas_assignments as assignment_service
from services import canvas_courses as course_service
from services import canvas_grades as grade_service
from services import canvas_student_access as student_access_service
from services import canvas_connection as connection_service
from services import canvas_roster as roster_service
from services import grading_service as grading_view_service

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


def _set_student_result_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


async def _student_result_access(db, request: CanvasStudentAccessRequest):
    return await student_access_service.authorize(
        db,
        request.access_token.get_secret_value(),
    )


@router.post(
    "/student-results/access",
    response_model=ExamGradeResponse,
)
async def canvas_student_result(
    request: CanvasStudentAccessRequest,
    response: Response,
    db=Depends(get_db),
):
    access = await _student_result_access(db, request)
    _set_student_result_headers(response)
    return await grading_view_service.get_grade_view(
        db,
        access.grade.id,
        access.student,
    )


@router.post(
    "/student-results/identity",
    response_model=IdentityAnnotations,
)
async def canvas_student_result_identity(
    request: CanvasStudentAccessRequest,
    response: Response,
    db=Depends(get_db),
):
    access = await _student_result_access(db, request)
    _set_student_result_headers(response)
    return await grading_view_service.get_grade_identity_view(
        db,
        access.grade.id,
        access.student,
    )


@router.post(
    "/student-results/pages/{page_index}/annotations",
    response_model=list[QuestionAnnotation],
)
async def canvas_student_result_page_annotations(
    request: CanvasStudentAccessRequest,
    response: Response,
    page_index: int = Path(ge=0),
    db=Depends(get_db),
):
    access = await _student_result_access(db, request)
    _set_student_result_headers(response)
    return await grading_view_service.get_grade_page_annotations_view(
        db,
        access.grade.id,
        page_index,
        access.student,
    )


@router.post(
    "/student-results/pages/{page_index}/identity",
    response_model=IdentityAnnotations,
)
async def canvas_student_result_page_identity(
    request: CanvasStudentAccessRequest,
    response: Response,
    page_index: int = Path(ge=0),
    db=Depends(get_db),
):
    access = await _student_result_access(db, request)
    _set_student_result_headers(response)
    return await grading_view_service.get_grade_page_identity_view(
        db,
        access.grade.id,
        page_index,
        access.student,
    )


@router.post(
    "/student-results/pages/{page_index}/version",
    response_model=VersionAnnotation,
)
async def canvas_student_result_page_version(
    request: CanvasStudentAccessRequest,
    response: Response,
    page_index: int = Path(ge=0),
    db=Depends(get_db),
):
    access = await _student_result_access(db, request)
    _set_student_result_headers(response)
    return await grading_view_service.get_grade_page_version_view(
        db,
        access.grade.id,
        page_index,
        access.student,
    )


@router.post(
    "/student-results/pages/{page_index}/image",
)
async def canvas_student_result_page_image(
    request: CanvasStudentAccessRequest,
    page_index: int = Path(ge=0),
    db=Depends(get_db),
):
    access = await _student_result_access(db, request)
    image = await grading_view_service.get_grade_page_image_bytes(
        db,
        access.grade.id,
        page_index,
        access.student,
    )
    response = StreamingResponse(
        io.BytesIO(image),
        media_type="image/jpeg",
    )
    _set_student_result_headers(response)
    return response


@router.get("/capabilities", response_model=CanvasCapabilitiesResponse)
async def canvas_capabilities(
    user: User = Depends(require_admin_or_prof),
):
    return CanvasCapabilitiesResponse(
        configured=connection_service.is_configured(),
        settings_url=connection_service.settings_url(),
    )


@router.post("/connection", response_model=CanvasConnectionResponse)
async def connect_canvas(
    request: CanvasConnectionRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await connection_service.connect(
        db,
        user.id,
        request.access_token.get_secret_value(),
    )


@router.get("/connection", response_model=CanvasConnectionResponse)
async def canvas_connection(
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await connection_service.get_connection_status(db, user.id)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_canvas(
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    await connection_service.disconnect(db, user.id)


@router.get("/courses", response_model=list[CanvasCourseResponse])
async def list_canvas_courses(
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course_service.list_courses(db, user.id)


@router.post("/courses/import", response_model=CanvasCourseImportResponse)
async def import_canvas_courses(
    request: CanvasCourseImportRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course_service.import_courses(db, user, request.course_ids)


@router.post(
    "/courses/{course_id}/import",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_canvas_course(
    course_id: CanvasId,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await course_service.import_course(db, user, course_id)


@router.get("/courses/{course_id}/students", response_model=CanvasRosterResponse)
async def canvas_roster(
    course_id: CanvasId,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await roster_service.get_roster(db, user.id, course_id)


@router.post(
    "/imported-courses/{course_id}/roster/sync",
    response_model=CanvasRosterSyncResponse,
)
async def sync_canvas_roster(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await roster_service.sync_roster(db, user, course_id)


@router.post(
    "/imported-courses/{course_id}/roster/invite-pending",
    response_model=CanvasRosterInvitationResponse,
)
async def invite_pending_canvas_students(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await roster_service.invite_pending_students(db, user, course_id)


@router.post(
    "/imported-courses/{course_id}/roster/{roster_entry_id}/invite",
    response_model=CanvasRosterInvitationResponse,
)
async def invite_canvas_student(
    course_id: UUID,
    roster_entry_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await roster_service.invite_student(
        db, user, course_id, roster_entry_id
    )


@router.get(
    "/imported-courses/{course_id}/assignments",
    response_model=list[CanvasAssignmentResponse],
)
async def canvas_assignments(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await assignment_service.list_available(db, user, course_id)


@router.put(
    "/exams/{exam_id}/canvas-assignment",
    response_model=CanvasGradeReleaseResponse,
)
async def set_canvas_exam_assignment(
    exam_id: UUID,
    request: CanvasExamAssignmentRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await grade_service.set_assignment(
        db, user, exam_id, request.assignment_id
    )


@router.delete(
    "/exams/{exam_id}/canvas-assignment",
    response_model=CanvasGradeReleaseResponse,
)
async def clear_canvas_exam_assignment(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await grade_service.clear_assignment(db, user, exam_id)


@router.get(
    "/exams/{exam_id}/grade-release",
    response_model=CanvasGradeReleaseResponse,
)
async def canvas_grade_release(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await grade_service.get_grade_release(db, user, exam_id)


@router.post(
    "/exams/{exam_id}/grade-release",
    response_model=CanvasGradeReleaseResponse,
)
async def release_canvas_grades(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await grade_service.release_grades(db, user, exam_id)
