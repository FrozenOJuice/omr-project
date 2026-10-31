import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from errors.exceptions import BadRequestError, ForbiddenError, NotFoundError, ServiceUnavailableError
from integrations.omr_client import OMRClientError
from services.exam_generator import (
    ANCHOR_PAD, ANCHOR_PNG_KEY, ANCHOR_SIZE, ANCHOR_OUTER_RING,
    BUBBLE_D, BUBBLE_STEP, COL_GAP, DIGITS, HEADER_EXTRA_H, HEADER_H, INFO_ROW_H, LABEL_W, LETTERS,
    MARGIN_X, MAX_QUESTION_COUNT, N_FIRST, N_ID, N_LAST, OFFSET_X, OFFSET_Y, PAGE_H_PT, PAGE_W_PT,
    ROW_HEIGHT, ROWS_PER_COL,
    SCAN_TEMPLATE, TEMPLATE_H, TEMPLATE_W,
    _anchor_roi, _answer_pages, _build_answer_key_csv, _build_answer_key_json, _build_mark_template,
    _choose_column_layout, _estimate_rows, _is_wide, _section_height,
    _compute_back_page_questions, _compute_questions,
    _make_anchor_jpeg, _make_anchor_png, _make_page_scan_template, _render_pdf,
    _t2p,
    finalize_exam_template, generate_template_pdf,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _questions(n: int = 3, choices: list[str] | None = None) -> list[dict]:
    """Minimal question list matching _compute_questions output."""
    choices = choices or ["A", "B", "C"]
    return [
        {
            "id": str(i),
            "label_x": MARGIN_X + LABEL_W // 2,
            "cy": HEADER_H + i * ROW_HEIGHT + ROW_HEIGHT // 2,
            "bubbles": [
                {
                    "label": lbl,
                    "x": MARGIN_X + LABEL_W + BUBBLE_D // 2 + j * BUBBLE_STEP,
                    "y": HEADER_H + i * ROW_HEIGHT + ROW_HEIGHT // 2,
                }
                for j, lbl in enumerate(choices)
            ],
        }
        for i in range(1, n + 1)
    ]


def _mock_template(owner_id, template_id=None, question_config=None, generated=False):
    t = MagicMock()
    t.id = template_id or uuid4()
    t.created_by = owner_id
    t.version = 1
    t.n_versions = 4
    t.question_config = question_config or {"1": {"choices": ["A", "B", "C"]}}
    t.sections = None
    t.blueprint = None
    t.omr_template_id = None
    t.generated_pdf_path = f"generated/{t.id}/bubble_sheet.pdf" if generated else None
    t.archived_at = None
    return t


def _mock_omr():
    o = MagicMock()
    o.id = uuid4()
    return o


# ---------------------------------------------------------------------------
# _anchor_roi
# ---------------------------------------------------------------------------

class TestAnchorROI:
    def test_interior_point(self):
        assert _anchor_roi(400, 600) == {
            "min": {"x": 250, "y": 450},
            "max": {"x": 550, "y": 750},
        }

    def test_clamps_min_to_zero_near_top_left(self):
        roi = _anchor_roi(50, 80)
        assert roi["min"] == {"x": 0, "y": 0}

    def test_clamps_max_to_template_bounds_near_bottom_right(self):
        roi = _anchor_roi(TEMPLATE_W - 50, TEMPLATE_H - 100)
        assert roi["max"] == {"x": TEMPLATE_W, "y": TEMPLATE_H}


# ---------------------------------------------------------------------------
# _make_anchor_png
# ---------------------------------------------------------------------------

class TestMakeAnchorPng:
    def test_produces_correct_png(self):
        from PIL import Image
        data = _make_anchor_png()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
        img = Image.open(BytesIO(data))
        assert img.size == (ANCHOR_SIZE, ANCHOR_SIZE)
        assert img.mode == "L"

    def test_centre_pixel_is_black_inner_dot(self):
        from PIL import Image
        img = Image.open(BytesIO(_make_anchor_png()))
        assert img.getpixel((ANCHOR_SIZE // 2, ANCHOR_SIZE // 2)) == 0

    def test_white_ring_pixel(self):
        from PIL import Image
        img = Image.open(BytesIO(_make_anchor_png()))
        # (ANCHOR_OUTER_RING+1, ANCHOR_SIZE//2) is inside the white ring
        # but outside the inner black dot
        assert img.getpixel((ANCHOR_OUTER_RING + 1, ANCHOR_SIZE // 2)) == 255

    def test_outer_ring_pixel_is_black(self):
        from PIL import Image
        img = Image.open(BytesIO(_make_anchor_png()))
        # (1, ANCHOR_SIZE//2) is inside the outer black disk but outside the white ring
        assert img.getpixel((1, ANCHOR_SIZE // 2)) == 0


class TestMakeAnchorJpeg:
    def test_produces_correct_jpeg(self):
        from PIL import Image
        data = _make_anchor_jpeg()
        assert data[:2] == b"\xff\xd8", "not a JPEG"
        img = Image.open(BytesIO(data))
        assert img.size == (ANCHOR_SIZE, ANCHOR_SIZE)


# ---------------------------------------------------------------------------
# _estimate_rows / _choose_column_layout
# ---------------------------------------------------------------------------

class TestEstimateRows:
    def test_capacity_scales_with_column_count(self):
        config = {"1": {"choices": ["A", "B", "C"]}}
        _, capacity = _estimate_rows(config, 3)
        assert capacity == ROWS_PER_COL * 3

    def test_wide_question_needs_more_than_one_row(self):
        config = {"1": {"choices": [str(i) for i in range(40)]}}
        total_rows, _ = _estimate_rows(config, 4)
        assert total_rows > 1


class TestChooseColumnLayout:
    def test_prefers_more_columns_when_it_fits(self):
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 6)}
        n_columns, total_rows, capacity = _choose_column_layout(config)
        assert n_columns == 4
        assert total_rows <= capacity

    def test_one_wide_question_no_longer_collapses_the_whole_layout(self):
        """A single wide question used to force _column_count(max_options)
        down to 1 column for the *entire* template. Column choice should now
        be based on the whole template's demand, so 29 tiny questions aren't
        squeezed into 1 column just because question 1 has 30 options."""
        config = {"1": {"choices": [str(i) for i in range(30)]}}
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(2, 31)})
        n_columns, total_rows, capacity = _choose_column_layout(config)
        assert n_columns == 4
        assert total_rows <= capacity

    def test_falls_back_to_closest_fit_when_nothing_fits(self):
        """30 questions of 20 options each don't fit at any column count.
        That's a genuine page-capacity limit, not a column-choice bug, so
        the closest candidate (1 column) should be reported, not just the
        max of 4."""
        config = {str(i): {"choices": [str(j) for j in range(20)]} for i in range(1, 31)}
        n_columns, total_rows, capacity = _choose_column_layout(config)
        assert total_rows > capacity
        assert n_columns == 1


# ---------------------------------------------------------------------------
# _compute_questions
# ---------------------------------------------------------------------------

class TestComputeQuestions:
    def test_single_question_structure(self):
        q = _compute_questions({"1": {"choices": ["A", "B", "C"]}})[0]
        assert q["id"] == "1"
        assert [b["label"] for b in q["bubbles"]] == ["A", "B", "C"]

    def test_bubble_spacing_and_y_alignment(self):
        q = _compute_questions({"1": {"choices": ["A", "B", "C", "D"]}})[0]
        for i in range(1, len(q["bubbles"])):
            assert q["bubbles"][i]["x"] - q["bubbles"][i - 1]["x"] == BUBBLE_STEP
        assert all(b["y"] == q["cy"] for b in q["bubbles"])

    def test_numeric_sort_order(self):
        config = {"10": {"choices": ["A", "B"]}, "2": {"choices": ["A", "B"]}, "1": {"choices": ["A", "B"]}}
        assert [q["id"] for q in _compute_questions(config)] == ["1", "2", "10"]

    def test_row_spacing_and_column_wrap(self):
        # No sections, and 26 questions won't keep together in one column
        # (27 rows including the would-be header > 25), so this falls
        # through to plain sequential placement: fill column 0, then wrap.
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 27)}
        questions = _compute_questions(config)
        # Consecutive rows within a column are spaced by ROW_HEIGHT
        assert questions[1]["cy"] - questions[0]["cy"] == ROW_HEIGHT
        # Column 0 holds exactly ROWS_PER_COL (25) questions before wrapping.
        assert questions[25]["cy"] < questions[24]["cy"]
        assert questions[25]["label_x"] > questions[0]["label_x"]

    def test_exactly_max_questions_succeeds(self):
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 201)}
        questions = _compute_questions(config)
        assert len(questions) == 200
        assert questions[99]["page"] == 0
        assert questions[100]["page"] == 1

    def test_overflow_raises_bad_request(self):
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 202)}
        with pytest.raises(BadRequestError) as exc:
            _compute_questions(config)
        assert exc.value.code == "layout_overflow"

    def test_wide_question_becomes_a_full_width_band(self):
        """40 options is well past the "wide" threshold, so it should span
        the full page width (minimising its own line count) instead of
        wrapping narrowly inside whatever column count the rest of the
        template uses."""
        wide_choices = [str(i) for i in range(40)]
        config = {
            "1": {"choices": wide_choices},
            "2": {"choices": ["A", "B", "C"]},
        }
        q1, q2 = _compute_questions(config)

        rows_used = sorted({b["y"] for b in q1["bubbles"]})
        assert len(rows_used) > 1  # still too many to fit on one line even at full width
        for i, y in enumerate(rows_used):
            assert y == q1["cy"] + i * ROW_HEIGHT

        # Uses far more horizontal space than a single normal grid column
        # would (the tiny Q2 alone would pick 4 columns, each ~268 units wide)
        assert max(b["x"] for b in q1["bubbles"]) > MARGIN_X + 268

        # Q2 starts a fresh grid segment right after Q1's band
        assert q2["cy"] == q1["cy"] + len(rows_used) * ROW_HEIGHT
        assert q2["label_x"] == MARGIN_X + LABEL_W // 2  # back at column 0

    def test_moderately_wide_question_spans_free_columns_to_avoid_wrapping(self):
        """8 options wrapping to 2 lines in a single grid column isn't
        reason enough to become a full-width band (see _is_wide) -- that
        threshold only decides whether a whole section breaks out of "keep
        together" placement. Whether one question spreads into an
        otherwise-empty neighboring column is judged separately, per
        question, so it still spreads here even though the section as a
        whole stayed confined to "keep together"."""
        config = {str(i): {"choices": [chr(65 + j) for j in range(8)]} for i in range(1, 4)}
        questions = _compute_questions(config)
        assert all(len({b["y"] for b in q["bubbles"]}) == 1 for q in questions)  # one line each
        # none of them are wide, so all three questions keep together in the
        # same column (stacked), rather than any one being pulled out
        assert len({q["label_x"] for q in questions}) == 1
        assert questions[0]["cy"] < questions[1]["cy"] < questions[2]["cy"]

    def test_content_after_a_full_width_band_rolls_to_a_new_page(self):
        """Regression test: a wide question's band syncs every column to the
        same height, including ones nothing had been placed in yet. What
        comes after it must keep advancing columns (and, once those are
        also full, pages) until it actually finds room, not just try once
        and silently overflow past the bottom of the page."""
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 25)}
        config["25"] = {"choices": [chr(65 + j) for j in range(26)]}
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(26, 30)})

        questions = _compute_questions(config)  # must not raise
        assert len(questions) == 29

        trailing = questions[-4:]  # questions 26-29, placed after the wide band
        assert all(q["page"] == 1 for q in trailing)  # rolled to a fresh page
        assert all(q["cy"] <= HEADER_H + ROWS_PER_COL * ROW_HEIGHT for q in trailing)

    def test_wide_question_mid_sequence_splits_grid_segments(self):
        """A wide question in the middle of the sequence should close out
        the grid segment before it and start a fresh one (from column 0)
        after it, rather than being wrapped in wherever it falls."""
        config = {
            "1": {"choices": ["A", "B", "C"]},
            "2": {"choices": [str(i) for i in range(40)]},
            "3": {"choices": ["A", "B", "C"]},
        }
        q1, q2, q3 = _compute_questions(config)
        assert not _is_wide(3)
        assert _is_wide(40)

        assert q1["label_x"] == q3["label_x"]  # both reused column 0
        rows_q1 = len({b["y"] for b in q1["bubbles"]})
        rows_q2 = len({b["y"] for b in q2["bubbles"]})
        assert q3["cy"] == q1["cy"] + (rows_q1 + rows_q2) * ROW_HEIGHT

    def test_single_question_taller_than_a_column_raises_overflow(self):
        """No column has enough vertical room for an 800-option question,
        regardless of how many columns are available."""
        config = {"1": {"choices": [str(i) for i in range(800)]}}
        with pytest.raises(BadRequestError) as exc:
            _compute_questions(config)
        assert exc.value.code == "layout_overflow"

    def test_section_order_and_page_headers_are_preserved(self):
        config = {
            str(i): {"choices": ["A", "B", "C", "D", "E"]}
            for i in range(1, 102)
        }
        sections = [
            {"id": "later", "name": "Later", "question_ids": ["101"]},
            {"id": "main", "name": "Main", "question_ids": [str(i) for i in range(1, 101)]},
        ]

        questions = _compute_questions(config, sections)

        assert questions[0]["id"] == "101"
        assert questions[0]["section_name"] == "Later"
        assert questions[0]["section_start"] is True
        assert questions[1]["section_name"] == "Main"
        assert questions[1]["section_start"] is True

        # Section headers reserve real vertical space, so fewer questions fit
        # on page 0 than a flat 100-question grid would allow. Whichever
        # question ends up first on page 1 must repeat the section header, so
        # a reader flipping pages still knows which section they're in.
        page_1_start = next(q for q in questions if q["page"] == 1)
        start_index = questions.index(page_1_start)
        assert start_index < 100
        assert page_1_start["section_start"] is True
        assert questions[start_index - 1]["page"] == 0

    def test_section_header_reserves_extra_row_height(self):
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 4)}
        sections = [
            {"id": "a", "name": "A", "question_ids": ["1"]},
            {"id": "b", "name": "B", "question_ids": ["2", "3"]},
        ]

        questions = _compute_questions(config, sections)

        # "1" starts section A (page-first, no cost of its own to measure).
        # "2" starts section B mid-column — that transition is pushed down by
        # HEADER_EXTRA_H on top of the usual ROW_HEIGHT step. "3" continues
        # section B and keeps the normal spacing.
        assert questions[1]["section_start"] is True
        assert questions[1]["cy"] - questions[0]["cy"] == ROW_HEIGHT + HEADER_EXTRA_H
        assert questions[2]["section_start"] is False
        assert questions[2]["cy"] - questions[1]["cy"] == ROW_HEIGHT

    def test_true_false_columns_use_a_narrow_width_not_the_wide_default(self):
        """true_false questions are always exactly 2 options — spacing
        their columns using the same width as a multi-choice column (sized
        for far more options) leaves a large, pointless gap between them."""
        config = {str(i): {"choices": ["T", "F"]} for i in range(1, 31)}
        sections = [{"id": "s", "name": "TF", "type": "true_false", "question_ids": [str(i) for i in range(1, 31)]}]

        questions = _compute_questions(config, sections)
        by_id = {q["id"]: q for q in questions}

        tf_col_width = LABEL_W + 2 * BUBBLE_STEP
        assert by_id["1"]["col_width"] == tf_col_width
        assert by_id["25"]["col_left"] == MARGIN_X + tf_col_width + COL_GAP

    def test_true_false_column_after_a_wide_column_does_not_overlap_it(self):
        """A true_false section that spills into a column right after a
        multiple_choice column must still be positioned past that column's
        actual (wider) width, not at the narrow position it would have
        preferred on its own — otherwise the two columns would overlap."""
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 25)}
        config.update({str(i): {"choices": ["T", "F"]} for i in range(25, 30)})
        sections = [
            {"id": "a", "name": "A", "type": "multiple_choice", "question_ids": [str(i) for i in range(1, 25)]},
            {"id": "b", "name": "B", "type": "true_false", "question_ids": [str(i) for i in range(25, 30)]},
        ]

        questions = _compute_questions(config, sections)
        by_id = {q["id"]: q for q in questions}

        wide_col_width = by_id["1"]["col_width"]
        assert by_id["25"]["col_left"] == MARGIN_X + wide_col_width + COL_GAP
        assert by_id["25"]["col_width"] == LABEL_W + 2 * BUBBLE_STEP  # still narrow for its own content

    def test_multiple_choice_section_will_not_reuse_a_narrow_locked_column(self):
        """A multiple_choice section must skip a column already locked
        narrow by an earlier true_false section, even when there's enough
        *row* capacity left in it to fit — reusing it would draw bubbles
        past that column's actual (narrower) right edge."""
        config = {str(i): {"choices": ["T", "F"]} for i in range(1, 4)}
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(4, 24)})
        sections = [
            {"id": "a", "name": "A", "type": "true_false", "question_ids": ["1", "2", "3"]},
            {"id": "b", "name": "B", "type": "multiple_choice", "question_ids": [str(i) for i in range(4, 24)]},
        ]

        questions = _compute_questions(config, sections)
        by_id = {q["id"]: q for q in questions}

        narrow_col_width = by_id["1"]["col_width"]
        assert by_id["4"]["col_left"] != by_id["1"]["col_left"]  # did not reuse the narrow column
        assert max(b["x"] for b in by_id["4"]["bubbles"]) < by_id["4"]["col_left"] + by_id["4"]["col_width"]

    def test_section_stacks_vertically_in_the_current_column_when_it_fits(self):
        """An all-normal section should keep together in whichever column
        is currently active, not spread across columns, as long as it fits
        there."""
        config = {str(i): {"choices": ["A", "B", "C"]} for i in range(1, 6)}
        sections = [{"id": "s", "name": "S", "question_ids": [str(i) for i in range(1, 6)]}]

        questions = _compute_questions(config, sections)

        assert len({q["label_x"] for q in questions}) == 1  # all in one column
        assert questions[0]["section_start"] is True
        assert all(not q["section_start"] for q in questions[1:])

    def test_section_moves_to_a_fresh_column_when_it_does_not_fit_in_place(self):
        """A small all-normal section that can't fit where the previous
        section left off, but would fit an empty column, should start over
        in a fresh column rather than splitting."""
        config = {str(i): {"choices": ["A", "B", "C"]} for i in range(1, 30)}
        sections = [
            # Section "a" fills column 0 almost completely (24 rows of 25).
            {"id": "a", "name": "A", "question_ids": [str(i) for i in range(1, 25)]},
            # Section "b" (5 rows incl. header) doesn't fit the 1 row left in
            # column 0, but easily fits a fresh column.
            {"id": "b", "name": "B", "question_ids": [str(i) for i in range(25, 30)]},
        ]

        questions = _compute_questions(config, sections)
        by_id = {q["id"]: q for q in questions}

        assert by_id["1"]["label_x"] != by_id["25"]["label_x"]  # different columns
        assert by_id["25"]["section_start"] is True
        assert all(not by_id[str(i)]["section_start"] for i in range(26, 30))

    def test_section_taller_than_a_column_splits_across_columns(self):
        """A section too tall to fit even an empty column falls through to
        ordinary per-question placement, splitting across columns like any
        other content, instead of raising or being confined to one column."""
        config = {str(i): {"choices": ["A", "B", "C"]} for i in range(1, 31)}
        sections = [{"id": "s", "name": "S", "question_ids": [str(i) for i in range(1, 31)]}]

        questions = _compute_questions(config, sections)  # must not raise
        assert len(questions) == 30
        assert len({q["label_x"] for q in questions}) > 1  # spans more than one column

    def test_section_uses_remaining_columns_before_rolling_to_a_new_page(self):
        """Regression test: a wide-question band leaves every column with a
        small residual height (not literally empty). A later section that
        then fully occupies one column used to leave keep-together unable
        to find a column that fit an upcoming section as a whole block —
        and it would roll straight to a new page rather than letting that
        section split across the *other* columns, which still had plenty
        of genuinely usable room left on the current page."""
        config = {"0": {"choices": [str(i) for i in range(26)]}}  # wide -> band
        config.update({str(i): {"choices": ["T", "F"]} for i in range(1, 24)})  # fills column 0
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(24, 48)})

        sections = [
            {"id": "a", "name": "A", "type": "multiple_choice", "question_ids": ["0"]},
            {"id": "b", "name": "B", "type": "true_false", "question_ids": [str(i) for i in range(1, 24)]},
            {"id": "c", "name": "C", "type": "multiple_choice", "question_ids": [str(i) for i in range(24, 48)]},
        ]

        questions = _compute_questions(config, sections)
        assert len(questions) == 48
        assert {q["page"] for q in questions} == {0}  # everything stayed on the first page

    def test_wide_questions_span_only_the_free_columns_next_to_other_content(self):
        """Regression test: a wide question used to always claim the full
        page width, waiting for every column (including ones with unrelated
        content already in them, like a narrow true_false column) to reach
        the same height first. That could roll content to a new page even
        though the columns actually free at that point had plenty of room
        to spread the wide question across, without needing the narrow
        column to catch up at all."""
        config = {str(i): {"choices": ["T", "F"]} for i in range(1, 21)}  # fills column 0
        config.update({
            str(i): {"choices": [chr(65 + j) for j in range(15)]} for i in range(21, 30)
        })
        sections = [
            {"id": "a", "name": "TF", "type": "true_false", "question_ids": [str(i) for i in range(1, 21)]},
            {"id": "b", "name": "MC", "type": "multiple_choice", "question_ids": [str(i) for i in range(21, 30)]},
        ]

        questions = _compute_questions(config, sections)
        assert len(questions) == 29
        assert {q["page"] for q in questions} == {0}  # never needed a second page

        wide_q = next(q for q in questions if q["id"] == "21")
        tf_q = next(q for q in questions if q["id"] == "1")
        assert wide_q["col_left"] >= tf_q["col_left"] + tf_q["col_width"]  # sits to the right, not overlapping

    def test_last_column_claims_slack_left_by_a_narrower_earlier_column(self):
        """Regression test: a question landing in the very last grid column
        has no further column to span into, even if one exists on paper --
        best_span's search never looks past n_columns. But a true_false
        column earlier on the page is narrower than the grid's per-column
        guess, so the true remaining page width at the last column is wider
        than that guess. The last column should claim that real slack
        rather than wrap just because the uniform guess wasn't enough."""
        config = {str(i): {"choices": ["T", "F"]} for i in range(1, 25)}  # exactly fills column 0
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(30, 55)})  # fills column 1
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(55, 80)})  # fills column 2
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E", "F"]} for i in range(80, 83)})  # lands in column 3

        sections = [
            {"id": "a", "type": "true_false", "question_ids": [str(i) for i in range(1, 25)]},
            {"id": "b", "type": "multiple_choice", "question_ids": [str(i) for i in range(30, 55)]},
            {"id": "c", "type": "multiple_choice", "question_ids": [str(i) for i in range(55, 80)]},
            {"id": "d", "type": "multiple_choice", "question_ids": [str(i) for i in range(80, 83)]},
        ]

        questions = _compute_questions(config, sections)
        q80 = next(q for q in questions if q["id"] == "80")
        assert q80["col_left"] + q80["col_width"] == TEMPLATE_W - MARGIN_X  # reaches the true page margin
        assert len({b["y"] for b in q80["bubbles"]}) == 1  # fits on one line using that slack

    def test_small_question_spreads_across_free_columns_instead_of_wrapping(self):
        """Regression test: a question confined to a single grid column's
        width could wrap to a second line even when the rest of the page
        was completely empty. A question that isn't part of a whole-section
        keep-together block (here, forced into per-question placement by a
        wide sibling) should use whatever free columns sit next to it to
        avoid wrapping, rather than wrapping just because one column's
        width alone wasn't quite enough."""
        config = {
            "1": {"choices": [chr(65 + j) for j in range(26)]},  # wide, skips keep-together
            "2": {"choices": [chr(65 + j) for j in range(10)]},
        }
        sections = [{"id": "s", "name": "S", "question_ids": ["1", "2"]}]

        questions = _compute_questions(config, sections)
        q2 = next(q for q in questions if q["id"] == "2")
        rows_used = len({b["y"] for b in q2["bubbles"]})
        assert rows_used == 1  # all 10 options fit on one line by spanning extra columns

    def test_kept_together_section_also_spreads_into_a_free_neighbor_column(self):
        """Regression test: a section small enough to be kept together in
        one column used to always place its questions at exactly that
        column's width, even when the very next column was completely free
        and would have let it avoid wrapping to a second line."""
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 51)}
        config.update({
            str(i): {"choices": [chr(65 + j) for j in range(7)]} for i in range(51, 56)
        })
        sections = [
            {"id": "a", "name": "A", "type": "multiple_choice", "question_ids": [str(i) for i in range(1, 26)]},
            {"id": "b", "name": "B", "type": "multiple_choice", "question_ids": [str(i) for i in range(26, 51)]},
            {"id": "c", "name": "C", "type": "multiple_choice", "question_ids": [str(i) for i in range(51, 56)]},
        ]

        questions = _compute_questions(config, sections)
        q51 = next(q for q in questions if q["id"] == "51")
        rows_used = len({b["y"] for b in q51["bubbles"]})
        assert rows_used == 1  # spread into the free column instead of wrapping

    def test_multi_column_span_followed_by_a_column_further_right_does_not_crash(self):
        """Regression test: a question that spans several columns releases
        their width lock for whatever comes next (so a differently-widthed
        section can still reclaim them). Placing something in a column to
        the right of a released one used to crash, because computing that
        column's x-position summed the released columns' widths, and
        "released" was stored as None rather than their actual on-page
        width."""
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 15)}
        config.update({str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(15, 29)})
        config.update({
            str(i): {"choices": ["A", "B", "C", "D", "E", "F"]} for i in range(29, 42)
        })
        sections = [
            {"id": "a", "name": "A", "type": "multiple_choice", "question_ids": [str(i) for i in range(1, 15)]},
            {"id": "b", "name": "B", "type": "multiple_choice", "question_ids": [str(i) for i in range(15, 29)]},
            {"id": "c", "name": "C", "type": "multiple_choice", "question_ids": [str(i) for i in range(29, 42)]},
        ]

        questions = _compute_questions(config, sections)  # must not raise
        assert len(questions) == 41

    def test_spanning_header_merges_adjacent_aligned_columns(self):
        """A section that flows into a second column right after the first
        (same page, same row, immediately adjacent) should draw one header
        spanning both columns, not repeat its name in each one."""
        config = {str(i): {"choices": ["A", "B", "C"]} for i in range(1, 31)}
        sections = [{"id": "s", "name": "S", "question_ids": [str(i) for i in range(1, 31)]}]

        questions = _compute_questions(config, sections)
        by_id = {q["id"]: q for q in questions}

        # Question 1 starts column 0's header; question 25 starts column 1's
        # (established by test_row_spacing_and_column_wrap's own numbers).
        assert by_id["1"]["draw_header"] is True
        assert by_id["25"]["section_start"] is True
        assert by_id["25"].get("draw_header") is False  # merged into "1"'s header
        assert by_id["1"]["header_span_width"] == by_id["1"]["col_width"] + COL_GAP + by_id["25"]["col_width"]

    def test_spanning_header_does_not_merge_across_a_page_break(self):
        """Columns that happen to align but are on different pages must
        keep their own separate headers — there's nothing for a single
        header to visually span between two different sheets of paper."""
        config = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 201)}
        sections = [{"id": "s", "name": "S", "question_ids": [str(i) for i in range(1, 201)]}]

        questions = _compute_questions(config, sections)
        headers = [q for q in questions if q.get("draw_header")]
        pages = {q["page"] for q in headers}
        assert len(pages) > 1  # spans multiple pages
        assert len(headers) == len(pages)  # exactly one drawn header per page


