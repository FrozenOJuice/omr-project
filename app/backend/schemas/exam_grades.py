from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class QuestionResult(BaseModel):
    grading_type: str
    student_answers: list[str]
    correct_answers: list[str]
    correct: bool
    score: float
    max_score: float
    ambiguous: bool = False


class OptionBox(BaseModel):
    """A single option's bubble bounding box, in scan pixel coordinates,
    selected or not.
    """

    label: str
    selected: bool
    x: int
    y: int
    width: int
    height: int


class QuestionBounds(BaseModel):
    """Bounding box enclosing every one of a question's bubbles, not just the
    selected ones. Present even for a blank question, unlike OptionBox.
    """

    x: int
    y: int
    width: int
    height: int


class QuestionAnnotation(BaseModel):
    """Where a question's bubbles sit on a scan page, plus its grade.

    This is what a frontend needs to draw a colored overlay on top of the
    page image. Coloring itself is a presentation decision left to the
    frontend (correct, incorrect, ambiguous); this only reports the
    underlying facts.
    """

    question_id: str
    bounds: QuestionBounds
    boxes: list[OptionBox]
    confidence: float
    correct: bool
    ambiguous: bool
    score: float
    max_score: float
    student_answers: list[str]
    correct_answers: list[str]


class IdentityFieldAnnotation(BaseModel):
    """One character column of a name/student-ID bubble field (e.g. the 3rd
    letter of a last name), for the same kind of overlay as QuestionAnnotation
    draws for answer questions.
    """

    field_type: str
    field_index: int
    bounds: QuestionBounds
    boxes: list[OptionBox]
    confidence: float


class IdentityAnnotations(BaseModel):
    """A grade's (or one page's) name/student-ID bubble fields, plus what OMR
    decoded them as. Used to resolve an unmatched scan.
    """

    fields: list[IdentityFieldAnnotation]
    last_name: str
    first_name: str
    student_id: str
    # Which page these fields live on, e.g. for a persistent "identify
    # student" card to jump to. None if this marking has no identity fields
    # at all (or, for the page-scoped endpoint, none on the requested page).
    page_index: int | None = None


class VersionAnnotation(BaseModel):
    """The version-selector bubble on a page, if this template has one and
    it's on this page, plus what OMR decoded it as. Read-only: unlike a
    name/ID mismatch, a wrong version reshuffles the whole grade (it picks
    the answer key), so correcting it isn't just a display fix.
    """

    field: IdentityFieldAnnotation | None
    detected_version: str | None


class GradeSectionResult(BaseModel):
    id: str
    name: str
    type: str | None
    question_ids: list[str]
    score: float
    max_score: float


class ExamGradeResponse(BaseModel):
    id: UUID
    omr_marking_id: UUID
    exam_answer_key_id: UUID
    question_results: dict[str, QuestionResult]
    total_score: float
    max_score: float
    template_version: int
    exam_version: str | None = None
    student_id: UUID | None
    status: str
    flag_reason: str | None
    graded_at: datetime
    section_results: list[GradeSectionResult] = Field(default_factory=list)
    # How many pages the marking's OMR template has, i.e. the valid range for
    # GET /grades/{id}/pages/{page_index}/annotations and .../image. None if
    # it couldn't be resolved (the OMR template was deleted after marking).
    page_count: int | None = None
    # Resolved via exam_answer_key_id -> ExamAnswerKey.exam_id. None if the
    # answer key was deleted after grading.
    exam_id: UUID | None = None

    model_config = {"from_attributes": True}


class GradeAuditEntryResponse(BaseModel):
    id: UUID
    exam_grade_id: UUID
    actor_user_id: UUID | None
    actor_name: str | None
    event_type: str
    previous_total_score: float | None
    new_total_score: float
    changes: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateExamGradeRequest(BaseModel):
    """Manual corrections applied by an instructor to a grade.

    - student_id: assign the scan to an enrolled student (fixes name/id flags).
    - corrected_answers: {question_number: [choice labels]} overrides for what
      the OMR detected; the affected questions are re-scored against the
      grade's answer key. An empty list marks the question blank.
    - resolve_flag: mark the grade as reviewed (status "graded", flag cleared).
    - confirm_duplicate_assignment: acknowledge that student_id already has a
      different grade for this exam.
    """

    student_id: UUID | None = None
    corrected_answers: dict[str, list[str]] | None = None
    resolve_flag: bool = False
    confirm_duplicate_assignment: bool = False

    @field_validator("corrected_answers")
    @classmethod
    def validate_corrected_answers(
        cls, v: dict[str, list[str]] | None
    ) -> dict[str, list[str]] | None:
        if v is None:
            return v
        for question_number, answers in v.items():
            for answer in answers:
                if len(answer) != 1 or not answer.isalpha():
                    raise ValueError(
                        f"Answers for question {question_number} must be single letters"
                    )
        return {
            question_number: [answer.upper() for answer in answers]
            for question_number, answers in v.items()
        }

    @model_validator(mode="after")
    def require_a_correction(self) -> "UpdateExamGradeRequest":
        if self.student_id is None and self.corrected_answers is None and not self.resolve_flag:
            raise ValueError(
                "Provide at least one of student_id, corrected_answers, or resolve_flag"
            )
        return self
