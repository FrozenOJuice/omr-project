"""Generates the committed manual-upload test-scan fixtures for the
consolidated scale course ("COSC 499 - Capstone Project", see seed.py).

seed.py seeds ~200 scale-testing students but deliberately gives the
first SCALE_SHOWCASE_COUNT of them (identified by stable student number) no
fabricated scan -- this script renders a real, filled, scanner-degraded PDF
for each of those students instead (one per exam template: the custom
10-question exam and the UBC blueprint exam), across randomized DPI/mark-
darkness/page-order conditions, so a tester has real fixtures to manually
upload against a real roster. Name/ID mark darkness is randomized
independently of (and with a higher floor than) answer-mark darkness -- see
the comment above _MIN_IDENTITY_DARKNESS for why coupling them produced
fixtures with missing name letters rather than just lower confidence.

Unlike generate_ubc_test_scans.py, this script needs a live DB connection:
the fixtures must be filled against the real, persisted Exam/ExamTemplate
rows the consolidated seed creates (for the correct bubble layout, and so the custom
exam's sheet header shows the real exam name/course/date instead of being
blank -- see build_exam_header in services/exam_generator.py), not a
hand-rolled stand-in. It therefore:

  1. Must be run AFTER `make dev-seed` has populated the DB --
     fails clearly (not silently) if the course/exams aren't found yet.
  2. Must run inside the `backend` container, same as seed.py itself and
     generate_ubc_test_scans.py's UBC half: the UBC fill path reads
     UBC_TEMPLATE_DIR (app/backend/data/ubc_template), which only exists via
     the ./omr/data/templates/ubc:/app/data/ubc_template:ro bind mount in
     app/docker-compose.yml, not on the host filesystem.

Output is committed to the repo (app/backend/data/sample_scans/) and is a
one-time generation, not something dev-seed re-runs on every seed --
only re-run this script by hand if the scale course's seeded identity changes
(e.g. SCALE_EXAM_TEMPLATES or build_scale_course_def() in seed.py are
edited), since the fixtures would otherwise silently go stale relative to
the DB. RANDOM_SEED keeps output byte-reproducible across re-runs, so an
unrelated re-run doesn't churn every file's git diff.

Usage (inside the backend container, after `make dev-seed`):
    python scripts/generate_extended_test_scans.py --output-dir ./data/sample_scans
"""
import argparse
import asyncio
import os
import random
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import fitz  # noqa: E402
from sqlalchemy import select  # noqa: E402

import db.base  # noqa: E402  (registers the full SQLAlchemy model graph)
from db.session import AsyncSessionLocal  # noqa: E402
from models.course import Course  # noqa: E402
from models.exam import Exam  # noqa: E402
from models.exam_template import ExamTemplate  # noqa: E402
from seed import SCALE_SHOWCASE_COUNT, SCALE_USERS  # noqa: E402
from services.scan_simulation import render_scanner_like_pdf  # noqa: E402
from services.exam_generator import (  # noqa: E402
    build_exam_header,
    render_filled_scan_pdf,
    render_filled_ubc_scan_pdf,
)

RANDOM_SEED = 42
COURSE_NAME = "COSC 499 - Capstone Project"
CUSTOM_EXAM_NAME = "Capstone Midterm"
UBC_EXAM_NAME = "Capstone Final Exam"