# ---------------------------------------------------------------------------
# _is_wide
# ---------------------------------------------------------------------------

class TestIsWide:
    @pytest.mark.parametrize("n_opts,expected", [
        (5,  False),
        (10, False),  # right at the boundary: 2 lines at 4 columns vs 1 at full width
        (11, True),   # 3 lines at 4 columns vs 1 at full width, past the 2x bar
        (26, True),
    ])
    def test_boundary(self, n_opts, expected):
        assert _is_wide(n_opts) == expected


# ---------------------------------------------------------------------------
# _t2p
# ---------------------------------------------------------------------------

class TestT2P:
    @pytest.mark.parametrize("tx,ty,ex,ey", [
        (0,          0,          OFFSET_X,             PAGE_H_PT - OFFSET_Y),
        (TEMPLATE_W, TEMPLATE_H, PAGE_W_PT - OFFSET_X,  OFFSET_Y),
        (TEMPLATE_W / 2, TEMPLATE_H / 2, PAGE_W_PT / 2, PAGE_H_PT / 2),
    ])
    def test_coordinate_conversion(self, tx, ty, ex, ey):
        x, y = _t2p(tx, ty)
        assert x == pytest.approx(ex)
        assert y == pytest.approx(ey)

    def test_uniform_scale_preserves_circles(self):
        """A square in template space must map to a square in PDF space —
        independent X/Y scale factors would distort it into a rectangle,
        which is exactly the bug this test guards against (anchors were
        being drawn as ellipses, hurting OMR anchor-matching confidence)."""
        x0, y0 = _t2p(0, 0)
        x1, y1 = _t2p(100, 100)
        assert abs(x1 - x0) == pytest.approx(abs(y1 - y0))


