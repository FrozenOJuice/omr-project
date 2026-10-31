"""Verify prepared screenshots and synthetic fixture identities offline.

Requires the same Pillow/pypdf/reportlab tooling as prepare_assets.py.
Optional --legacy-ref checks for former documentation IDs without printing them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from PIL import Image
from pypdf import PdfReader

from check_repository import ROOT, source_files
from prepare_assets import IDENTITY, OMR, SCREENSHOTS, digit_reading


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-ref", help="Private historical ref containing the original charter")
    args = parser.parse_args()
    legacy_ids: set[str] = set()
    if args.legacy_ref:
        text = subprocess.check_output(
            ["git", "show", f"{args.legacy_ref}:docs/charter/charter.md"], cwd=ROOT,
        ).decode()
        legacy_ids = set(re.findall(r"\b\d{8}\b", text))
        assert legacy_ids, "Historical charter must contain identifiers to check"

    report = PdfReader(ROOT / "docs/final/OMR System Final Project Report.pdf")
    for page, index, filename in SCREENSHOTS:
        expected = report.pages[page - 1].images[index].image.convert("RGB")
        actual = Image.open(ROOT / "docs/portfolio/screenshots" / filename).convert("RGB")
        assert actual.size == expected.size and actual.tobytes() == expected.tobytes(), filename

    images = list((OMR / "internal/httpserver/handler/testdata/pages").glob("*page1.png"))
    images += list((OMR / "internal/scanner/testdata/multipage").glob("*page1.png"))
    assert len(images) == 5
    for path in images:
        assert digit_reading(Image.open(path))[0] == IDENTITY["I"], path.relative_to(ROOT)

    identities_in_pdfs = 0
    for path in source_files():
        if path.suffix != ".pdf":
            try:
                text = path.read_text()
            except (UnicodeError, OSError):
                continue
            assert not any(value in text for value in legacy_ids), f"Legacy ID remains in {path.relative_to(ROOT)}"
            continue
        reader = PdfReader(path)
        for page in reader.pages:
            assert not any(value in (page.extract_text() or "") for value in legacy_ids), path.relative_to(ROOT)
            if not path.is_relative_to(OMR):
                continue
            for embedded in page.images:
                image = embedded.image
                if image.size != (1680, 2184):
                    continue
                for rotation in (0, 180):
                    decoded, contrast = digit_reading(image.rotate(rotation))
                    assert not (decoded in legacy_ids and contrast > 20), f"Legacy identity in {path.relative_to(ROOT)}"
                    if decoded == IDENTITY["I"] and contrast > 20:
                        identities_in_pdfs += 1
                        break
    assert identities_in_pdfs == 11, f"Expected 11 synthetic identity images in PDFs, found {identities_in_pdfs}"

    expected = json.loads((OMR / "internal/httpserver/handler/testdata/answers/exam0.json").read_text())
    for scan in expected["scans"]:
        for prefix, value in IDENTITY.items():
            fields = sorted((m for m in scan["marks"] if m["questionId"].startswith(prefix)),
                            key=lambda m: int(m["questionId"][1:]))
            actual = "".join("".join(mark["selected"]) for mark in fields)
            assert actual == value, f"Expected-results identity field {prefix}"
    for name, count in (("sample.pdf", 5), ("sample_large.pdf", 88)):
        reader = PdfReader(OMR / "internal/pdf/testdata" / name)
        assert len(reader.pages) == count
        assert all("OMR rendering test document" in (page.extract_text() or "") for page in reader.pages)
    print("Verified 6 original screenshots, 5 synthetic identity PNGs, 11 PDF identity images,")
    print("matching expected identity fields, and synthetic 5-/88-page rendering fixtures.")
    if legacy_ids:
        print("Former charter IDs absent from current text, PDF text, and checked OMR identity images.")
    print("No source identity values were printed and no application service was accessed.")


if __name__ == "__main__":
    main()