# DPI is expressed as a render zoom (dpi = zoom * 72, see RENDER_ZOOM /
# render_scanner_like_pdf's zoom param in scan_simulation.py). The range
# spans below/above the empirically-validated 150-300 DPI clean range and
# the soft-warn band at ~145-324 DPI relative to 216-DPI templates (see
# feature/431-support-variable-dpi-scans) -- some draws intentionally land
# in/near the warning zone. That's deliberate coverage, not a bug.
_MIN_DPI, _MAX_DPI = 140.0, 320.0
_MIN_DARKNESS, _MAX_DARKNESS = 0.2, 1.0
# Name/ID fields get their own, higher darkness floor, independent of the
# answer-mark darkness above. A UBC name row has 26 competing letter
# options vs. a question's 5 (or the ID row's 10 digits) -- the OMR
# service's confidence formula (app/omr/internal/marker/marker.go) is a
# margin normalized by how many options are competing, so a 26-option row
# has far less headroom to lose before individual letters drop out
# entirely. Coupling identity darkness to the same low draws as the answer
# darkness produced fixtures with genuinely missing name letters, not just
# lower (but still correct) confidence -- see the investigation this
# comment documents in the branch history. Real students have no reason to
# bubble their name markedly fainter than their answers, so this isn't
# losing realism, just not conflating two different things being tested.
_MIN_IDENTITY_DARKNESS, _MAX_IDENTITY_DARKNESS = 0.7, 1.0
# A minority condition. It does NOT reliably trigger FAILURE_PAGE_OUT_OF_ORDER
# for a 2-page exam -- ScanExamMats (app/omr/internal/scanner/mats.go)
# already brute-force tries every page-order permutation before giving up,
# so a swapped 2-page PDF is usually just transparently self-corrected.
# Kept anyway as regression coverage for that auto-correction path, not as
# an expected-failure case.
_SWAP_PROBABILITY = 0.175

_ANSWER_CYCLE = ["A", "B", "C", "D", "E"]


def _draw_condition(rng: random.Random, *, baseline: bool) -> dict:
    """baseline=True (used once, for the first showcase student) is a fixed
    known-good control: 216 DPI, full darkness, normal page order -- a
    sanity-check file a tester can upload first to confirm the pipeline
    works before trying the randomized ones.

    Takes an explicit Random instance -- the SAME one generate() also passes
    into render_scanner_like_pdf's rng param -- rather than the bare
    `random` module. A prior version of this script called
    `random.seed(RANDOM_SEED)` (module-level) and expected that to also
    determinize render_scanner_like_pdf's degradation noise, since it read
    from that same global module -- but re-running still produced different
    output every time. This process talks to a real DB over asyncpg in the
    same event loop, and something in that stack draws from the shared
    global `random` state too, consuming an unpredictable number of values
    between this function's own calls. An explicit, isolated Random instance
    that nothing else can touch is the only way to actually guarantee
    reproducible output here.
    """
    if baseline:
        return {"dpi": 216.0, "darkness": 1.0, "identity_darkness": 1.0, "swap_pages": False}
    return {
        "dpi": rng.uniform(_MIN_DPI, _MAX_DPI),
        "darkness": rng.uniform(_MIN_DARKNESS, _MAX_DARKNESS),
        "identity_darkness": rng.uniform(_MIN_IDENTITY_DARKNESS, _MAX_IDENTITY_DARKNESS),
        "swap_pages": rng.random() < _SWAP_PROBABILITY,
    }


def _custom_answers(template: ExamTemplate, offset: int) -> dict[str, list[str]]:
    return {
        qid: [_ANSWER_CYCLE[(int(qid) - 1 + offset) % len(cfg["choices"])]]
        for qid, cfg in template.question_config.items()
    }


def _ubc_answers(offset: int) -> dict[str, list[str]]:
    # render_filled_ubc_scan_pdf keys answers by mark.json's own field IDs
    # ("Q1".."Q100"), a different shape from question_config's "1".."100".
    return {f"Q{i}": [_ANSWER_CYCLE[(i - 1 + offset) % len(_ANSWER_CYCLE)]] for i in range(1, 101)}


