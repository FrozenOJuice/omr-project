"""Generates custom exam PDFs and their supporting OMR templates."""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from constants.blueprints import UBCO_100_BLUEPRINT
from errors.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from integrations.omr_client import OMRClientError, upload_marking_template, upload_preprocessing_template
from models.exam_template import ExamTemplate
from models.user import User, UserRole
from repositories.courses import get_by_id as get_course_by_id
from repositories.exam_templates import get_exam_template_by_id
from repositories.exams import get_exam_by_id
from repositories.omr_templates import create_omr_template
from repositories.storage import StorageRepository
from schemas.omr_schema import MarkingTemplate, PreprocessingTemplate

# Hand-made physical sheet for UBCO_100_BLUEPRINT templates — the same
# directory app/omr/data/templates/ubc uses for the OMR CLI, bind-mounted
# read-only into this container (see docker-compose.yml) so there's one
# source of truth instead of a copy per service.
UBC_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "ubc_template"


def _load_ubc_mark_template_bytes() -> bytes:
    return (UBC_TEMPLATE_DIR / "mark.json").read_bytes()


def _load_ubc_scan_template() -> tuple[dict, dict[tuple[int, int], bytes]]:
    """Loads the CLI-format scan.json and its anchor crops.

    scan.json is written for the OMR CLI's scanner.LoadTemplate, which
    marshals Go's image.Point/Rectangle as capitalized X/Y/Min/Max and
    references anchor images by path. The HTTP API this calls into
    (upload_preprocessing_template) expects lowercase x/y/min/max and
    anchor images as uploaded JPEG bytes, so both get translated here.
    """
    from PIL import Image

    raw = json.loads((UBC_TEMPLATE_DIR / "scan.json").read_text())

    def _point(p: dict) -> dict:
        return {"x": p["X"], "y": p["Y"]}

    scan_template = {
        "width": raw["width"],
        "height": raw["height"],
        # This hand-made template has no recorded calibration DPI, so the
        # OMR service falls back to its own default rather than a value
        # tied to this specific template.
        "nativeDpi": raw.get("nativeDpi", 0),
        "config": raw["config"],
        "pages": [
            {
                "anchors": [
                    {
                        "center": _point(anchor["center"]),
                        "roi": {"min": _point(anchor["roi"]["Min"]), "max": _point(anchor["roi"]["Max"])},
                        "optional": anchor.get("optional", False),
                    }
                    for anchor in page["anchors"]
                ]
            }
            for page in raw["pages"]
        ],
    }

    anchor_images = {}
    for page_idx, page in enumerate(raw["pages"]):
        for anchor_idx, anchor in enumerate(page["anchors"]):
            png_bytes = (UBC_TEMPLATE_DIR / anchor["path"]).read_bytes()
            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            anchor_images[(page_idx, anchor_idx)] = buf.getvalue()

    return scan_template, anchor_images

# Page geometry
TEMPLATE_W, TEMPLATE_H = 1314, 1700
PAGE_W_PT, PAGE_H_PT = 612.0, 792.0


def _fit_scale_offset(
    content_w: float, content_h: float, page_w_pt: float = PAGE_W_PT, page_h_pt: float = PAGE_H_PT
) -> tuple[float, float, float]:
    """A single uniform scale, not independent X/Y factors, to fit a
    content_w x content_h canvas onto a page_w_pt x page_h_pt page.
    Scaling each axis independently would draw anchors/bubbles as ellipses
    instead of circles, which hurts the OMR service's anchor
    template-matching confidence. The two offsets centre the scaled content
    on whichever axis has slack. Shared by both the custom exam generator
    (its own TEMPLATE_W/H canvas) and the UBC blueprint (its canonical
    warped page images, see render_filled_ubc_scan_pdf).
    """
    scale = min(page_w_pt / content_w, page_h_pt / content_h)
    offset_x = (page_w_pt - content_w * scale) / 2
    offset_y = (page_h_pt - content_h * scale) / 2
    return scale, offset_x, offset_y


SCALE, OFFSET_X, OFFSET_Y = _fit_scale_offset(TEMPLATE_W, TEMPLATE_H)

# NATIVE_DPI records the DPI this template's anchor/binarization tuning is
# calibrated against, so the OMR service can request a matching render by default
# instead of relying only on a hardcoded constant on the backend side.
#
# REFERENCE_RATIO is the imgSize/TEMPLATE_W(H) ratio a render at NATIVE_DPI
# actually produces. TEMPLATE_W/H is just an internal working resolution,
# not a real physical page size, so it does not equal 1 the way it might
# for a template whose canvas was defined to match its own calibration DPI.
# The OMR service uses this to scale its binarization tuning relative to
# how far a given scan's resolution has drifted from NATIVE_DPI, rather
# than from an assumed (and here, incorrect) ratio of 1.
RENDER_ZOOM = 3.0

NATIVE_DPI =  int(RENDER_ZOOM * 72) #216
REFERENCE_RATIO = RENDER_ZOOM * SCALE

# Anchor marker geometry (template pixel space)
ANCHOR_PAD        = 36   # distance from page edge to anchor centre
ANCHOR_SIZE       = 24   # diameter in template pixels (~16 pt ≈ 5.7 mm printed)
ANCHOR_OUTER_RING = 3    # outer black ring width (px)
ANCHOR_WHITE_RING = 5    # white ring width (px)
ANCHOR_PNG_KEY    = "anchors/custom_exam_anchor.png"

ANCHORS_FRONT = [
    (ANCHOR_PAD,              ANCHOR_PAD),               # top-left
    (TEMPLATE_W - ANCHOR_PAD, ANCHOR_PAD),               # top-right
    (ANCHOR_PAD,              TEMPLATE_H - ANCHOR_PAD),  # bottom-left
]
ANCHORS_BACK = [
    (ANCHOR_PAD,              ANCHOR_PAD),               # top-left
    (TEMPLATE_W - ANCHOR_PAD, ANCHOR_PAD),               # top-right
    (TEMPLATE_W - ANCHOR_PAD, TEMPLATE_H - ANCHOR_PAD),  # bottom-right
]


def _anchor_roi(cx: int, cy: int) -> dict:
    return {
        "min": {"x": max(0, cx - 150), "y": max(0, cy - 150)},
        "max": {"x": min(TEMPLATE_W, cx + 150), "y": min(TEMPLATE_H, cy + 150)},
    }


def _draw_anchor_image():
    """Bullseye greyscale image for OMR template matching.

    Draws black outer disk → white ring → black centre dot. The white ring
    gives Otsu binarization (ThresholdBinaryInv+Otsu in the Go scanner) a
    bimodal histogram to work with. Circles are rotation-invariant, so
    matchTemplate scores don't degrade on slightly skewed scans.
    """
    from PIL import Image, ImageDraw

    img  = Image.new("L", (ANCHOR_SIZE, ANCHOR_SIZE), 0xFF)
    draw = ImageDraw.Draw(img)
    last = ANCHOR_SIZE - 1  # ImageDraw uses inclusive coordinates

    def _bbox(inset: int) -> list[int]:
        return [inset, inset, last - inset, last - inset]

    draw.ellipse(_bbox(0),                                    fill=0)    # outer black disk
    draw.ellipse(_bbox(ANCHOR_OUTER_RING),                    fill=0xFF) # white ring
    draw.ellipse(_bbox(ANCHOR_OUTER_RING + ANCHOR_WHITE_RING), fill=0)   # inner black dot

    return img


