"""Snap the model's boxes onto the PDF's own text layer.

Gemini returns the printed text of every value and a box for it, but the boxes are often
misplaced (docs/progress.md 2026-11-16: on the clean e2e PDFs only about a third of the box
centres fell inside the true box, some a whole table row low). A born-digital PDF knows
exactly where each character is, so for every value we look for the text Gemini copied in
the page's text layer and take that position instead:

1. Find every occurrence of the copied text (whitespace-insensitive, on word boundaries).
2. Values printed once on the page are unambiguous: they become anchors. Their median
   offset from Gemini's boxes estimates Gemini's systematic shift on this page.
3. A value printed several times ("10", "20 %") takes the occurrence closest to its
   shift-corrected Gemini box; on a table line, the occurrence on the same row as that
   line's anchors wins.
4. A value not found verbatim (e.g. misread: "2 204,04" printed as "2 204,00") keeps the
   shift-corrected Gemini box, marked approximate.

Scans (JPEG) have no text layer; their boxes stay as Gemini returned them, marked
approximate. OCR word boxes can feed the same matcher later.
"""

from __future__ import annotations

import statistics
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

from trimatch.pdfium_lock import PDFIUM_LOCK
from trimatch.schema import Box

MAX_DISTANCE = 0.12  # page fractions: beyond this an occurrence is not "the same value"
ROW_TOLERANCE = 0.012  # page fractions: same table row if centres differ by less
MIN_ANCHORS = 3  # anchors needed before trusting a shift estimate


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def shifted(self, dx: float, dy: float) -> Rect:
        return Rect(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)


@dataclass
class PageText:
    """Non-space characters of one page, normalised, with their boxes (0..1, top-left)."""

    chars: str
    rects: list[Rect]
    word_start: list[bool]  # a space or punctuation precedes this char on the page
    word_end: list[bool]  # a space or punctuation follows it


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def _is_sep(ch: str) -> bool:
    return ch.isspace() or not ch.isalnum()


def page_text(pdf_path: Path, page_index: int = 0) -> PageText | None:
    """The text layer of a page, or None if the file has none (scans)."""
    with PDFIUM_LOCK:  # the pipeline extracts several files in parallel threads
        pdf = pdfium.PdfDocument(pdf_path)
        try:
            page = pdf[page_index]
            w, h = page.get_size()
            tp = page.get_textpage()
            n = tp.count_chars()
            raw = [tp.get_text_range(i, 1) or " " for i in range(n)]
            boxes = [tp.get_charbox(i) for i in range(n)]
        finally:
            pdf.close()
    chars: list[str] = []
    rects: list[Rect] = []
    starts: list[bool] = []
    ends: list[bool] = []
    for i, ch in enumerate(raw):
        if ch.isspace():
            continue
        left, bottom, right, top = boxes[i]
        r = Rect(left / w, 1 - top / h, right / w, 1 - bottom / h)
        prev_sep = i == 0 or _is_sep(raw[i - 1]) or _is_sep(ch)
        next_sep = i == n - 1 or _is_sep(raw[i + 1]) or _is_sep(ch)
        expanded = _norm(ch)  # NFKC/casefold may turn one char into several
        for j, c in enumerate(expanded):
            chars.append(c)
            rects.append(r)
            starts.append(prev_sep and j == 0)
            ends.append(next_sep and j == len(expanded) - 1)
    if not chars:
        return None
    return PageText("".join(chars), rects, starts, ends)


def occurrences(pt: PageText, text: str) -> list[Rect]:
    """Boxes of every word-aligned occurrence of `text` (spaces ignored)."""
    needle = "".join(_norm(text).split())
    if not needle:
        return []
    out = []
    start = pt.chars.find(needle)
    while start != -1:
        end = start + len(needle) - 1
        if pt.word_start[start] and pt.word_end[end]:
            rs = pt.rects[start : end + 1]
            out.append(
                Rect(
                    min(r.x0 for r in rs),
                    min(r.y0 for r in rs),
                    max(r.x1 for r in rs),
                    max(r.y1 for r in rs),
                )
            )
        start = pt.chars.find(needle, start + 1)
    return out


@dataclass
class Item:
    """One extracted value: what the model read and where it said it was."""

    key: object  # caller's handle for the value
    text: str | None
    model_box: Rect | None
    line: int | None = None  # table line, for row anchoring ("lines" of the document)
    found: list[Rect] = field(default_factory=list)


def _dist(a: Rect, b: Rect) -> float:
    return ((a.cx - b.cx) ** 2 + (a.cy - b.cy) ** 2) ** 0.5


def snap(items: Iterable[Item], pt: PageText | None) -> dict[object, Box]:
    """key -> Box (page 1). Exact text-layer positions where possible, else approximate."""
    items = [it for it in items if it.model_box is not None or it.text]
    if pt is None:
        return {it.key: _box(it.model_box, approximate=True) for it in items if it.model_box}
    for it in items:
        it.found = occurrences(pt, it.text) if it.text else []

    anchors = [it for it in items if len(it.found) == 1 and it.model_box]
    if len(anchors) >= MIN_ANCHORS:
        dx = statistics.median(it.found[0].cx - it.model_box.cx for it in anchors)
        dy = statistics.median(it.found[0].cy - it.model_box.cy for it in anchors)
    else:
        dx = dy = 0.0

    rows: dict[int, list[float]] = {}
    for it in items:
        if it.line is not None and len(it.found) == 1:
            rows.setdefault(it.line, []).append(it.found[0].cy)
    row_y = {line: statistics.median(ys) for line, ys in rows.items()}

    out: dict[object, Box] = {}
    for it in items:
        guess = it.model_box.shifted(dx, dy) if it.model_box else None
        chosen = None
        if len(it.found) == 1:
            chosen = it.found[0]
        elif it.found:
            cands = it.found
            if it.line in row_y:
                same_row = [r for r in cands if abs(r.cy - row_y[it.line]) <= ROW_TOLERANCE]
                cands = same_row or cands
            if guess is not None:
                best = min(cands, key=lambda r: _dist(r, guess))
                chosen = best if _dist(best, guess) <= MAX_DISTANCE else None
            elif len(cands) == 1:
                chosen = cands[0]
        if chosen is not None:
            out[it.key] = _box(chosen, approximate=False)
        elif guess is not None:
            out[it.key] = _box(guess, approximate=True)
    return out


def _box(r: Rect, approximate: bool) -> Box:
    def c(v: float) -> float:
        return round(min(1.0, max(0.0, v)), 4)

    return Box(page=1, x0=c(r.x0), y0=c(r.y0), x1=c(r.x1), y1=c(r.y1), approximate=approximate)