def _swap_pdf_pages(pdf_bytes: bytes) -> bytes:
    """Reorders a 2-page PDF back-to-front, for the "back page fed into the
    scanner first" condition. Applied after render_scanner_like_pdf's
    degradation pass, not before, so the swap itself doesn't interact with
    the blur/skew/JPEG-noise simulation."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        doc.move_page(1, 0)
        return doc.tobytes(no_new_id=True)  # see scan_simulation.py's render_scanner_like_pdf comment
    finally:
        doc.close()


async def generate(output_dir: str) -> None:
    rng = random.Random(RANDOM_SEED)
    os.makedirs(output_dir, exist_ok=True)

    async with AsyncSessionLocal() as session:
        course = (
            await session.execute(
                select(Course)
                .join(Exam, Exam.course_id == Course.id)
                .where(Course.name == COURSE_NAME, Exam.name == CUSTOM_EXAM_NAME)
            )
        ).scalar_one_or_none()
        if not course:
            sys.exit(f"ERROR: course {COURSE_NAME!r} not found -- run `make dev-seed` first.")

        custom_exam = (
            await session.execute(
                select(Exam).where(Exam.course_id == course.id, Exam.name == CUSTOM_EXAM_NAME)
            )
        ).scalar_one_or_none()
        ubc_exam = (
            await session.execute(
                select(Exam).where(Exam.course_id == course.id, Exam.name == UBC_EXAM_NAME)
            )
        ).scalar_one_or_none()
        if not custom_exam or not ubc_exam:
            sys.exit(f"ERROR: expected exams not found in {COURSE_NAME!r} -- run `make dev-seed` first.")

        custom_template = await session.get(ExamTemplate, custom_exam.exam_template_id)
        ubc_template = await session.get(ExamTemplate, ubc_exam.exam_template_id)
        if not custom_template or not ubc_template:
            sys.exit("ERROR: exam templates not registered -- run `make dev-seed` first.")

        # UBC blueprint sheets are pre-printed and have no header mechanism
        # at all (generate_exam_pdf rejects them outright for this reason) --
        # only the custom exam's fills get a header.
        header = build_exam_header(custom_exam, course)

        showcase = SCALE_USERS[:SCALE_SHOWCASE_COUNT]
        assert len(showcase) == SCALE_SHOWCASE_COUNT, (
            f"expected {SCALE_SHOWCASE_COUNT} showcase students, found {len(showcase)}"
        )

        for idx, student in enumerate(showcase):
            condition = _draw_condition(rng, baseline=(idx == 0))
            zoom = condition["dpi"] / 72
            slug = f"showcase{idx:02d}_{student['last_name'].lower()}"
            tag = f"dpi{round(condition['dpi'])}_d{condition['darkness']:.2f}"
            if condition["swap_pages"]:
                tag += "_swapped"

            custom_pdf = render_filled_scan_pdf(
                custom_template,
                version=["A", "B"][idx % 2],
                student_id=student["student_number"],
                first_name=student["first_name"],
                last_name=student["last_name"],
                answers=_custom_answers(custom_template, offset=idx),
                darkness=condition["darkness"],
                identity_darkness=condition["identity_darkness"],
                header=header,
            )
            custom_pdf = render_scanner_like_pdf(custom_pdf, zoom=zoom, rng=rng)
            if condition["swap_pages"]:
                custom_pdf = _swap_pdf_pages(custom_pdf)

            ubc_pdf = render_filled_ubc_scan_pdf(
                answers=_ubc_answers(offset=idx),
                student_id=student["student_number"],
                first_name=student["first_name"],
                last_name=student["last_name"],
                darkness=condition["darkness"],
                identity_darkness=condition["identity_darkness"],
            )
            ubc_pdf = render_scanner_like_pdf(ubc_pdf, zoom=zoom, rng=rng)
            if condition["swap_pages"]:
                ubc_pdf = _swap_pdf_pages(ubc_pdf)

            custom_path = os.path.join(output_dir, f"custom_{slug}_{tag}.pdf")
            ubc_path = os.path.join(output_dir, f"ubc_{slug}_{tag}.pdf")
            with open(custom_path, "wb") as f:
                f.write(custom_pdf)
            with open(ubc_path, "wb") as f:
                f.write(ubc_pdf)
            print(f"wrote {custom_path} ({len(custom_pdf)} bytes)")
            print(f"wrote {ubc_path} ({len(ubc_pdf)} bytes)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate committed manual-upload test-scan fixtures for the scale seed course."
    )
    parser.add_argument("--output-dir", default="./data/sample_scans", help="Directory to write generated PDFs to.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(generate(args.output_dir))


if __name__ == "__main__":
    main()