def _make_anchor_png() -> bytes:
    buf = io.BytesIO()
    _draw_anchor_image().save(buf, format="PNG")
    return buf.getvalue()


def _make_anchor_jpeg() -> bytes:
    """Same anchor image as _make_anchor_png, JPEG-encoded.

    The OMR service's /template/preprocess endpoint hardcodes JPEG decoding
    for anchor uploads, so this is what gets sent there — the PNG stays the
    durable copy in Garage.
    """
    buf = io.BytesIO()
    _draw_anchor_image().save(buf, format="JPEG")
    return buf.getvalue()


def _make_page_scan_template(anchor_positions: list) -> dict:
    return {
        "anchors": [
            {"center": {"x": cx, "y": cy}, "roi": _anchor_roi(cx, cy)}
            for cx, cy in anchor_positions
        ],
    }


def _make_scan_template(answer_page_count: int = 1) -> dict:
    """Build preprocessing pages for each answer page plus student info."""
    return {
        "width": TEMPLATE_W,
        "height": TEMPLATE_H,
        "nativeDpi": NATIVE_DPI,
        "config": {
            "blurSize": 5,
            "morphCloseSize": 3,
            "minAnchorConfidence": 0.5,
            "adaptiveBlockSize": 51,
            # Low enough to catch faint pencil marks (verified against real scans
            # down to a ~15-25 grayscale point contrast from background) without
            # tipping into the false-positive cliff that starts right at 0.
            "adaptiveC": 2,
            "referenceRatio": REFERENCE_RATIO,
        },
        "pages": [
            *[
                _make_page_scan_template(ANCHORS_FRONT)
                for _ in range(answer_page_count)
            ],
            _make_page_scan_template(ANCHORS_BACK),
        ],
    }


# The common one-answer-page shape remains available to existing callers.
SCAN_TEMPLATE = _make_scan_template()

# Front page layout
HEADER_H    = 270
MARGIN_X    = 75
COL_GAP     = 30
ROW_HEIGHT  = 44
HEADER_EXTRA_H = ROW_HEIGHT  # extra room reserved above a section-start row
MAX_QUESTION_COUNT = 200
BUBBLE_D    = 20
BUBBLE_STEP = 38
LABEL_W     = 50
VERSION_CY  = 237  # template-pixel y-centre of the version bubble row

ROWS_PER_COL = 25  # bubble-rows of vertical space available per column

