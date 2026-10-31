"""Seed-only helpers for producing realistic scanner-like PDFs."""

import io
import random

import fitz
from PIL import Image, ImageEnhance, ImageFilter


RENDER_ZOOM = 3.0


def _simulate_scan_noise(jpeg_bytes: bytes, rng: random.Random) -> bytes:
    """Apply mild scanner/printer artifacts to a rendered PDF page.

    Takes an explicit Random instance instead of drawing from the bare
    random module, so a caller that wants reproducible output (a fixed-seed
    fixture generator) can rely on it. A process talking to a real DB over
    asyncpg in the same event loop can draw from that shared global random
    state too, so module-level random.seed() alone doesn't guarantee
    reproducibility here.
    """
    image = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    width, height = image.size
    image = image.rotate(
        rng.uniform(-1.5, 1.5),
        resample=Image.BICUBIC,
        fillcolor=(255, 255, 255),
    )

    jitter = 0.0015

    def point(x, y):
        return (
            x + rng.uniform(-jitter, jitter) * width,
            y + rng.uniform(-jitter, jitter) * height,
        )

    quad = (*point(0, 0), *point(0, height), *point(width, height), *point(width, 0))
    image = image.transform(
        (width, height),
        Image.QUAD,
        quad,
        resample=Image.BICUBIC,
        fillcolor=(255, 255, 255),
    )
    image = image.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.25, 0.5)))
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.9, 1.1))
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.9, 1.1))

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=rng.randint(80, 92))
    return output.getvalue()


def render_scanner_like_pdf(pdf_bytes: bytes, zoom: float = RENDER_ZOOM, rng: random.Random | None = None) -> bytes:
    """Rasterize a generated PDF and add light scanner artifacts for seeds.

    zoom controls the embedded raster's DPI (dpi = zoom * 72) -- pass a
    different value to deliberately produce a fixture at a different
    resolution, e.g. for testing DPI auto-detection. rng, if given, is used
    for the degradation noise instead of a fresh unseeded Random(); pass a
    seeded instance for reproducible output (see _simulate_scan_noise).
    """
    if rng is None:
        rng = random.Random()
    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    output = fitz.open()
    matrix = fitz.Matrix(zoom, zoom)
    try:
        for page in source:
            pixels = page.get_pixmap(matrix=matrix, alpha=False)
            destination = output.new_page(width=page.rect.width, height=page.rect.height)
            destination.insert_image(
                destination.rect, stream=_simulate_scan_noise(pixels.tobytes(output="jpeg"), rng)
            )
        # PyMuPDF otherwise writes a random /ID trailer entry on every call
        # regardless of content, which defeats byte-for-byte reproducibility
        # for a fixed-seed caller even with identical pixels.
        return output.tobytes(no_new_id=True)
    finally:
        output.close()
        source.close()
