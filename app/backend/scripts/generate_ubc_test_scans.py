"""Generates synthetic filled UBC bubble-sheet PDFs across a range of fill
darkness levels, for testing OMR marking sensitivity without needing real
handmade scans every time.

Requested render DPI is not baked into these PDFs -- it's a parameter of the
OMR service's /scan/pdf upload (see the `dpi` field on that endpoint, or
scan_processing.OMR_UPLOAD_DPI / a template's native_dpi). Vary that
separately at upload time; the same generated PDF here can be uploaded at
any DPI to test how the pipeline handles that resolution.

Usage:
    python scripts/generate_ubc_test_scans.py --output-dir ./test_scans
"""
import argparse
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

from services.exam_generator import render_filled_ubc_scan_pdf

DEFAULT_DARKNESS_LEVELS = [1.0, 0.7, 0.5, 0.35, 0.25]


def generate(output_dir: str, darkness_levels: list[float], student_id: str, first_name: str, last_name: str, answer: str) -> None:
    answers = {f"Q{i}": [answer] for i in range(1, 101)}
    os.makedirs(output_dir, exist_ok=True)
    for darkness in darkness_levels:
        pdf_bytes = render_filled_ubc_scan_pdf(
            answers=answers,
            student_id=student_id,
            first_name=first_name,
            last_name=last_name,
            darkness=darkness,
        )
        path = os.path.join(output_dir, f"ubc_{first_name.lower()}_{last_name.lower()}_d{darkness:g}.pdf")
        with open(path, "wb") as f:
            f.write(pdf_bytes)
        print(f"wrote {path} ({len(pdf_bytes)} bytes)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic filled UBC bubble-sheet PDFs across a range of fill darkness levels."
    )
    parser.add_argument("--output-dir", default="./test_scans", help="Directory to write generated PDFs to.")
    parser.add_argument(
        "--darkness", type=float, nargs="+", default=DEFAULT_DARKNESS_LEVELS,
        help="Fill darkness levels to generate, each 0.0 (faint) to 1.0 (solid).",
    )
    parser.add_argument("--student-id", default="12345678")
    parser.add_argument("--first-name", default="KADEN")
    parser.add_argument("--last-name", default="HARRIS")
    parser.add_argument("--answer", default="A", help="Answer letter to fill for every multiple-choice question.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate(args.output_dir, args.darkness, args.student_id, args.first_name, args.last_name, args.answer)


if __name__ == "__main__":
    main()