# Back page layout
INFO_ROW_H    = 36
WRITEIN_W     = 40
SECTION_LBL_H = 30
COL_HDR_H     = 25
SECTION_GAP   = 25
N_LAST  = 15
N_FIRST = 10
N_ID    =  8
DIGITS  = list("0123456789")
LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _estimate_rows(question_config: dict, n_columns: int) -> tuple[int, int]:
    """Total wrapped bubble-rows this template would need at a given column
    count, and how many rows are actually available at that count.

    This is a cheap upper-bound check, not an exact simulation of the greedy
    packing in _compute_questions: real packing can only do *worse* than this
    sum (a question that doesn't fit a column's remaining rows skips to the
    next column, wasting whatever was left), never better. So "fits by this
    estimate" doesn't guarantee real packing succeeds, but "doesn't fit by
    this estimate" always means real packing will fail too. That makes it
    safe to use as a fast pre-check with an accurate error message before
    laying anything out.
    """
    col_width           = ((TEMPLATE_W - 2 * MARGIN_X) - COL_GAP * (n_columns - 1)) // n_columns
    options_per_row_cap = max(1, (col_width - LABEL_W) // BUBBLE_STEP)
    total_rows = 0
    for cfg in question_config.values():
        n_opts          = len(cfg["choices"])
        options_per_row = min(n_opts, options_per_row_cap)
        total_rows     += (n_opts + options_per_row - 1) // options_per_row
    return total_rows, ROWS_PER_COL * n_columns


def _choose_column_layout(question_config: dict) -> tuple[int, int, int]:
    """Pick how many columns (1-4) to lay this template out in.

    Prefers the most columns whose total wrapped-row demand fits the page.
    More columns generally means more capacity, but each one is narrower, so
    a template full of wide questions can need *more* total rows at 4 narrow
    columns than at 1 wide one (every wide question wraps harder). Basing
    this on the whole template's demand, rather than just the single widest
    question, means one wide question no longer forces every other question
    in the template down to fewer columns than it needs.

    If no column count fits, returns whichever comes closest, so the caller
    can report an accurate shortfall instead of a vague "too many questions".
    """
    best = None
    for n in (4, 3, 2, 1):
        total_rows, capacity = _estimate_rows(question_config, n)
        if total_rows <= capacity:
            return n, total_rows, capacity
        if best is None or (total_rows - capacity) < (best[1] - best[2]):
            best = (n, total_rows, capacity)
    return best


def _bubble_rows_for(n_opts: int, cap: int) -> int:
    options_per_row = min(n_opts, cap)
    return (n_opts + options_per_row - 1) // options_per_row


def _full_width_cap() -> int:
    return max(1, ((TEMPLATE_W - 2 * MARGIN_X) - LABEL_W) // BUBBLE_STEP)


def _is_wide(n_opts: int) -> bool:
    """A question is "wide" if confining it to the tightest normal column
    (4 columns, used here as a fixed reference point regardless of how many
    columns this template actually ends up using) would take more than
    double the lines it'd need spanning the full page width instead.

    Below that bar, a question just wraps in place within the multi-column
    grid (e.g. 8 options into 2 lines), which isn't worth breaking the grid
    for. Above it (e.g. 26 options into 6 narrow lines vs 1 full-width
    line), it's pulled out into its own full-width band instead.
    """
    col_width_4 = ((TEMPLATE_W - 2 * MARGIN_X) - COL_GAP * 3) // 4
    cap_4       = max(1, (col_width_4 - LABEL_W) // BUBBLE_STEP)
    return _bubble_rows_for(n_opts, cap_4) > 2 * _bubble_rows_for(n_opts, _full_width_cap())


def _section_height(section_keys: list[str], question_config: dict, options_per_row_cap: int, has_header: bool) -> int:
    """Rows an all-normal section needs if kept together in a single
    column: each question's own wrapped rows, plus one row for its header
    if it has a name (the unnamed "leftover" section, used when a template
    has no sections configured at all, never draws a header)."""
    return (1 if has_header else 0) + sum(
        _bubble_rows_for(len(question_config[key]["choices"]), options_per_row_cap)
        for key in section_keys
    )


def _compute_questions(question_config: dict, sections: list | None = None) -> list[dict]:
    """Lay questions out section by section, top-to-bottom, spilling onto
    more columns and then more pages as needed.

    A section with no wide questions tries to stay together as one block:
    it's placed in whichever column currently has the most room if the
    whole section fits there, or starts fresh in an empty column (or a new
    page, if every column already has something in it) if it doesn't. This
    is the same "keep together, otherwise move over" rule multi-column text
    layout uses.

    A section that's too tall for even an empty column, or that contains a
    "wide" question (see _is_wide), falls through to plain per-question
    placement instead: each question claims one column, then as many more
    still-untouched columns to its right as actually shorten its wrapped
    rows (see best_span) — spreading horizontally takes priority over
    wrapping to another line, which in turn takes priority over rolling
    onto a new column or page.
    """
    keys = sorted(question_config, key=lambda k: int(k) if k.lstrip("-").isdigit() else k)
    if len(keys) > MAX_QUESTION_COUNT:
        raise BadRequestError(
            f"Too many questions ({len(keys)}) for this layout (max {MAX_QUESTION_COUNT}).",
            code="layout_overflow",
        )

    cap_full    = _full_width_cap()
    is_wide_key = {key: _is_wide(len(question_config[key]["choices"])) for key in keys}

    # _choose_column_layout's "closest fit" fallback still picks a sensible
    # n_columns even when nothing fits on a single page — content that
    # overflows one page now just rolls onto the next one (see new_page()
    # below) rather than being an error, so there's nothing to raise here.
    normal_config = {key: question_config[key] for key in keys if not is_wide_key[key]}
    n_columns, _, _ = _choose_column_layout(normal_config)
    col_width            = ((TEMPLATE_W - 2 * MARGIN_X) - COL_GAP * (n_columns - 1)) // n_columns
    options_per_row_cap  = max(1, (col_width - LABEL_W) // BUBBLE_STEP)

    # A question that needs more lines than fit a column, even alone at the
    # full page width, is a hard failure no amount of paging can fix. Catch
    # it up front for a precise message instead of a confusing one mid-layout.
    # cap_full is every question's best case, since a lone question can never
    # claim more than the whole page.
    for key in keys:
        rows = _bubble_rows_for(len(question_config[key]["choices"]), cap_full)
        if rows > ROWS_PER_COL:
            raise BadRequestError(
                f"Question {key} has {len(question_config[key]['choices'])} options, which needs "
                f"{rows} lines, more than fit in a single column ({ROWS_PER_COL} lines). Reduce its "
                "option count or split it into multiple questions.",
                code="layout_overflow",
            )

    # A true_false section's questions are always exactly 2 options, far
    # narrower than a normal multiple_choice column sized for the widest
    # question in the template — using that same wide column width to space
    # true_false columns left a large, pointless gap between them.
    tf_col_width = LABEL_W + 2 * BUBBLE_STEP
    tf_cap       = 2

    # Sections fully partition question_config server-side (validated in
    # schemas/exam_templates.py), but stay defensive here: a template with
    # no sections configured falls back to one implicit, unnamed section in
    # plain numeric order.
    covered, ordered_sections = set(), []
    for section in (sections if isinstance(sections, list) else []):
        section_keys = [
            qid for qid in section.get("question_ids", [])
            if qid in question_config and qid not in covered
        ]
        covered.update(section_keys)
        if section_keys:
            ordered_sections.append((section.get("name"), section.get("type", "multiple_choice"), section_keys))
    leftover = [key for key in keys if key not in covered]
    if leftover:
        ordered_sections.append((None, "multiple_choice", leftover))

    questions   = []
    page        = 0
    active_col  = 0  # column currently being filled; only ever moves forward
    col_heights = [0] * n_columns
    # A column's width is only decided the first time something is placed
    # in it (None means "not opened yet this page") and then stays fixed
    # for the rest of the page, even if a later section here would have
    # preferred a different width — columns are positioned cumulatively
    # (col_x below), so once earlier columns commit to a width, an earlier
    # one changing width later would shift every column after it and
    # overlap whatever's already drawn there.
    col_widths: list[int | None] = [None] * n_columns

    def col_x(col: int) -> int:
        x = MARGIN_X
        for i in range(col):
            # A column's width lock is released (None) once a multi-column
            # span passes through it, so a later, differently-widthed
            # section can reclaim it — but the pixels already drawn there
            # don't move. Only the standard multiple_choice grid width ever
            # spans multiple columns (true_false questions never need more
            # than one), so a released column's actual on-page width is
            # always col_width.
            x += (col_widths[i] if col_widths[i] is not None else col_width) + COL_GAP
        return x

    def span_width_for(start_col: int, span: int, width: int) -> int:
        """Pixel width of span columns starting at start_col, using width
        per column — except a span reaching the last column claims every
        remaining pixel up to the true page margin instead. An earlier
        column narrower than its assumed share (e.g. a true_false column,
        see col_x) leaves slack that only the final column can claim, since
        there's no column after it to hand that slack to.
        """
        if start_col + span == n_columns:
            return (TEMPLATE_W - MARGIN_X) - col_x(start_col)
        return span * width + (span - 1) * COL_GAP

    def best_span(start_col: int, width: int, n_opts: int) -> tuple[int, int, int, int]:
        """How many columns, starting at start_col, this question should
        claim: never more than the run of columns nothing else has used yet
        (col_widths is None) to its right, and never more than actually
        shortens its wrapped-row count — claims exactly as much width as
        helps, never the whole row just because it's available. Row count
        only ever plateaus or drops as span grows (never rises), but it can
        plateau for a span or two before dropping again (integer division),
        so this checks every reachable span rather than stopping at the
        first one that doesn't immediately help.
        """
        max_span = 1
        while start_col + max_span < n_columns and col_widths[start_col + max_span] is None:
            max_span += 1
        best = None
        for span in range(1, max_span + 1):
            width_px = span_width_for(start_col, span, width)
            cap      = max(1, (width_px - LABEL_W) // BUBBLE_STEP)
            rows     = _bubble_rows_for(n_opts, cap)
            if best is None or rows < best[3]:
                best = (span, cap, width_px, rows)
        return best

    def place(key: str, section_name: str | None, section_start: bool, start_col: int, span: int, row: int, cap: int, width: int, span_width: int) -> None:
        col_left        = col_x(start_col)
        choices         = question_config[key]["choices"]
        options_per_row = min(len(choices), cap)
        center_y        = HEADER_H + row * ROW_HEIGHT + ROW_HEIGHT // 2
        questions.append({
            "id":      key,
            "page":    page,
            "section_name": section_name,
            "section_start": section_start,
            "col_left": col_left,
            "col_width": span_width,
            "label_x": col_left + LABEL_W // 2,
            "cy":      center_y,
            "bubbles": [
                {
                    "label": label,
                    "x": col_left + LABEL_W + BUBBLE_D // 2 + (j % options_per_row) * BUBBLE_STEP,
                    "y": center_y + (j // options_per_row) * ROW_HEIGHT,
                }
                for j, label in enumerate(choices)
            ],
        })
        new_height = row + _bubble_rows_for(len(choices), cap)
        for c in range(start_col, start_col + span):
            col_heights[c] = new_height
            # A single-column placement locks that column to its width, so
            # later content lines up with it. A multi-column span merges
            # those columns into one row for this question only — nothing
            # below is bound to that merged width, so every column it
            # touched gets to pick fresh next time, same as a lone column
            # that was never claimed.
            col_widths[c]  = width if span == 1 else None

    def advance_column() -> None:
        """Move to the next column, rolling onto a fresh page once every
        column on this one has been used. Never revisits an earlier column:
        like ordinary multi-column text, content flows forward only."""
        nonlocal active_col, page
        active_col += 1
        if active_col >= n_columns:
            active_col = 0
            page += 1
            for i in range(n_columns):
                col_heights[i] = 0
                col_widths[i]  = None

    for section_name, section_type, section_keys in ordered_sections:
        is_tf                = section_type == "true_false"
        section_width, section_cap = (tf_col_width, tf_cap) if is_tf else (col_width, options_per_row_cap)
        has_wide     = any(is_wide_key[k] for k in section_keys)
        has_header   = section_name is not None

        if not has_wide:
            height = _section_height(section_keys, question_config, section_cap, has_header)
            if height <= ROWS_PER_COL:
                # Prefer a column already on this page over rolling to a
                # fresh page, even if that means skipping past a column
                # that's merely too full rather than genuinely empty —
                # horizontal space on the current page beats a new page.
                # A column already locked to a different width (e.g. a
                # true_false column this section, being multiple_choice,
                # can't reuse) is skipped too, not just a full one — using
                # it anyway would place bubbles past its narrower edge.
                fits_col = next(
                    (
                        c for c in range(active_col, n_columns)
                        if col_widths[c] in (None, section_width) and col_heights[c] + height <= ROWS_PER_COL
                    ),
                    None,
                )
                if fits_col is not None:
                    active_col = fits_col
                    for i, key in enumerate(section_keys):
                        n_opts        = len(question_config[key]["choices"])
                        section_start = i == 0 and has_header
                        extra         = 1 if section_start else 0
                        # Still confined to columns starting at active_col
                        # (that's what "keep together" means), but each
                        # question spreads into whatever still-free columns
                        # next to it shorten its own wrapped rows, same as
                        # the per-question fallback below.
                        span, cap, span_width, _ = best_span(active_col, section_width, n_opts)
                        row = max(col_heights[active_col:active_col + span]) + extra
                        place(key, section_name, section_start, active_col, span, row, cap, section_width, span_width)
                    continue
                # Nothing left on this page fits it as one block: falls
                # through below and splits across columns/pages instead.

        last_header_at = None
        for key in section_keys:
            wants_header = section_name is not None
            n_opts       = len(question_config[key]["choices"])
            while True:
                # Keep moving past a column already locked to a different
                # width (e.g. true_false content skipping a wider
                # multiple_choice column, or vice versa) — reusing it would
                # misplace bubbles.
                if col_widths[active_col] not in (None, section_width):
                    advance_column()
                    continue
                span, cap, span_width, bubble_rows = best_span(active_col, section_width, n_opts)
                section_start = wants_header and (page, active_col) != last_header_at
                extra         = 1 if section_start else 0
                baseline      = max(col_heights[active_col:active_col + span])
                if baseline + extra + bubble_rows <= ROWS_PER_COL:
                    break
                if active_col == 0 and baseline == 0:
                    # Even alone, spanning every column on a fresh page,
                    # this doesn't fit — the upfront cap_full check should
                    # already have caught this; this is just the backstop
                    # that keeps this loop from spinning forever.
                    raise BadRequestError(
                        f"Question {key} has {n_opts} options, which needs {bubble_rows} lines, "
                        f"more than fit in a single column ({ROWS_PER_COL} lines) even spanning "
                        "the full page width. Reduce its option count or split it into multiple "
                        "questions.",
                        code="layout_overflow",
                    )
                advance_column()
            row = baseline + extra
            place(key, section_name, section_start, active_col, span, row, cap, section_width, span_width)
            last_header_at = (page, active_col)

    _mark_spanning_headers(questions)
    return questions


def _mark_spanning_headers(questions: list[dict]) -> None:
    """A section that reprints its header across several columns in a row
    (because it kept flowing rather than fitting in one) reads as one
    header repeated needlessly when those columns' tops actually line up —
    so merge each such run into a single header spanning all of them,
    drawn once from the leftmost column's left edge to the rightmost
    column's right edge, instead of one per column.

    Every question keeps its own "section_start" (still needed to reserve
    a header-row's worth of space above it, regardless of who draws the
    text there); this only decides who actually draws it and how wide.
    Only genuinely adjacent, same-row, same-page, same-section columns
    merge — anything else (a column that continues lower down, a
    different page, a gap left by a wide-question band) keeps its own
    header, since there'd be nothing for a merged header to span cleanly.
    """
    starts = [q for q in questions if q["section_start"]]
    i = 0
    while i < len(starts):
        group = [starts[i]]
        while (
            i + len(group) < len(starts)
            and (candidate := starts[i + len(group)])["section_name"] == group[0]["section_name"]
            and candidate["page"] == group[0]["page"]
            and candidate["cy"] == group[0]["cy"]
            and candidate["col_left"] == group[-1]["col_left"] + group[-1]["col_width"] + COL_GAP
        ):
            group.append(candidate)
        span_left  = group[0]["col_left"]
        span_right = group[-1]["col_left"] + group[-1]["col_width"]
        group[0]["draw_header"]       = True
        group[0]["header_span_width"] = span_right - span_left
        for q in group[1:]:
            q["draw_header"] = False
        i += len(group)


def _answer_pages(questions: list[dict]) -> list[list[dict]]:
    page_count = max((question.get("page", 0) for question in questions), default=0) + 1
    return [
        [question for question in questions if question.get("page", 0) == page]
        for page in range(page_count)
    ]


def _t2p(tx: float, ty: float) -> tuple[float, float]:
    """Convert template pixel coordinates to PDF point coordinates."""
    return OFFSET_X + tx * SCALE, PAGE_H_PT - OFFSET_Y - ty * SCALE


def _draw_anchors(c, anchor_positions: list) -> None:
    """Draw a bullseye anchor marker at each position."""
    from reportlab.lib.colors import black, white

    outer_r = (ANCHOR_SIZE / 2) * SCALE
    ring_r  = outer_r - ANCHOR_OUTER_RING * SCALE
    inner_r = ring_r  - ANCHOR_WHITE_RING * SCALE

    for cx, cy in anchor_positions:
        px, py = _t2p(cx, cy)
        c.setFillColor(black)
        c.ellipse(px - outer_r, py - outer_r, px + outer_r, py + outer_r, fill=1, stroke=0)
        c.setFillColor(white)
        c.ellipse(px - ring_r,  py - ring_r,  px + ring_r,  py + ring_r,  fill=1, stroke=0)
        c.setFillColor(black)
        c.ellipse(px - inner_r, py - inner_r, px + inner_r, py + inner_r, fill=1, stroke=0)


def _draw_bubble(c, bx: float, by: float, label: str, filled: bool = False, darkness: float = 1.0) -> None:
    from reportlab.lib.colors import black, white, Color
    r = (BUBBLE_D / 2) * SCALE
    c.setFillColor(white)
    c.setStrokeColor(black)
    c.setLineWidth(0.8)
    c.circle(bx, by, r, fill=1, stroke=1)
    if filled:
        # Solid fill well inside the outline — comfortably above the mark
        # template's fillThreshold (see _make_scan_template's "config"),
        # emulating a pencil-filled bubble for seeded/synthetic scans. No
        # label drawn on top -- a real filled-in bubble hides its letter too.
        #
        # darkness scales the fill from solid black (1.0, a firm pencil/pen
        # mark) toward light gray as it approaches 0, so synthetic scans can
        # mimic the fainter marks real handmade scans sometimes have instead
        # of only ever testing the easiest, darkest case.
        gray = max(0.0, min(1.0, 1.0 - darkness))
        c.setFillColor(Color(gray, gray, gray))
        c.circle(bx, by, r * 0.95, fill=1, stroke=0)
        return
    c.setFont("Helvetica", 4.8)
    c.setFillColor(black)
    c.drawCentredString(bx, by - 2, label)


def _draw_exam_header(c, title: str, subtitle: str) -> None:
    """Exam name and course/date line for an exam-specific answer page.

    Drawn in the margin between the top anchors and the first separator
    line (template y 48-158), which every other draw call already leaves
    blank, so this can't shift anchor or bubble positions the OMR service
    depends on.
    """
    from reportlab.lib.colors import black

    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(*_t2p(TEMPLATE_W / 2, 90), title)
    c.setFont("Helvetica", 8)
    c.drawCentredString(*_t2p(TEMPLATE_W / 2, 112), subtitle)


def _draw_front_page(
    c,
    questions: list[dict],
    n_versions: int,
    header: tuple[str, str] | None = None,
    show_version: bool = True,
    fill_answers: dict[str, list[str]] | None = None,
    fill_version: str | None = None,
    darkness: float = 1.0,
) -> None:
    from reportlab.lib.colors import black, lightgrey

    _draw_anchors(c, ANCHORS_FRONT)
    if header:
        _draw_exam_header(c, *header)

    left_x  = OFFSET_X + MARGIN_X * SCALE
    right_x = OFFSET_X + (TEMPLATE_W - MARGIN_X) * SCALE

    def _draw_separator(template_y: float, x1: float = left_x, x2: float = right_x) -> None:
        c.setStrokeColor(lightgrey)
        c.setLineWidth(0.4)
        y = PAGE_H_PT - OFFSET_Y - template_y * SCALE
        c.line(x1, y, x2, y)

    _draw_separator(158)

    c.setFont("Helvetica", 7.5)
    for i, line in enumerate([
        "•  Use a dark pencil or pen. Fill bubbles completely.",
        "•  Erase cleanly before changing an answer.",
        "•  Fill in your student information on the back of this sheet.",
    ]):
        c.drawString(left_x, PAGE_H_PT - OFFSET_Y - (174 + i * 15) * SCALE, line)

    _draw_separator(210)

    # Version bubbles — a single-version template has nothing to disambiguate,
    # so the row (and its "Ver" label) is skipped entirely.
    if n_versions > 1 and show_version:
        label_x, label_y = _t2p(MARGIN_X + LABEL_W // 2, VERSION_CY)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(black)
        c.drawCentredString(label_x, label_y - 2.5, "Ver")
        for j, ch in enumerate(LETTERS[:n_versions]):
            _draw_bubble(
                c, *_t2p(MARGIN_X + LABEL_W + BUBBLE_D // 2 + j * BUBBLE_STEP, VERSION_CY), ch,
                filled=(ch == fill_version), darkness=darkness,
            )

    _draw_separator(260)

    # Answer bubbles
    for q in questions:
        if q.get("draw_header"):
            # row_top is the top of this row's own slot; _compute_questions
            # reserved HEADER_EXTRA_H immediately above it for this header, on
            # top of the normal ROW_HEIGHT/2 gap already above every row.
            # header_span_width may cover more than this one question's own
            # column, when _mark_spanning_headers merged several adjacent,
            # aligned columns into a single header rather than repeating it.
            row_top = q["cy"] - ROW_HEIGHT // 2
            header_top = row_top - HEADER_EXTRA_H
            span_width = q.get("header_span_width", q["col_width"])
            col_x1 = OFFSET_X + q["col_left"] * SCALE
            col_x2 = OFFSET_X + (q["col_left"] + span_width) * SCALE
            text_x, text_y = _t2p(q["col_left"] + 4, header_top + 24)
            c.setFillColor(black)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(text_x, text_y, q["section_name"][:32])
            _draw_separator(row_top - 6, col_x1, col_x2)
        label_x, label_y = _t2p(q["label_x"], q["cy"])
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(black)
        c.drawCentredString(label_x, label_y - 2.5, q["id"])
        selected = fill_answers.get(q["id"], []) if fill_answers else []
        for b in q["bubbles"]:
            _draw_bubble(c, *_t2p(b["x"], b["y"]), b["label"], filled=(b["label"] in selected), darkness=darkness)


def _draw_info_section(
    c, title: str, options: list[str], n_rows: int, start_y: int,
    fill_chars: str | None = None, darkness: float = 1.0,
) -> int:
    from reportlab.lib.colors import black

    # Match the bubble-to-bubble gap (BUBBLE_STEP - BUBBLE_D) between the write-in line and first bubble
    bubble_x_positions = [MARGIN_X + WRITEIN_W + (j + 1) * BUBBLE_STEP - BUBBLE_D // 2 for j in range(len(options))]

    title_x, title_y = _t2p(TEMPLATE_W / 2, start_y + SECTION_LBL_H / 2)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(black)
    c.drawCentredString(title_x, title_y - 3, title)

    row_top = start_y + SECTION_LBL_H + COL_HDR_H
    for i in range(n_rows):
        cy = row_top + i * INFO_ROW_H + INFO_ROW_H // 2
        line_x1, line_y = _t2p(MARGIN_X + 2,             cy + INFO_ROW_H // 2 - 5)
        line_x2, _      = _t2p(MARGIN_X + WRITEIN_W - 2, cy + INFO_ROW_H // 2 - 5)
        c.setStrokeColor(black)
        c.setLineWidth(0.6)
        c.line(line_x1, line_y, line_x2, line_y)
        row_char = fill_chars[i] if fill_chars is not None and i < len(fill_chars) else None
        for j, opt in enumerate(options):
            _draw_bubble(c, *_t2p(bubble_x_positions[j], cy), opt, filled=(opt == row_char), darkness=darkness)

    return row_top + n_rows * INFO_ROW_H


def _draw_back_page(
    c,
    fill_last: str | None = None,
    fill_first: str | None = None,
    fill_id: str | None = None,
    darkness: float = 1.0,
) -> None:
    from reportlab.lib.colors import black
    _draw_anchors(c, ANCHORS_BACK)
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(black)
    c.drawCentredString(PAGE_W_PT / 2, PAGE_H_PT - OFFSET_Y - 105 * SCALE, "Student Information")
    y = 120
    y = _draw_info_section(c, "Last Name",  LETTERS, N_LAST,  y, fill_chars=fill_last, darkness=darkness) + SECTION_GAP
    y = _draw_info_section(c, "First Name", LETTERS, N_FIRST, y, fill_chars=fill_first, darkness=darkness) + SECTION_GAP
    _draw_info_section(c, "Student ID", DIGITS, N_ID, y, fill_chars=fill_id, darkness=darkness)


def _render_pdf(
    questions: list[dict],
    n_versions: int,
    *,
    header: tuple[str, str] | None = None,
    include_back: bool = True,
    fill_answers: dict[str, list[str]] | None = None,
    fill_version: str | None = None,
    fill_student_id: str | None = None,
    fill_first_name: str | None = None,
    fill_last_name: str | None = None,
    darkness: float = 1.0,
    identity_darkness: float | None = None,
) -> bytes:
    """Render answer pages and, unless previewing, student information.

    The fill_* params draw a mark over the selected bubble(s), and
    everything else about the layout is identical to a blank render, so a
    seeded/synthetic "filled" scan uses the exact same bubble geometry the
    real OMR mark template was built from. darkness (0.0-1.0) controls how
    solid the answer/version marks are, from a firm pencil/pen press (1.0)
    toward a faint one (near 0.0). identity_darkness, if given, controls the
    back page's name/ID marks independently -- useful for varying answer
    darkness without also starving the name/ID fields, which need less
    margin to lose before individual letters stop being detected at all (a
    26-option name row has much less headroom than a 5-option question row;
    see marker.go's confidence comments). Defaults to darkness when omitted,
    so existing callers are unaffected.
    """
    from reportlab.pdfgen import canvas as rl_canvas
    buf = io.BytesIO()
    # invariant=1: suppresses reportlab's default embedded CreationDate/ID
    # (otherwise wall-clock-derived), so two calls with identical arguments
    # produce byte-identical PDFs -- otherwise even a fixed-seed fixture
    # generator can't produce reproducible output.
    c   = rl_canvas.Canvas(buf, pagesize=(PAGE_W_PT, PAGE_H_PT), invariant=1)
    pages = _answer_pages(questions)
    for page, page_questions in enumerate(pages):
        _draw_front_page(
            c,
            page_questions,
            n_versions,
            header=header,
            show_version=page == 0,
            fill_answers=fill_answers,
            fill_version=fill_version,
            darkness=darkness,
        )
        if include_back or page < len(pages) - 1:
            c.showPage()
    if include_back:
        _draw_back_page(
            c, fill_last=fill_last_name, fill_first=fill_first_name, fill_id=fill_student_id,
            darkness=identity_darkness if identity_darkness is not None else darkness,
        )
    c.save()
    return buf.getvalue()


def render_filled_scan_pdf(
    exam_template: ExamTemplate,
    *,
    version: str,
    student_id: str,
    first_name: str,
    last_name: str,
    answers: dict[str, list[str]],
    darkness: float = 1.0,
    identity_darkness: float | None = None,
    header: tuple[str, str] | None = None,
) -> bytes:
    """Renders this template's bubble sheet with a specific student's answers,
    name, ID, and version already bubbled in — a synthetic "filled scan" for
    seeding real data through the actual OMR/grading pipeline instead of
    fabricating OMRDetectedMark rows directly. darkness (0.0-1.0) controls
    how solid the answer/version marks are; identity_darkness independently
    controls the name/ID marks (defaults to darkness when omitted) -- see
    _render_pdf for why these are worth varying separately. header, if given
    (see build_exam_header), prints the real exam name/course/date on the
    front page, the same as a real distributed exam sheet -- omit it only
    when no specific Exam applies (e.g. a bare template preview)."""
    questions = _compute_questions(exam_template.question_config, exam_template.sections)
    return _render_pdf(
        questions,
        exam_template.n_versions,
        header=header,
        fill_answers=answers,
        fill_version=version,
        fill_student_id=student_id,
        fill_first_name=first_name.upper(),
        fill_last_name=last_name.upper(),
        darkness=darkness,
        identity_darkness=identity_darkness,
    )


def render_filled_ubc_scan_pdf(
    *,
    answers: dict[str, list[str]],
    student_id: str,
    first_name: str,
    last_name: str,
    darkness: float = 1.0,
    identity_darkness: float | None = None,
) -> bytes:
    """Renders the UBC blueprint's two-page bubble sheet with the given
    answers/name/ID already bubbled in, the same synthetic-scan testing
    purpose render_filled_scan_pdf serves the custom exam generator, but for
    the UBC template.

    Unlike the custom generator, this doesn't compute a layout: ubc/mark.json
    already has every bubble's exact position, so fills are drawn directly
    onto canonical_front.png/canonical_back.png, pre-warped, anchor-aligned
    renders of the UBC blueprint's own reference sheets (see
    app/omr/data/templates/ubc/canonical_*.png) at the coordinates the real
    mark template uses. darkness (0.0-1.0) controls how solid the answer
    marks (mark.json ids "Q1".."Q100") are, from a firm pencil/pen press
    (1.0) toward a faint one (near 0.0); identity_darkness independently
    controls the name/ID marks (ids "F"/"L"/"I"-prefixed), defaulting to
    darkness when omitted. These are worth varying separately: a 26-option
    name row has much less confidence-scoring headroom to lose than a
    5-option question row before individual letters stop being detected at
    all (see marker.go's confidence comments), so coupling them to the same
    randomized value produces name reads that look broken even when the
    darkness being tested is really about answer-mark robustness.
    """
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    mark_tmpl = json.loads(_load_ubc_mark_template_bytes())

    fills: dict[str, list[str]] = {qid: list(labels) for qid, labels in answers.items()}
    for i, ch in enumerate(last_name.upper()):
        fills[f"L{i + 1}"] = [ch]
    for i, ch in enumerate(first_name.upper()):
        fills[f"F{i + 1}"] = [ch]
    for i, ch in enumerate(student_id):
        fills[f"I{i + 1}"] = [ch]

    question_gray = max(0, min(255, round(255 * (1.0 - darkness))))
    identity_gray = max(
        0, min(255, round(255 * (1.0 - (identity_darkness if identity_darkness is not None else darkness))))
    )

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(PAGE_W_PT, PAGE_H_PT), invariant=1)  # see _render_pdf's comment

    for page, image_name in zip(mark_tmpl["pages"], ("canonical_front.png", "canonical_back.png")):
        img = Image.open(UBC_TEMPLATE_DIR / image_name).convert("L")
        draw = ImageDraw.Draw(img)
        for q in page["questions"]:
            selected = fills.get(q["id"], [])
            if not selected:
                continue
            gray = identity_gray if q["id"][0] in ("F", "L", "I") else question_gray
            r = min(q["bubbleWidth"], q["bubbleHeight"]) / 2 * 0.95
            for opt in q["options"]:
                if opt["label"] not in selected:
                    continue
                x, y = opt["x"], opt["y"]
                draw.ellipse((x - r, y - r, x + r, y + r), fill=gray)

        scale, offset_x, offset_y = _fit_scale_offset(img.width, img.height)
        c.drawImage(
            ImageReader(img), offset_x, offset_y,
            width=img.width * scale, height=img.height * scale,
        )
        c.showPage()

    c.save()
    return buf.getvalue()


def _compute_back_page_questions() -> list[dict]:
    """Compute bubble centre coordinates for all back-page info sections."""
    all_questions: list[dict] = []

    def _section(prefix: str, options: list[str], n_rows: int, start_y: int) -> int:
        bubble_x = [
            MARGIN_X + WRITEIN_W + (j + 1) * BUBBLE_STEP - BUBBLE_D // 2
            for j in range(len(options))
        ]
        row_top = start_y + SECTION_LBL_H + COL_HDR_H
        for i in range(n_rows):
            cy = row_top + i * INFO_ROW_H + INFO_ROW_H // 2
            all_questions.append({
                "id": f"{prefix}{i + 1}",
                "bubbles": [{"label": lbl, "x": bubble_x[j], "y": cy} for j, lbl in enumerate(options)],
            })
        return row_top + n_rows * INFO_ROW_H

    y = 120
    y = _section("L", LETTERS, N_LAST,  y) + SECTION_GAP
    y = _section("F", LETTERS, N_FIRST, y) + SECTION_GAP
    _section("I", DIGITS, N_ID, y)
    return all_questions


def _build_answer_key_json(template, answer_key) -> dict:
    """Produce the standalone answer_key JSON payload for one exam version."""
    question_config = template.question_config
    scoring_rules = answer_key.scoring_rules or {}
    default_points = scoring_rules.get("default_points_per_question", 1.0)

    questions = {}
    total_points = 0.0
    for q_num, config in question_config.items():
        ak_item = answer_key.answer_key.get(q_num, {})
        pts = ak_item.get("points") or default_points
        total_points += pts
        questions[q_num] = {
            "choices": config["choices"],
            "grading_type": ak_item.get("grading_type", "single"),
            "correct_choices": ak_item.get("correct_choices", []),
            "points": pts,
            "partial_weights": ak_item.get("partial_weights"),
        }

    return {
        "exam_id": str(answer_key.exam_id),
        "exam_template_id": str(answer_key.exam_template_id),
        "exam_version": answer_key.exam_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "default_points_per_question": default_points,
        "total_points": total_points,
        "questions": questions,
    }


def _build_answer_key_csv(template, answer_key) -> str:
    """Produce a CSV answer-key export that can be imported by the UI."""
    exported = _build_answer_key_json(template, answer_key)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "question",
            "correct_choices",
            "grading_type",
            "points",
            "partial_weights",
            "exam_version",
            "default_points_per_question",
        ),
    )
    writer.writeheader()
    for question, item in exported["questions"].items():
        writer.writerow(
            {
                "question": question,
                "correct_choices": "|".join(item["correct_choices"]),
                "grading_type": item["grading_type"],
                "points": item["points"],
                "partial_weights": json.dumps(item["partial_weights"] or {}),
                "exam_version": exported["exam_version"] or "",
                "default_points_per_question": exported["default_points_per_question"],
            }
        )
    return output.getvalue()


def _build_mark_template(
    questions: list[dict],
    n_versions: int,
) -> bytes:
    version_cx = MARGIN_X + LABEL_W + BUBBLE_D // 2
    # A single-version template has no version bubble on the sheet (see
    # _draw_front_page), so the mark template shouldn't expect one either.
    version_questions = []
    if n_versions > 1:
        version_questions = [{
            "id":           "V1",
            "type":         "single",
            "bubbleWidth":  BUBBLE_D,
            "bubbleHeight": BUBBLE_D,
            "options": [
                {"label": ch, "x": version_cx + j * BUBBLE_STEP, "y": VERSION_CY}
                for j, ch in enumerate(LETTERS[:n_versions])
            ],
        }]

    answer_pages = []
    for page, page_questions in enumerate(_answer_pages(questions)):
        answer_pages.append({
            "questions": (version_questions if page == 0 else []) + [
                {
                    "id":           f"Q{q['id']}",
                    # Registration is independent of an exam's answer keys.
                    # Capture every selected bubble here; grading applies the
                    # eventual single/multiple/partial semantics itself.
                    "type":         "multi",
                    "bubbleWidth":  BUBBLE_D,
                    "bubbleHeight": BUBBLE_D,
                    "options":      [{"label": b["label"], "x": b["x"], "y": b["y"]} for b in q["bubbles"]],
                }
                for q in page_questions
            ],
        })

    back_questions = [
        {
            "id":           bq["id"],
            "type":         "single",
            "bubbleWidth":  BUBBLE_D,
            "bubbleHeight": BUBBLE_D,
            "options":      [{"label": b["label"], "x": b["x"], "y": b["y"]} for b in bq["bubbles"]],
        }
        for bq in _compute_back_page_questions()
    ]

    return json.dumps({
        "config": {"fillThreshold": 0.28, "bubbleInset": 0.75, "flagThreshold": 0.25, "searchRadius": 5},
        "pages": [
            *answer_pages,
            {"questions": back_questions},
        ],
    }, indent=2).encode()


def _store_template_layout(exam_template, storage_repo: StorageRepository) -> str | None:
    """Store the printable sheet and scan layout, returning the PDF path."""
    base          = f"generated/{exam_template.id}"
    scan_tmpl_key = f"{base}/scan_template.json"

    if exam_template.blueprint == UBCO_100_BLUEPRINT:
        ubc_scan_template, _ = _load_ubc_scan_template()
        storage_repo.upload_file(json.dumps(ubc_scan_template, indent=2).encode(), scan_tmpl_key)
        return None

    questions = _compute_questions(
        exam_template.question_config, exam_template.sections
    )
    scan_template = _make_scan_template(len(_answer_pages(questions)))
    pdf       = _render_pdf(questions, exam_template.n_versions)
    pdf_key   = f"{base}/bubble_sheet.pdf"

    storage_repo.upload_file(_make_anchor_png(),                           ANCHOR_PNG_KEY)
    storage_repo.upload_file(pdf,                                          pdf_key)
    storage_repo.upload_file(json.dumps(scan_template, indent=2).encode(), scan_tmpl_key)
    return pdf_key


async def generate_template_pdf(
    db: AsyncSession,
    storage_repo: StorageRepository,
    template_id: UUID,
    requesting_user_id: UUID,
):
    """Generate a reusable blank bubble-sheet PDF and scan template for an ExamTemplate.

    This step produces the physical sheet artefacts only — no exam-specific
    information is embedded. Run finalize_exam_template to produce the mark
    template and register the layout with OMR.

    UBCO_100_BLUEPRINT templates use an already-printed physical sheet, so
    there's no PDF to draw — this just records the hand-made scan template
    (see UBC_TEMPLATE_DIR) instead of rendering a custom layout.
    """
    exam_template = await get_exam_template_by_id(db, template_id)
    if not exam_template:
        raise NotFoundError("Exam template not found", code="template_not_found")

    if exam_template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorised to generate for this exam template", code="forbidden")
    if exam_template.archived_at is not None:
        raise ConflictError(
            "Archived templates are read-only. Restore this template before generating it.",
            code="template_archived_read_only",
        )

    pdf_key = _store_template_layout(exam_template, storage_repo)
    if pdf_key is None:
        return exam_template

    try:
        exam_template.generated_pdf_path = pdf_key
        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return exam_template


async def render_template_preview_pdf(
    db: AsyncSession,
    template_id: UUID,
    requesting_user_id: UUID,
) -> bytes:
    """Render the answer pages for the in-app preview.

    Computed fresh from the template's current question_config each call
    rather than read back from storage, so it always matches what a Save
    would (re)generate, even before that Save has actually happened.
    """
    exam_template = await get_exam_template_by_id(db, template_id)
    if not exam_template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if exam_template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorised to preview this exam template", code="forbidden")
    if exam_template.blueprint:
        raise BadRequestError(
            "This template uses a pre-printed physical sheet with no PDF to preview.",
            code="pdf_not_generated",
        )

    questions = _compute_questions(
        exam_template.question_config, exam_template.sections
    )
    return _render_pdf(questions, exam_template.n_versions, include_back=False)


async def _authorize_exam_pdf_action(db: AsyncSession, exam, requesting_user: User):
    """Same rule release_exam uses: only an admin or the professor who owns
    the exam's course may generate or download its PDF. Returns the course
    so callers that also need it (generate_exam_pdf, for the header text)
    don't have to look it up a second time.
    """
    course = await get_course_by_id(db, exam.course_id)
    if not course:
        raise NotFoundError("Course not found", code="course_not_found")
    if requesting_user.role_enum != UserRole.ADMIN and course.created_by != requesting_user.id:
        raise ForbiddenError("Not authorised to manage this exam's PDF", code="forbidden")
    return course


def build_exam_header(exam, course) -> tuple[str, str]:
    """The (title, subtitle) pair printed on an exam-specific bubble sheet's
    front page — exam name plus course and start date/time. Shared by
    generate_exam_pdf (blank sheet for printing/distribution) and every
    filled-scan renderer that fills in a real, finalized exam rather than a
    bare template, so a filled sheet always looks like the real thing a
    student would have received instead of a blank template render."""
    schedule = (
        exam.start_time.strftime("%b %d, %Y · %I:%M %p")
        if exam.start_time
        else "Date not scheduled"
    )
    return exam.name, f"{course.name} · {schedule}"


async def generate_exam_pdf(
    db: AsyncSession,
    storage_repo: StorageRepository,
    exam_id: UUID,
    requesting_user: User,
):
    """Renders and stores this exam's bubble sheet: the template's layout
    plus the exam's name, course, and date/time printed on the front page.

    Requires the template to already be registered with OMR (see
    finalize_exam_template). Answer-key completeness is exam-specific and is
    checked separately before student scan upload and grading.
    """
    exam = await get_exam_by_id(db, exam_id)
    if not exam:
        raise NotFoundError("Exam not found", code="exam_not_found")
    course = await _authorize_exam_pdf_action(db, exam, requesting_user)

    if not exam.exam_template_id:
        raise BadRequestError("This exam has no template attached.", code="template_missing")
    exam_template = await get_exam_template_by_id(db, exam.exam_template_id)
    if not exam_template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if exam_template.blueprint:
        raise BadRequestError(
            "This template uses a pre-printed physical sheet, so there's no PDF to add exam details to.",
            code="pdf_not_generated",
        )
    if not exam_template.omr_template_id:
        raise BadRequestError(
            "Finalize the template (register it with OMR) before generating the exam PDF.",
            code="template_not_finalized",
        )

    questions = _compute_questions(
        exam_template.question_config, exam_template.sections
    )
    header = build_exam_header(exam, course)
    pdf = _render_pdf(questions, exam_template.n_versions, header=header)
    pdf_key = f"generated/exam/{exam.id}/exam_sheet.pdf"
    storage_repo.upload_file(pdf, pdf_key)

    try:
        exam.generated_pdf_path = pdf_key
        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return exam


async def get_exam_pdf_bytes(
    db: AsyncSession,
    storage_repo: StorageRepository,
    exam_id: UUID,
    requesting_user: User,
) -> tuple[bytes, str]:
    """Returns the stored exam PDF and the exam's name, for the download
    endpoint to build a filename from."""
    exam = await get_exam_by_id(db, exam_id)
    if not exam:
        raise NotFoundError("Exam not found", code="exam_not_found")
    await _authorize_exam_pdf_action(db, exam, requesting_user)
    if not exam.generated_pdf_path:
        raise BadRequestError("PDF has not been generated for this exam yet", code="pdf_not_generated")
    return storage_repo.download_file(exam.generated_pdf_path), exam.name


async def finalize_exam_template(
    db: AsyncSession,
    storage_repo: StorageRepository,
    template_id: UUID,
    requesting_user_id: UUID,
):
    """Prepare missing layout files and register the template with OMR."""
    exam_template = await get_exam_template_by_id(db, template_id)
    if not exam_template:
        raise NotFoundError("Exam template not found", code="template_not_found")

    if exam_template.created_by != requesting_user_id:
        raise ForbiddenError("Not authorised to finalize this exam template", code="forbidden")
    if exam_template.archived_at is not None:
        raise ConflictError(
            "Archived templates are read-only. Restore this template before finalizing it.",
            code="template_archived_read_only",
        )

    if exam_template.omr_template_id:
        return exam_template

    is_ubc_blueprint = exam_template.blueprint == UBCO_100_BLUEPRINT
    if not is_ubc_blueprint and not exam_template.generated_pdf_path:
        exam_template.generated_pdf_path = _store_template_layout(exam_template, storage_repo)

    base          = f"generated/{exam_template.id}"
    mark_tmpl_key = f"{base}/mark_template.json"
    scan_tmpl_key = f"{base}/scan_template.json"

    if is_ubc_blueprint:
        mark = _load_ubc_mark_template_bytes()
        preprocessing_payload, anchor_images = _load_ubc_scan_template()
        # Finalize doesn't require generate_template_pdf to have run for this
        # blueprint, so keep the archived scan template in sync here too.
        storage_repo.upload_file(json.dumps(preprocessing_payload, indent=2).encode(), scan_tmpl_key)
    else:
        questions      = _compute_questions(
            exam_template.question_config, exam_template.sections
        )
        mark           = _build_mark_template(questions, exam_template.n_versions)

        preprocessing_payload = _make_scan_template(len(_answer_pages(questions)))
        anchor_jpeg = _make_anchor_jpeg()
        anchor_images = {
            (page_idx, anchor_idx): anchor_jpeg
            for page_idx, page in enumerate(preprocessing_payload["pages"])
            for anchor_idx in range(len(page["anchors"]))
        }

    storage_repo.upload_file(mark, mark_tmpl_key)

    try:
        preprocess_template_id = await upload_preprocessing_template(
            PreprocessingTemplate.model_validate(preprocessing_payload), anchor_images
        )
        mark_template_id = await upload_marking_template(MarkingTemplate.model_validate_json(mark))
    except OMRClientError as exc:
        raise ServiceUnavailableError(
            f"OMR service rejected the generated template: {exc}",
            code="omr_template_upload_failed",
        ) from exc

    try:
        omr_template = await create_omr_template(
            db,
            name=f"OMR: template {exam_template.id} v{exam_template.version}",
            page_count=len(preprocessing_payload["pages"]),
            scan_template_path=scan_tmpl_key,
            mark_template_path=mark_tmpl_key,
            preprocess_template_id=preprocess_template_id,
            mark_template_id=mark_template_id,
            native_dpi=preprocessing_payload.get("nativeDpi") or None,
        )
        exam_template.omr_template_id = omr_template.id
        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return exam_template
