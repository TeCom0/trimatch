"""HTML (Jinja2) -> PDF (Playwright/Chromium), plus the ground-truth box of every field.

Every printed value sits in an element with data-field="<schema path>". After layout,
the element's bounding box is read from the page and normalised to 0..1 of the A4 page.
"""

from __future__ import annotations

import random
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from playwright.sync_api import Browser

from trimatch.generate.data import GenDoc
from trimatch.money import fr_amount, fr_qty
from trimatch.schema import Box, DeliveryNote, Field, Invoice, get_path

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"

A4_W_PX = 210 / 25.4 * 96  # CSS px at 96 dpi
A4_H_PX = 297 / 25.4 * 96

HW_FONTS = [("Caveat", "17pt"), ("HomemadeApple", "14pt")]

_env = Environment(
    loader=FileSystemLoader(HERE / "templates"), autoescape=True, undefined=StrictUndefined
)
_env.filters["fr_amount"] = lambda x: fr_amount(Decimal(x))
_env.filters["fr_qty"] = lambda x: fr_qty(Decimal(x))
_env.filters["fr_date"] = lambda d: d.strftime("%d/%m/%Y")
_env.filters["pct"] = lambda x: f"{Decimal(x).normalize():f} %"

_BOXES_JS = """
() => Array.from(document.querySelectorAll('[data-field]')).map(el => {
  const r = el.getBoundingClientRect();
  return [el.dataset.field, r.left, r.top, r.right, r.bottom];
})
"""


def render_html(doc: GenDoc) -> str:
    rng = random.Random(f"{doc.rng_key}-hw")
    hw = doc.variant == "handwriting"
    hw_font, hw_size = rng.choice(HW_FONTS)
    jitter = [
        (round(rng.uniform(-6, 6), 1), round(rng.uniform(-6, 2), 1), round(rng.uniform(-2, 2), 1))
        for _ in doc.label.lines
    ]
    label_date: date = doc.label.date.value
    return _env.get_template("doc.html").render(
        doc=doc.label,
        kind=doc.kind,
        b=doc.ctx["branding"],
        sup=doc.ctx["supplier"],
        comp=doc.ctx["company"],
        amount_words=doc.ctx.get("amount_words", ""),
        fonts=FONTS.as_uri(),
        hw=hw,
        hw_font=hw_font,
        hw_size=hw_size,
        jitter=jitter,
        hw_initials=rng.choice(["K.B.", "S. Alami", "Y.E.", "M.R."]),
        hw_date=label_date.strftime("%d/%m"),
    )


def render_pdf(browser: Browser, doc: GenDoc, out_pdf: Path) -> DeliveryNote | Invoice:
    """Render one document to out_pdf and return a copy of its label with boxes filled in."""
    html = render_html(doc)
    page = browser.new_page(viewport={"width": round(A4_W_PX), "height": round(A4_H_PX)})
    try:
        page.emulate_media(media="print")
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            tmp = Path(f.name)
        try:
            page.goto(tmp.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            height = page.evaluate("document.documentElement.scrollHeight")
            if height > A4_H_PX + 2:
                raise ValueError(f"{doc.doc_id}: content overflows one A4 page ({height}px)")
            boxes = page.evaluate(_BOXES_JS)
            page.pdf(
                path=str(out_pdf),
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        page.close()

    label = doc.label.model_copy(deep=True)
    seen: set[str] = set()
    for path, x0, y0, x1, y1 in boxes:
        target = get_path(label, path)
        if not isinstance(target, Field):
            raise TypeError(f"{doc.doc_id}: data-field {path!r} is not a Field")
        if path in seen:
            raise ValueError(f"{doc.doc_id}: data-field {path!r} appears twice")
        seen.add(path)
        target.source = Box(
            page=1,
            x0=round(x0 / A4_W_PX, 5),
            y0=round(y0 / A4_H_PX, 5),
            x1=round(x1 / A4_W_PX, 5),
            y1=round(y1 / A4_H_PX, 5),
        )
    return label