# ---------------------------------------------------------------------------
# _make_page_scan_template  /  SCAN_TEMPLATE constant
# ---------------------------------------------------------------------------

class TestPageScanTemplate:
    def test_anchor_structure(self):
        result = _make_page_scan_template([(150, 250), (300, 400), (500, 600)])
        assert len(result["anchors"]) == 3
        a = result["anchors"][0]
        assert a["center"] == {"x": 150, "y": 250}
        assert a["roi"] == _anchor_roi(150, 250)

    def test_scan_template_structure(self):
        assert SCAN_TEMPLATE["width"] == TEMPLATE_W
        assert SCAN_TEMPLATE["height"] == TEMPLATE_H
        assert len(SCAN_TEMPLATE["pages"]) == 2
        assert all(len(p["anchors"]) == 3 for p in SCAN_TEMPLATE["pages"])

    def test_corner_disambiguation(self):
        front_centers = {(a["center"]["x"], a["center"]["y"]) for a in SCAN_TEMPLATE["pages"][0]["anchors"]}
        back_centers  = {(a["center"]["x"], a["center"]["y"]) for a in SCAN_TEMPLATE["pages"][1]["anchors"]}
        # Front page is missing bottom-right; back page is missing bottom-left
        assert (TEMPLATE_W - ANCHOR_PAD, TEMPLATE_H - ANCHOR_PAD) not in front_centers
        assert (ANCHOR_PAD, TEMPLATE_H - ANCHOR_PAD) not in back_centers


