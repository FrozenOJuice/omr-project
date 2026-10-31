"""Prepare portfolio assets and synthetic test documents without running the app.

Requires Pillow, pypdf, and reportlab. Run from any directory with Python 3.12+.
The screenshots are extracted unchanged from the team's existing final report.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OMR = ROOT / "app/omr"
IDENTITY = {"L": "EXAMPLE", "F": "ALEX", "I": "90009999"}
SCREENSHOTS = (
    (41, 1, "template-editor.png"),
    (42, 0, "answer-key-editor.png"),
    (42, 1, "scan-upload.png"),
    (42, 2, "exam-review.png"),
    (43, 0, "grade-release.png"),
    (44, 0, "canvas-course-import.png"),
)


def screenshots() -> None:
    report = PdfReader(ROOT / "docs/final/OMR System Final Project Report.pdf")
    destination = ROOT / "docs/portfolio/screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    for page, index, filename in SCREENSHOTS:
        image = report.pages[page - 1].images[index].image
        image.save(destination / filename)
        print(f"Extracted {filename} from report page {page}")


def synthetic_pdf(path: Path, pages: int) -> None:
    """Keep renderer-test page counts, with original text and vector graphics."""
    document = canvas.Canvas(str(path), pagesize=(612, 792), invariant=1)
    document.setTitle("OMR synthetic rendering fixture")
    document.setAuthor("OMR System contributors")
    document.setSubject("Original test data; no student records or third-party prose")
    for page in range(1, pages + 1):
        document.setFont("Helvetica-Bold", 22)
        document.drawString(48, 734, "OMR rendering test document")
        document.setFont("Helvetica", 12)
        document.drawString(48, 706, f"Synthetic page {page} of {pages}")
        for row in range(16):
            y = 666 - row * 32
            document.setFillColorRGB(0.1, 0.2, 0.3)
            document.drawString(48, y, f"Page {page:02d}, row {row + 1:02d}: deterministic rendering sample.")
            document.setFillColorRGB((page % 7) / 8, (row % 5) / 6, 0.4)
            document.rect(48, y - 13, 24 + ((page * 17 + row * 13) % 450), 7, fill=1, stroke=0)
        document.setFillColorRGB(0, 0, 0)
        document.drawString(48, 66, "Created for testing by the OMR System contributors.")
        document.showPage()
    document.save()
    assert len(PdfReader(path).pages) == pages


def digit_reading(image: Image.Image) -> tuple[str, float]:
    """Read known fixture geometry only; never print source identity values."""
    gray = image.convert("L")
    digits, contrasts = [], []
    for row in range(8):
        values = []
        for column in range(10):
            x, y = round(199 + 53.8 * column), round(1624 + 46.1 * row)
            values.append(ImageStat.Stat(gray.crop((x - 5, y - 5, x + 6, y + 6))).mean[0])
        order = sorted(range(10), key=values.__getitem__)
        digits.append(str(order[0]))
        contrasts.append(values[order[1]] - values[order[0]])
    return "".join(digits), min(contrasts)


def synthetic_identity(image: Image.Image) -> Image.Image:
    """Regenerate the identity bubble fields; preserve anchors and answer marks."""
    result = image.convert("RGB").copy()
    draw = ImageDraw.Draw(result)
    # Clear each whole field so no old glyph edges survive a slightly different
    # source scan's row spacing. Headers, answer marks, and anchors stay intact.
    for rectangle in ((170, 228, 1575, 945), (170, 1036, 1575, 1500), (170, 1602, 710, 1970)):
        draw.rectangle(rectangle, fill="white")
    # Pillow's bundled font avoids host-specific font dependencies.
    font = ImageFont.load_default(size=16)
    groups = (("L", 248, 48.0, 15, 26), ("F", 1056, 46.2, 10, 26), ("I", 1624, 46.1, 8, 10))
    for field, start_y, step_y, rows, columns in groups:
        for row in range(rows):
            y = round(start_y + step_y * row)
            target = IDENTITY[field][row] if row < len(IDENTITY[field]) else None
            for column in range(columns):
                x = round(199 + 53.8 * column)
                label = str(column) if field == "I" else chr(65 + column)
                # Erase all old fills and glyphs, then draw an original bubble.
                draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill="white")
                draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill=(90, 90, 90) if label == target else "white", outline="black", width=2)
                draw.text((x, y), label, fill="black", font=font, anchor="mm")
    decoded, contrast = digit_reading(result)
    assert decoded == IDENTITY["I"] and contrast > 30, "Synthetic ID must decode unambiguously"
    return result


def sanitize_fixtures() -> None:
    handler = OMR / "internal/httpserver/handler/testdata"
    source_path = handler / "pages/exam0page1.png"
    if not source_path.exists():
        source_path = source_path.with_suffix(".jpeg")
    source = Image.open(source_path).convert("RGB")
    previous_id, contrast = digit_reading(source)
    assert contrast > 20, "Unexpected identity geometry; refusing to rewrite fixtures"
    replacement = synthetic_identity(source)
    for folder in (handler / "pages", OMR / "internal/scanner/testdata/multipage"):
        for path in sorted(folder.glob("exam*page1.*")):
            destination = path.with_suffix(".png")
            # Keep anchor pixels lossless: JPEG recompression changes matching.
            replacement.save(destination)
            if path != destination:
                path.unlink()
            assert digit_reading(Image.open(destination))[0] == IDENTITY["I"]
            print(f"Synthetic identity: {destination.relative_to(ROOT)}")

    pdfs = sorted((handler / "batches").glob("*.pdf")) + sorted((OMR / "internal/pdf/testdata/samples").glob("*.pdf"))
    for path in pdfs:
        writer = PdfWriter(clone_from=path)
        if writer.metadata and writer.metadata.get("/OMRFixtureVersion") == "synthetic-identity-v2":
            writer.close()
            continue
        updated = 0
        for page in writer.pages:
            for embedded in page.images:
                image = embedded.image.convert("RGB")
                if image.size != source.size:
                    continue
                for rotation in (0, 180):
                    upright = image.rotate(rotation)
                    decoded, contrast = digit_reading(upright)
                    if decoded in (previous_id, IDENTITY["I"]) and contrast > 20:
                        embedded.replace(synthetic_identity(upright).rotate(rotation), quality=100, subsampling=0)
                        updated += 1
                        break
        if updated:
            writer.add_metadata({"/OMRFixtureVersion": "synthetic-identity-v2"})
            buffer = BytesIO()
            writer.write(buffer)
            path.write_bytes(buffer.getvalue())
            print(f"Synthetic identity in {updated} PDF image(s): {path.relative_to(ROOT)}")
        writer.close()

    expected_path = handler / "answers/exam0.json"
    expected = json.loads(expected_path.read_text())
    for scan in expected["scans"]:
        for mark in scan["marks"]:
            field = mark["questionId"]
            if field[0] in IDENTITY:
                index = int(field[1:]) - 1
                value = IDENTITY[field[0]]
                mark["selected"] = [value[index]] if index < len(value) else []
    expected_path.write_text(json.dumps(expected, indent=4) + "\n")


def synthetic_images() -> None:
    """Replace unrelated illustration fixtures with original geometric samples."""
    files = (
        ("internal/pdf/testdata/sample_image.png", (2642, 2464)),
        ("internal/fs/testdata/sample_image.jpg", (2642, 2464)),
        ("internal/pdf/testdata/not_a_pdf.jpg", (1400, 1050)),
    )
    for filename, size in files:
        image = Image.new("RGB", size, "white")
        drawing = ImageDraw.Draw(image)
        width, height = size
        for row in range(12):
            for column in range(12):
                left, top = column * width // 12, row * height // 12
                drawing.rectangle((left, top, (column + 1) * width // 12, (row + 1) * height // 12),
                                  fill=(column * 21, row * 21, ((column + row) % 12) * 21))
        drawing.rectangle((width // 6, height // 3, width * 5 // 6, height * 2 // 3), fill="white", outline="black", width=8)
        drawing.text((width // 2, height // 2), "OMR synthetic image fixture", fill="black", anchor="mm", font=ImageFont.load_default(size=36))
        image.save(OMR / filename)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("screenshots", "fixtures"))
    args = parser.parse_args()
    if args.action == "screenshots":
        screenshots()
    else:
        sanitize_fixtures()
        directory = OMR / "internal/pdf/testdata"
        synthetic_pdf(directory / "sample.pdf", 5)
        synthetic_pdf(directory / "sample_large.pdf", 88)
        (directory / "not_a_pdf.txt").write_text("Synthetic malformed-PDF fixture. This is plain text, not a PDF.\n")
        synthetic_images()


if __name__ == "__main__":
    main()
