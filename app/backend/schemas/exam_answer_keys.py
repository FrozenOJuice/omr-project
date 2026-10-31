import math
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class GradingType(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    PARTIAL = "partial"


class AnswerKeyScanWarningCode(StrEnum):
    BLANK_ANSWER = "blank_answer"
    LOW_CONFIDENCE = "low_confidence"
    VERSION_NOT_DETECTED = "version_not_detected"
    VERSION_AMBIGUOUS = "version_ambiguous"
    VERSION_INVALID = "version_invalid"
    VERSION_DUPLICATE = "version_duplicate"


class AnswerKeyVersionDetectionStatus(StrEnum):
    DETECTED = "detected"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    NOT_APPLICABLE = "not_applicable"


class AnswerKeyScanMatchingMode(StrEnum):
    AUTOMATIC = "automatic"
    ORDERED = "ordered"
    MANUAL = "manual"


class AnswerKeyScanMatchAction(StrEnum):
    APPLY = "apply"
    SKIP = "skip"


class AnswerKeyItem(BaseModel):
    grading_type: GradingType
    correct_choices: list[str]
    points: float | None = None
    partial_weights: dict[str, float] | None = None

    @field_validator("partial_weights")
    @classmethod
    def validate_partial_weight_range(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        # Weights are fractions of a question's points (0 = no credit, 1 = full
        # credit), matching the frontend's own 0-1 check in answer-key.ts's
        # validationError. Enforced here too since this schema is the only
        # gate for clients that hit the API directly.
        if v is not None:
            for label, weight in v.items():
                if not (0 <= weight <= 1):
                    raise ValueError(
                        f"partial_weights['{label}'] must be between 0 and 1, got {weight}"
                    )
        return v

    @model_validator(mode="after")
    def validate_partial_weights(self) -> "AnswerKeyItem":
        if self.grading_type == GradingType.PARTIAL and not self.partial_weights:
            raise ValueError("partial_weights must be provided when grading_type is 'partial'")
        if self.grading_type == GradingType.SINGLE and self.partial_weights is not None:
            raise ValueError("partial_weights should not be set for 'single' grading type")
        if self.grading_type == GradingType.PARTIAL and self.partial_weights is not None and self.correct_choices:
            # grading_service._score_question sums the weights of every correct
            # choice a student selected, so these must add up to exactly 1 (100%)
            # for a student who selects every correct choice to be able to earn
            # full marks. Skipped while correct_choices is still empty (the key
            # is mid-edit / intentionally saved incomplete), since there's
            # nothing to sum yet.
            total = sum(
                weight for choice, weight in self.partial_weights.items()
                if choice in self.correct_choices
            )
            if not math.isclose(total, 1.0, abs_tol=1e-6):
                raise ValueError(
                    f"partial_weights for correct choices add up to {total}, "
                    "which must equal exactly 1 (100%)"
                )
        return self


class CreateExamAnswerKeyRequest(BaseModel):
    exam_template_id: UUID
    exam_version: str | None = None
    answer_key: dict[str, AnswerKeyItem]
    scoring_rules: dict[str, float] | None = None

    @field_validator("exam_version")
    @classmethod
    def validate_exam_version(cls, v: str | None) -> str | None:
        if v is not None and (len(v) != 1 or not v.isalpha()):
            raise ValueError("exam_version must be a single letter (A–Z)")
        return v.upper() if v else v


class UpdateExamAnswerKeyRequest(BaseModel):
    answer_key: dict[str, AnswerKeyItem] | None = None
    scoring_rules: dict[str, float] | None = None


class ExamAnswerKeyResponse(BaseModel):
    id: UUID
    exam_id: UUID
    exam_template_id: UUID | None
    exam_version: str | None
    answer_key: dict[str, AnswerKeyItem]
    scoring_rules: dict[str, float] | None
    answer_key_path: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# The uploaded PDF itself is a multipart ``UploadFile`` on the future route;
# this model describes the form fields that accompany it.
class ExtractAnswerKeyScanBatchRequest(BaseModel):
    question_count: int = Field(ge=1, le=200)


class ExtractedAnswerKeyQuestion(BaseModel):
    selected_choices: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    flagged: bool = False


class AnswerKeyScanWarning(BaseModel):
    code: AnswerKeyScanWarningCode
    message: str
    question_id: str | None = None
    selected_choices: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class AnswerKeyVersionDetection(BaseModel):
    status: AnswerKeyVersionDetectionStatus
    selected_choices: list[str] = Field(default_factory=list)
    detected_version: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("detected_version")
    @classmethod
    def normalize_detected_version(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 1 or not value.isalpha()):
            raise ValueError("detected_version must be a single letter (A–Z)")
        return value.upper() if value else value

    @model_validator(mode="after")
    def validate_status(self) -> "AnswerKeyVersionDetection":
        if self.status == AnswerKeyVersionDetectionStatus.DETECTED:
            if len(self.selected_choices) != 1 or self.detected_version != self.selected_choices[0]:
                raise ValueError(
                    "detected version status requires one selected choice matching detected_version"
                )
        elif self.detected_version is not None:
            raise ValueError("detected_version must be null unless status is 'detected'")

        if self.status in (
            AnswerKeyVersionDetectionStatus.MISSING,
            AnswerKeyVersionDetectionStatus.NOT_APPLICABLE,
        ) and self.selected_choices:
            raise ValueError(f"{self.status} version status cannot have selected choices")
        if self.status == AnswerKeyVersionDetectionStatus.AMBIGUOUS and len(self.selected_choices) < 2:
            raise ValueError("ambiguous version status requires at least two selected choices")
        return self


class ExtractedAnswerKeySheet(BaseModel):
    sheet_index: int = Field(ge=0)
    # Which uploaded file this sheet came from, so the matching UI can group
    # sheets by file when more than one was uploaded at once.
    source_filename: str
    # Page numbers are one-based and inclusive, counted within source_filename
    # rather than across the whole upload, so they can be shown directly in
    # the matching UI (for example, "Sheet 2 · pages 3–4").
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    answers: dict[str, ExtractedAnswerKeyQuestion]
    version: AnswerKeyVersionDetection
    # Minimum confidence across the included answer/version fields.
    minimum_confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: list[AnswerKeyScanWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_page_range(self) -> "ExtractedAnswerKeySheet":
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ExtractAnswerKeyScanBatchResponse(BaseModel):
    pages_per_sheet: int = Field(ge=1)
    sheets: list[ExtractedAnswerKeySheet] = Field(default_factory=list)


class AnswerKeyScanSheetMatch(BaseModel):
    sheet_index: int = Field(ge=0)
    action: AnswerKeyScanMatchAction = AnswerKeyScanMatchAction.APPLY
    # Null is a valid target for an exam with one unversioned key.
    target_version: str | None = None

    @field_validator("target_version")
    @classmethod
    def normalize_target_version(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 1 or not value.isalpha()):
            raise ValueError("target_version must be a single letter (A–Z)")
        return value.upper() if value else value

    @model_validator(mode="after")
    def validate_skipped_match(self) -> "AnswerKeyScanSheetMatch":
        if self.action == AnswerKeyScanMatchAction.SKIP and self.target_version is not None:
            raise ValueError("a skipped sheet cannot have a target_version")
        return self


class ConfirmAnswerKeyScanMatchesRequest(BaseModel):
    matching_mode: AnswerKeyScanMatchingMode
    matches: list[AnswerKeyScanSheetMatch] = Field(min_length=1)
    overwrite_existing: bool = False

    @model_validator(mode="after")
    def validate_one_to_one_matches(self) -> "ConfirmAnswerKeyScanMatchesRequest":
        sheet_indexes = [match.sheet_index for match in self.matches]
        if len(sheet_indexes) != len(set(sheet_indexes)):
            raise ValueError("each extracted sheet may only be matched once")

        applied_targets = [
            match.target_version
            for match in self.matches
            if match.action == AnswerKeyScanMatchAction.APPLY
        ]
        if len(applied_targets) != len(set(applied_targets)):
            raise ValueError("each answer-key version may only be matched once")
        return self