# ---------------------------------------------------------------------------
# _render_pdf
# ---------------------------------------------------------------------------

class TestRenderPdf:
    def test_produces_two_page_pdf(self):
        result = _render_pdf(_questions(3), 4)
        assert result[:5] == b"%PDF-"
        assert result.count(b"/Page") >= 2

    def test_additional_answer_pages_are_rendered(self):
        questions = _questions(2)
        questions[1]["page"] = 1
        result = _render_pdf(questions, 4)
        assert result.count(b"/Page") >= 3

    def test_filled_answers_produce_valid_pdf_distinct_from_blank(self):
        blank = _render_pdf(_questions(3), 4)
        filled = _render_pdf(
            _questions(3),
            4,
            fill_answers={"1": ["B"], "2": ["A", "C"]},
            fill_version="A",
            fill_student_id="1234",
            fill_first_name="JOE",
            fill_last_name="BLOW",
        )
        assert filled[:5] == b"%PDF-"
        assert filled.count(b"/Page") >= 2
        assert filled != blank


class TestRenderExamPdf:
    def test_produces_two_page_pdf_with_header(self):
        result = _render_pdf(
            _questions(3),
            4,
            header=("Midterm 1", "COSC 499 · Aug 01, 2026"),
        )
        assert result[:5] == b"%PDF-"
        assert result.count(b"/Page") >= 2


