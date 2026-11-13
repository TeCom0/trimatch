"""Rasterise a rendered PDF and apply one degradation (SPEC 8). Boxes follow the image."""

from __future__ import annotations

import math
import random
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from trimatch.schema import Box, DeliveryNote, Field, Invoice

from .render import FONTS

DPI = 150
JPEG_QUALITY = 70


def rasterise(pdf_path: Path, dpi: int = DPI) -> Image.Image:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return pdf[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()


def iter_fields(model) -> list[Field]:
    """All Field leaves of a document model."""
    out: list[Field] = []

    def walk(obj):
        if isinstance(obj, Field):
            out.append(obj)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)
        elif hasattr(obj, "__pydantic_fields__"):
            for name in type(obj).model_fields:
                walk(getattr(obj, name))

    walk(model)
    return out


def _rotate(img: Image.Image, label, angle: float) -> Image.Image:
    """Rotate counter-clockwise by angle degrees (PIL convention), expanding the canvas.

    Each box becomes the axis-aligned box around its four rotated corners.
    """
    w, h = img.size
    out = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    w2, h2 = out.size
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)

    def tf(x, y):
        dx, dy = x - w / 2, y - h / 2
        # Visual CCW rotation in image coordinates (y points down).
        return dx * c + dy * s + w2 / 2, -dx * s + dy * c + h2 / 2

    for f in iter_fields(label):
        if f.source is None:
            continue
        b = f.source
        pts = [tf(x * w, y * h) for x in (b.x0, b.x1) for y in (b.y0, b.y1)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        f.source = Box(
            page=b.page,
            x0=round(max(0.0, min(xs) / w2), 5),
            y0=round(max(0.0, min(ys) / h2), 5),
            x1=round(min(1.0, max(xs) / w2), 5),
            y1=round(min(1.0, max(ys) / h2), 5),
        )
    return out


def _stamp(img: Image.Image, label, rng: random.Random, when: date) -> Image.Image:
    """A semi-transparent 'REÇU' stamp with a date, over part of the line table."""
    w, h = img.size
    lines = [f.source for f in iter_fields(label.lines) if f.source]
    y_top = min(b.y0 for b in lines) * h
    y_bot = max(b.y1 for b in lines) * h
    color = rng.choice([(200, 30, 40), (30, 60, 170)])
    font_big = ImageFont.truetype(str(FONTS / "Inter.ttf"), 64)
    font_small = ImageFont.truetype(str(FONTS / "Inter.ttf"), 26)
    sw, sh = 330, 150
    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    alpha = rng.randint(140, 190)
    ink = (*color, alpha)
    d.rounded_rectangle((4, 4, sw - 4, sh - 4), radius=14, outline=ink, width=6)
    d.text(
        (sw / 2, 58), "REÇU", font=font_big, fill=ink, anchor="mm", stroke_width=2, stroke_fill=ink
    )
    d.text((sw / 2, 115), f"le {when.strftime('%d/%m/%Y')}", font=font_small, fill=ink, anchor="mm")
    layer = layer.rotate(rng.uniform(-18, 18), resample=Image.BICUBIC, expand=True)
    x = rng.randint(int(w * 0.25), int(w * 0.65) - layer.width // 2)
    y = int(rng.uniform(y_top, max(y_top + 1, y_bot - layer.height * 0.6)))
    base = img.convert("RGBA")
    base.alpha_composite(layer, (max(0, x), max(0, y)))
    return base.convert("RGB")


def degrade(
    pdf_path: Path, label: DeliveryNote | Invoice, variant: str, rng_key: str, out_jpg: Path
) -> DeliveryNote | Invoice:
    """Rasterise + one degradation -> out_jpg. Returns the label with boxes adjusted."""
    rng = random.Random(f"{rng_key}-degrade")
    label = label.model_copy(deep=True)
    img = rasterise(pdf_path)
    if variant == "rot":
        angle = rng.uniform(3, 8) * rng.choice([-1, 1])
        img = _rotate(img, label, angle)
    elif variant == "blur":
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(1.0, 1.6)))
    elif variant == "stamp":
        img = _stamp(img, label, rng, label.date.value)
    elif variant == "handwriting":
        pass  # handwriting is drawn at render time; only rasterise + JPEG here
    else:
        raise ValueError(f"unknown variant {variant!r}")
    img.save(out_jpg, "JPEG", quality=JPEG_QUALITY, dpi=(DPI, DPI))
    return label
