"""Request/response contracts for the OMR service's HTTP API.

Field names use snake_case for Python callers but alias to the camelCase
names the OMR service's OpenAPI spec (app/omr/api/openapi.yaml) actually
sends/expects on the wire.

Note: POST /mark runs synchronously and returns full results in the 200
response — there is no job-id + polling flow (that was tried and dropped;
see the "Run a marking job" description in app/omr/api/openapi.yaml).
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _OMRSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# --- Preprocessing template (POST /template/preprocess) ---

class Point(_OMRSchema):
    x: int
    y: int


class ROI(_OMRSchema):
    min: Point
    max: Point


class PreprocessingConfig(_OMRSchema):
    blur_size: int = Field(alias="blurSize")
    morph_close_size: int = Field(alias="morphCloseSize")
    min_anchor_confidence: float = Field(alias="minAnchorConfidence")
    # Adaptive-threshold tuning, added after the original spec draft — both
    # required by the Go handler's validation (app/omr/internal/httpserver/dto/ptemplate.go).
    adaptive_block_size: int = Field(alias="adaptiveBlockSize")
    adaptive_c: float = Field(default=0.0, alias="adaptiveC")
    # The imgSize/templateSize ratio the sizes above were tuned against, so
    # the OMR service can scale them relative to a scan's actual resolution
    # instead of applying them unscaled at every DPI. 0 means unknown (the
    # OMR service leaves them unscaled, matching pre-existing behavior).
    reference_ratio: float = Field(default=0.0, alias="referenceRatio")


class PreprocessingAnchor(_OMRSchema):
    center: Point
    roi: ROI


class PreprocessingPage(_OMRSchema):
    anchors: list[PreprocessingAnchor]


class PreprocessingTemplate(_OMRSchema):
    width: int
    height: int
    # The DPI this template's tuning is calibrated against, so the OMR
    # service can request a matching render by default. 0 means unknown.
    native_dpi: float = Field(default=0.0, alias="nativeDpi")
    config: PreprocessingConfig
    pages: list[PreprocessingPage]


# --- Marking template (POST /template/mark) ---

class MarkingConfig(_OMRSchema):
    fill_threshold: float = Field(alias="fillThreshold")
    # Used in place of fill_threshold for the final gap-based selection
    # cutoff only; see marker.Config.SelectionThreshold in
    # app/omr/internal/marker/marker.go for why that needs to be a separate
    # knob. None (default) falls back to fill_threshold, i.e. previous
    # behavior -- must stay Optional, not a bare float defaulting to 0.0,
    # since 0 would disable gap-based selection entirely.
    selection_threshold: Optional[float] = Field(default=None, alias="selectionThreshold")
    bubble_inset: float = Field(alias="bubbleInset")
    flag_threshold: Optional[float] = Field(default=None, alias="flagThreshold")
    # Per-axis pixel search window around each bubble's template position;
    # added after the original spec draft (app/omr/internal/httpserver/dto/mtemplate.go).
    search_radius: int = Field(default=0, alias="searchRadius")
    # Splits a wide row into independently-aligned groups instead of one
    # shared-offset search for the whole row; see
    # marker.Config.SearchGroupSize in app/omr/internal/marker/marker.go for
    # the full rationale. Both 0 (default) keeps search_radius's original
    # behavior.
    search_group_size: int = Field(default=0, alias="searchGroupSize")
    group_search_radius: int = Field(default=0, alias="groupSearchRadius")


class QuestionOption(_OMRSchema):
    label: str
    x: int
    y: int
    # Corrects for this option's own printed glyph reading a different
    # natural (unmarked) ink level than its question's other options; see
    # marker.Bubble.BaselineBias in app/omr/internal/marker/marker.go for
    # the full rationale. 0 (default) leaves detection exactly as before.
    baseline_bias: float = Field(default=0.0, alias="baselineBias")


class Question(_OMRSchema):
    id: str
    bubble_width: int = Field(alias="bubbleWidth")
    bubble_height: int = Field(alias="bubbleHeight")
    type: Optional[str] = None
    options: list[QuestionOption]


class MarkingPage(_OMRSchema):
    questions: list[Question]


class MarkingTemplate(_OMRSchema):
    config: MarkingConfig
    pages: list[MarkingPage]


# --- Marking results (POST /mark, 200 response) ---

class OptionBox(_OMRSchema):
    """A single option's bubble bounding box, in scan pixel coordinates,
    selected or not.
    """

    label: str
    selected: bool
    x: int
    y: int
    width: int
    height: int


class QuestionBounds(_OMRSchema):
    """Bounding box enclosing every one of a question's bubbles, not just the
    selected ones. Present even for a blank question, unlike OptionBox.
    """

    x: int
    y: int
    width: int
    height: int


class DetectedQuestionMark(_OMRSchema):
    question_id: str = Field(alias="questionId")
    flagged: bool
    selected: list[str]
    confidence: float
    # Which page (matching the scan's page images) this mark's coordinates
    # are relative to. Needed to make sense of bounds/boxes below.
    page_index: int = Field(alias="pageIndex")
    bounds: QuestionBounds
    # One box per option in the question, in template order.
    boxes: list[OptionBox]


class ScanMarks(_OMRSchema):
    scan_id: str = Field(alias="scanId")
    marks: list[DetectedQuestionMark]


class MarkingError(_OMRSchema):
    """Why a single scan in a marking job's batch failed: a missing scan,
    a page count mismatch against the template, or a marking failure. This
    doesn't stop the rest of the batch from being marked.
    """

    scan_id: str = Field(alias="scanId")
    debug: str


class MarkingResult(_OMRSchema):
    pages_marked: int = Field(alias="pagesMarked")
    template_id: str = Field(alias="templateId")
    scans: list[ScanMarks]
    # Per-scan failures inside an otherwise-successful (200) batch — the
    # overall request still succeeds even if individual scans error out.
    errors: list[MarkingError] = Field(default_factory=list)


# --- PDF preprocessing results (POST /scan/pdf) ---

class PDFScanError(_OMRSchema):
    from_page: int = Field(alias="from")
    thru_page: int = Field(alias="thru")
    debug: str


class PDFScanResult(_OMRSchema):
    scan_ids: list[str] = Field(alias="scanIds")
    errors: list[PDFScanError] = Field(default_factory=list)


# --- Job status (GET /job) ---

class OMRJobStatus(_OMRSchema):
    id: str
    method: str
    path: str
    progress: float
    started_timestamp: int = Field(alias="startedTimestamp")
    finished_timestamp: Optional[int] = Field(default=None, alias="finishedTimestamp")
    success: Optional[bool] = None
    notes: str = ""