# ---------------------------------------------------------------------------
# _compute_back_page_questions
# ---------------------------------------------------------------------------

class TestComputeBackPageQuestions:
    def test_section_counts_and_ids(self):
        all_qs = _compute_back_page_questions()
        assert len(all_qs) == N_LAST + N_FIRST + N_ID

        last  = [q for q in all_qs if q["id"].startswith("L")]
        first = [q for q in all_qs if q["id"].startswith("F")]
        ids   = [q for q in all_qs if q["id"].startswith("I")]

        assert len(last) == N_LAST and last[0]["id"] == "L1"  and last[-1]["id"]  == f"L{N_LAST}"
        assert len(first) == N_FIRST and first[0]["id"] == "F1" and first[-1]["id"] == f"F{N_FIRST}"
        assert len(ids) == N_ID   and ids[0]["id"] == "I1"   and ids[-1]["id"]   == f"I{N_ID}"

    def test_bubble_labels_per_section(self):
        all_qs = _compute_back_page_questions()
        last_labels = [b["label"] for b in next(q for q in all_qs if q["id"] == "L1")["bubbles"]]
        id_labels   = [b["label"] for b in next(q for q in all_qs if q["id"] == "I1")["bubbles"]]
        assert last_labels == LETTERS
        assert id_labels   == DIGITS

    def test_row_y_spacing_within_section(self):
        qs = [q for q in _compute_back_page_questions() if q["id"].startswith("L")]
        deltas = {qs[i]["bubbles"][0]["y"] - qs[i-1]["bubbles"][0]["y"] for i in range(1, len(qs))}
        assert deltas == {INFO_ROW_H}

    def test_sections_non_overlapping_in_y(self):
        all_qs = _compute_back_page_questions()
        max_last  = max(q["bubbles"][0]["y"] for q in all_qs if q["id"].startswith("L"))
        min_first = min(q["bubbles"][0]["y"] for q in all_qs if q["id"].startswith("F"))
        max_first = max(q["bubbles"][0]["y"] for q in all_qs if q["id"].startswith("F"))
        min_id    = min(q["bubbles"][0]["y"] for q in all_qs if q["id"].startswith("I"))
        assert max_last < min_first
        assert max_first < min_id


# ---------------------------------------------------------------------------
# _build_mark_template
# ---------------------------------------------------------------------------

class TestBuildMarkTemplate:
    def test_config_values(self):
        config = json.loads(_build_mark_template(_questions(1), 4))["config"]
        assert config == {"fillThreshold": 0.28, "bubbleInset": 0.75, "flagThreshold": 0.25, "searchRadius": 5}

    def test_front_page_structure(self):
        result = json.loads(_build_mark_template(_questions(3), 4))
        front = result["pages"][0]["questions"]
        assert len(front) == 4          # V1 + 3 questions
        assert front[0]["id"] == "V1"
        assert front[0]["type"] == "single"
        assert [q["id"] for q in front[1:]] == ["Q1", "Q2", "Q3"]

    @pytest.mark.parametrize("n_versions", [2, 4, 6])
    def test_version_bubble_count(self, n_versions):
        v1 = json.loads(_build_mark_template(_questions(1), n_versions))["pages"][0]["questions"][0]
        assert len(v1["options"]) == n_versions
        assert [o["label"] for o in v1["options"]] == LETTERS[:n_versions]

    def test_single_version_template_has_no_version_question(self):
        front = json.loads(_build_mark_template(_questions(3), 1))["pages"][0]["questions"]
        assert [q["id"] for q in front] == ["Q1", "Q2", "Q3"]

    def test_all_answer_questions_allow_multiple_selections(self):
        front = json.loads(_build_mark_template(_questions(3), 4))["pages"][0]["questions"]
        for q in front[1:]:  # skip V1
            assert q["type"] == "multi"

    def test_bubble_dimensions_and_coordinate_passthrough(self):
        qs_in = _questions(1)
        front = json.loads(_build_mark_template(qs_in, 4))["pages"][0]["questions"]
        for q in front:
            assert q["bubbleWidth"] == BUBBLE_D and q["bubbleHeight"] == BUBBLE_D
        q1 = next(q for q in front if q["id"] == "Q1")
        assert q1["options"][0] == {"label": "A", "x": qs_in[0]["bubbles"][0]["x"], "y": qs_in[0]["bubbles"][0]["y"]}

    def test_back_page_structure(self):
        back = json.loads(_build_mark_template(_questions(1), 4))["pages"][1]["questions"]
        assert len(back) == N_LAST + N_FIRST + N_ID
        assert all(q["type"] == "single" for q in back)

    def test_additional_answer_pages_match_question_pages(self):
        questions = _questions(2)
        questions[1]["page"] = 1
        pages = json.loads(_build_mark_template(questions, 4))["pages"]

        assert [question["id"] for question in pages[0]["questions"]] == ["V1", "Q1"]
        assert [question["id"] for question in pages[1]["questions"]] == ["Q2"]
        assert len(pages[2]["questions"]) == N_LAST + N_FIRST + N_ID

# ---------------------------------------------------------------------------
# _build_answer_key_json
# ---------------------------------------------------------------------------

class TestBuildAnswerKeyJson:
    def _make_template(self, question_config: dict) -> MagicMock:
        t = MagicMock()
        t.question_config = question_config
        return t

    def _make_answer_key(
        self,
        answer_key: dict,
        scoring_rules: dict | None = None,
        exam_version: str | None = "A",
    ) -> MagicMock:
        ak = MagicMock()
        ak.exam_id = uuid4()
        ak.exam_template_id = uuid4()
        ak.exam_version = exam_version
        ak.answer_key = answer_key
        ak.scoring_rules = scoring_rules
        return ak

    def test_output_structure_contains_required_fields(self):
        tmpl = self._make_template({"1": {"choices": ["A", "B", "C"]}})
        ak = self._make_answer_key({
            "1": {"grading_type": "single", "correct_choices": ["B"], "points": None, "partial_weights": None},
        })
        result = _build_answer_key_json(tmpl, ak)
        assert result["exam_id"] == str(ak.exam_id)
        assert result["exam_template_id"] == str(ak.exam_template_id)
        assert result["exam_version"] == "A"
        assert "generated_at" in result
        assert result["questions"]["1"]["choices"] == ["A", "B", "C"]
        assert result["questions"]["1"]["correct_choices"] == ["B"]
        assert result["questions"]["1"]["grading_type"] == "single"

    def test_per_question_points_override_used_when_set(self):
        tmpl = self._make_template({"1": {"choices": ["A", "B"]}})
        ak = self._make_answer_key(
            {"1": {"grading_type": "single", "correct_choices": ["A"], "points": 5.0, "partial_weights": None}},
            scoring_rules={"default_points_per_question": 1.0},
        )
        result = _build_answer_key_json(tmpl, ak)
        assert result["questions"]["1"]["points"] == 5.0
        assert result["total_points"] == 5.0

    def test_default_points_used_when_per_question_points_is_none(self):
        tmpl = self._make_template({"1": {"choices": ["A", "B"]}})
        ak = self._make_answer_key(
            {"1": {"grading_type": "single", "correct_choices": ["A"], "points": None, "partial_weights": None}},
            scoring_rules={"default_points_per_question": 3.0},
        )
        result = _build_answer_key_json(tmpl, ak)
        assert result["questions"]["1"]["points"] == 3.0
        assert result["default_points_per_question"] == 3.0

    def test_no_scoring_rules_defaults_to_one_point(self):
        tmpl = self._make_template({"1": {"choices": ["A", "B"]}})
        ak = self._make_answer_key(
            {"1": {"grading_type": "single", "correct_choices": ["A"], "points": None, "partial_weights": None}},
            scoring_rules=None,
        )
        result = _build_answer_key_json(tmpl, ak)
        assert result["default_points_per_question"] == 1.0

    def test_total_points_sums_all_questions(self):
        tmpl = self._make_template({
            "1": {"choices": ["A", "B"]},
            "2": {"choices": ["A", "B"]},
        })
        ak = self._make_answer_key(
            {
                "1": {"grading_type": "single", "correct_choices": ["A"], "points": 2.0, "partial_weights": None},
                "2": {"grading_type": "single", "correct_choices": ["B"], "points": 3.0, "partial_weights": None},
            },
        )
        result = _build_answer_key_json(tmpl, ak)
        assert result["total_points"] == pytest.approx(5.0)

    def test_none_version_passed_through(self):
        tmpl = self._make_template({"1": {"choices": ["A"]}})
        ak = self._make_answer_key(
            {"1": {"grading_type": "single", "correct_choices": ["A"], "points": None, "partial_weights": None}},
            exam_version=None,
        )
        result = _build_answer_key_json(tmpl, ak)
        assert result["exam_version"] is None


class TestBuildAnswerKeyCsv:
    def test_csv_uses_importable_columns_and_preserves_answer_values(self):
        tmpl = MagicMock(question_config={"1": {"choices": ["A", "B", "C"]}})
        ak = MagicMock(
            exam_id=uuid4(),
            exam_template_id=uuid4(),
            exam_version="A",
            answer_key={
                "1": {
                    "grading_type": "partial",
                    "correct_choices": ["A", "C"],
                    "points": 2.0,
                    "partial_weights": {"A": 0.4, "C": 0.6},
                },
            },
            scoring_rules={"default_points_per_question": 1.0},
        )

        result = _build_answer_key_csv(tmpl, ak)

        assert result.splitlines()[0].startswith("question,correct_choices,grading_type,points")
        assert '1,A|C,partial,2.0,"{""A"": 0.4, ""C"": 0.6}",A,1.0' in result


# ---------------------------------------------------------------------------
# generate_template_pdf
# ---------------------------------------------------------------------------

class TestGenerateTemplatePdf:
    @pytest.fixture
    def db(self):
        m = MagicMock()
        m.flush = AsyncMock()
        m.commit = AsyncMock()
        m.rollback = AsyncMock()
        return m

    @pytest.fixture
    def storage(self):
        return MagicMock()

    async def _call(self, db, storage, owner_id=None, template_id=None):
        return await generate_template_pdf(
            db, storage, template_id or uuid4(), owner_id or uuid4()
        )

    async def test_template_not_found(self, db, storage):
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(NotFoundError) as exc:
                await self._call(db, storage)
        assert exc.value.code == "template_not_found"

    async def test_wrong_user_raises_forbidden(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner)
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl):
            with pytest.raises(ForbiddenError) as exc:
                await self._call(db, storage, owner_id=uuid4(), template_id=tmpl.id)
        assert exc.value.code == "forbidden"

    async def test_layout_overflow_raises_bad_request(self, db, storage):
        owner = uuid4()
        overflow = {str(i): {"choices": ["A", "B", "C", "D", "E"]} for i in range(1, 202)}
        tmpl = _mock_template(owner, question_config=overflow)
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl):
            with pytest.raises(BadRequestError) as exc:
                await self._call(db, storage, owner_id=owner, template_id=tmpl.id)
        assert exc.value.code == "layout_overflow"

    async def test_happy_path_uploads_three_files(self, db, storage):
        owner = uuid4()
        tid = uuid4()
        tmpl = _mock_template(owner, template_id=tid)

        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl):
            result = await self._call(db, storage, owner_id=owner, template_id=tid)

        uploaded_keys = {c.args[1] for c in storage.upload_file.call_args_list}
        assert storage.upload_file.call_count == 3
        assert ANCHOR_PNG_KEY in uploaded_keys
        assert f"generated/{tid}/bubble_sheet.pdf" in uploaded_keys
        assert f"generated/{tid}/scan_template.json" in uploaded_keys
        assert f"generated/{tid}/mark_template.json" not in uploaded_keys

        assert result is tmpl
        assert result.generated_pdf_path == f"generated/{tid}/bubble_sheet.pdf"
        assert result.omr_template_id is None

        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    async def test_large_template_generates_matching_scan_pages(self, db, storage):
        owner = uuid4()
        tid = uuid4()
        question_config = {
            str(i): {"choices": ["A", "B", "C", "D", "E"]}
            for i in range(1, 102)
        }
        tmpl = _mock_template(owner, template_id=tid, question_config=question_config)

        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl):
            await self._call(db, storage, owner_id=owner, template_id=tid)

        scan_upload = next(
            call for call in storage.upload_file.call_args_list
            if call.args[1].endswith("scan_template.json")
        )
        assert len(json.loads(scan_upload.args[0])["pages"]) == 3

    async def test_db_error_triggers_rollback(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner)
        db.flush = AsyncMock(side_effect=RuntimeError("flush failed"))
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl):
            with pytest.raises(RuntimeError):
                await self._call(db, storage, owner_id=owner, template_id=tmpl.id)
        db.rollback.assert_called_once()
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# finalize_exam_template
# ---------------------------------------------------------------------------

class TestFinalizeExamTemplate:
    @pytest.fixture
    def db(self):
        m = MagicMock()
        m.flush = AsyncMock()
        m.commit = AsyncMock()
        m.rollback = AsyncMock()
        return m

    @pytest.fixture
    def storage(self):
        return MagicMock()

    async def _call(self, db, storage, owner_id=None, template_id=None):
        return await finalize_exam_template(
            db, storage, template_id or uuid4(), owner_id or uuid4()
        )

    async def test_template_not_found(self, db, storage):
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=None):
            with pytest.raises(NotFoundError) as exc:
                await self._call(db, storage)
        assert exc.value.code == "template_not_found"

    async def test_wrong_user_raises_forbidden(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner, generated=True)
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl):
            with pytest.raises(ForbiddenError) as exc:
                await self._call(db, storage, owner_id=uuid4(), template_id=tmpl.id)
        assert exc.value.code == "forbidden"

    async def test_missing_pdf_is_generated_before_registration(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner, generated=False)
        omr = _mock_omr()
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl), \
             patch("services.exam_generator.upload_preprocessing_template", new_callable=AsyncMock, return_value="pt-abc"), \
             patch("services.exam_generator.upload_marking_template", new_callable=AsyncMock, return_value="mt-xyz"), \
             patch("services.exam_generator.create_omr_template", new_callable=AsyncMock, return_value=omr):
            result = await self._call(db, storage, owner_id=owner, template_id=tmpl.id)

        assert result.generated_pdf_path == f"generated/{tmpl.id}/bubble_sheet.pdf"
        assert result.omr_template_id == omr.id
        uploaded_keys = {call.args[1] for call in storage.upload_file.call_args_list}
        assert f"generated/{tmpl.id}/bubble_sheet.pdf" in uploaded_keys
        assert f"generated/{tmpl.id}/scan_template.json" in uploaded_keys

    async def test_already_registered_template_is_unchanged(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner, generated=True)
        tmpl.omr_template_id = uuid4()

        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl):
            result = await self._call(db, storage, owner_id=owner, template_id=tmpl.id)

        assert result is tmpl
        storage.upload_file.assert_not_called()

    async def test_no_answer_keys_still_registers(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner, generated=True)
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl), \
             patch("services.exam_generator.upload_preprocessing_template", new_callable=AsyncMock, return_value="pt-abc"), \
             patch("services.exam_generator.upload_marking_template", new_callable=AsyncMock, return_value="mt-xyz"), \
             patch("services.exam_generator.create_omr_template", new_callable=AsyncMock, return_value=_mock_omr()):
            result = await self._call(db, storage, owner_id=owner, template_id=tmpl.id)
        assert result.omr_template_id is not None

    async def test_happy_path_uploads_mark_template_and_sets_omr_id(self, db, storage):
        owner = uuid4()
        tid = uuid4()
        tmpl = _mock_template(owner, template_id=tid, generated=True)
        omr = _mock_omr()
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl), \
             patch("services.exam_generator.upload_preprocessing_template", new_callable=AsyncMock, return_value="pt-abc") as mock_upload_pt, \
             patch("services.exam_generator.upload_marking_template", new_callable=AsyncMock, return_value="mt-xyz") as mock_upload_mt, \
             patch("services.exam_generator.create_omr_template", new_callable=AsyncMock, return_value=omr) as mock_create_omr:
            result = await self._call(db, storage, owner_id=owner, template_id=tid)

        uploaded_keys = {c.args[1] for c in storage.upload_file.call_args_list}
        assert storage.upload_file.call_count == 1
        assert f"generated/{tid}/mark_template.json" in uploaded_keys

        mock_upload_pt.assert_awaited_once()
        mock_upload_mt.assert_awaited_once()

        assert result.omr_template_id == omr.id
        assert mock_create_omr.call_args.kwargs["scan_template_path"] == f"generated/{tid}/scan_template.json"
        assert mock_create_omr.call_args.kwargs["mark_template_path"] == f"generated/{tid}/mark_template.json"
        assert mock_create_omr.call_args.kwargs["preprocess_template_id"] == "pt-abc"
        assert mock_create_omr.call_args.kwargs["mark_template_id"] == "mt-xyz"
        assert mock_create_omr.call_args.kwargs["page_count"] == 2
        db.commit.assert_called_once()

    async def test_large_template_registers_every_generated_page(self, db, storage):
        owner = uuid4()
        tid = uuid4()
        question_config = {
            str(i): {"choices": ["A", "B", "C", "D", "E"]}
            for i in range(1, 102)
        }
        tmpl = _mock_template(
            owner,
            template_id=tid,
            question_config=question_config,
            generated=True,
        )
        omr = _mock_omr()

        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl), \
             patch("services.exam_generator.upload_preprocessing_template", new_callable=AsyncMock, return_value="pt-abc") as mock_upload_pt, \
             patch("services.exam_generator.upload_marking_template", new_callable=AsyncMock, return_value="mt-xyz"), \
             patch("services.exam_generator.create_omr_template", new_callable=AsyncMock, return_value=omr) as mock_create_omr:
            await self._call(db, storage, owner_id=owner, template_id=tid)

        preprocessing = mock_upload_pt.await_args.args[0]
        assert len(preprocessing.pages) == 3
        assert mock_create_omr.call_args.kwargs["page_count"] == 3

    async def test_omr_upload_failure_raises_service_unavailable(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner, generated=True)

        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl), \
             patch(
                 "services.exam_generator.upload_preprocessing_template",
                 new_callable=AsyncMock,
                 side_effect=OMRClientError("OMR service returned 500"),
             ), \
             patch("services.exam_generator.create_omr_template", new_callable=AsyncMock) as mock_create_omr:
            with pytest.raises(ServiceUnavailableError) as exc:
                await self._call(db, storage, owner_id=owner, template_id=tmpl.id)

        assert exc.value.code == "omr_template_upload_failed"
        mock_create_omr.assert_not_called()
        db.commit.assert_not_called()

    async def test_db_error_triggers_rollback(self, db, storage):
        owner = uuid4()
        tmpl = _mock_template(owner, generated=True)
        with patch("services.exam_generator.get_exam_template_by_id", new_callable=AsyncMock, return_value=tmpl), \
             patch("services.exam_generator.upload_preprocessing_template", new_callable=AsyncMock, return_value="pt-abc"), \
             patch("services.exam_generator.upload_marking_template", new_callable=AsyncMock, return_value="mt-xyz"), \
             patch("services.exam_generator.create_omr_template", new_callable=AsyncMock, side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError):
                await self._call(db, storage, owner_id=owner, template_id=tmpl.id)
        db.rollback.assert_called_once()
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# StorageRepository.get_presigned_url
# ---------------------------------------------------------------------------

class TestStorageGetPresignedUrl:
    def _repo(self):
        from repositories.storage import StorageRepository
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://storage/signed"
        return StorageRepository(s3_client=mock_s3, bucket="test-bucket"), mock_s3

    def test_calls_s3_with_correct_args(self):
        repo, mock_s3 = self._repo()
        url = repo.get_presigned_url("some/file.pdf")
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "some/file.pdf"},
            ExpiresIn=3600,
        )
        assert url == "https://storage/signed"

    def test_custom_expiry_forwarded(self):
        repo, mock_s3 = self._repo()
        repo.get_presigned_url("file.pdf", expires_in=7200)
        assert mock_s3.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 7200
