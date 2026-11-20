"""Words with positions for any page: the PDF text layer, or OCR for scans and photos.

Feeds extract/snap.py (exact highlight boxes on scans too) and the OCR + local LLM
extractor (docs/plan-phase1-local-extractors.md). Two OCR engines, compared by measurement:

- "rapidocr": PaddleOCR PP-OCR models through RapidOCR / ONNX Runtime (CPU), Latin script
- "tesseract": Tesseract 5 with French data, through its CLI (TSV output)

Both are Apache-2.0. Tools and models live on D: (config/ocr.yaml); nothing is downloaded
at run time.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import itertools
import math
import os
import statistics
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from PIL import Image

from trimatch.config import CONFIG_DIR
from trimatch.extract.snap import PageText, Rect, page_text

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class Word:
    text: str
    rect: Rect  # 0..1, origin top-left
    line: int  # reading-order line number (for the LLM layout)
    conf: float  # engine confidence 0..1
    # Centre after undoing the page's tilt (a photo or a skewed scan), for grouping words
    # into printed rows. None: the rect itself.
    xd: float | None = None
    yd: float | None = None

    @property
    def row_y(self) -> float:
        return self.rect.cy if self.yd is None else self.yd

    @property
    def row_x(self) -> float:
        return self.rect.x0 if self.xd is None else self.xd


@cache
def settings() -> dict:
    return yaml.safe_load((CONFIG_DIR / "ocr.yaml").read_text(encoding="utf-8"))


# --- engines -----------------------------------------------------------------------------


@cache
def _rapid():
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    s = settings()["rapidocr"]
    root = s["model_root_dir"]
    Path(root).mkdir(parents=True, exist_ok=True)
    return RapidOCR(
        params={
            "Global.model_root_dir": root,
            "Global.log_level": "error",
            "Rec.lang_type": LangRec.LATIN,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
        }
    )


def _rapid_words(img: Image.Image) -> list[Word]:
    w, h = img.size
    res = _rapid()(img, return_word_box=True)
    out: list[Word] = []
    if res.boxes is None:
        return out
    lines = sorted(
        zip(
            res.boxes,
            res.txts,
            res.scores,
            res.word_results or [None] * len(res.txts),
            strict=False,
        ),
        key=lambda t: (min(p[1] for p in t[0]), min(p[0] for p in t[0])),
    )
    for li, (poly, text, score, words) in enumerate(lines):
        if words:  # [(text, score, box4)] per word
            for wt, ws, wbox in words:
                if wt.strip():
                    out.append(Word(wt, _rect(wbox, w, h), li, float(ws)))
        elif text.strip():
            out.append(Word(text, _rect(poly, w, h), li, float(score)))
    return _deskew(out, _skew([t[0] for t in lines]), w, h)


def _skew(polys) -> float:
    """Median angle (radians) of the long text lines: how much the page is tilted."""
    angles = []
    for p in polys:
        (x0, y0), (x1, y1) = p[0][:2], p[1][:2]
        width = math.hypot(x1 - x0, y1 - y0)
        height = math.hypot(p[3][0] - x0, p[3][1] - y0)
        if width > 3 * max(height, 1):
            angles.append(math.atan2(y1 - y0, x1 - x0))
    return statistics.median(angles) if angles else 0.0


def _deskew(words: list[Word], angle: float, w: int, h: int) -> list[Word]:
    if abs(angle) < math.radians(0.3):
        return words
    cos, sin = math.cos(-angle), math.sin(-angle)
    out = []
    for wd in words:
        x, y = wd.rect.x0 * w - w / 2, wd.rect.cy * h - h / 2
        out.append(
            dataclasses.replace(
                wd,
                xd=(x * cos - y * sin + w / 2) / w,
                yd=(x * sin + y * cos + h / 2) / h,
            )
        )
    return out


def _rect(poly, w: int, h: int) -> Rect:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return Rect(min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h)


def _tesseract_words(img: Image.Image) -> list[Word]:
    s = settings()["tesseract"]
    env = {**os.environ, "TESSDATA_PREFIX": s["tessdata"]}
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    proc = subprocess.run(
        [s["exe"], "stdin", "stdout", "-l", s["lang"], "--psm", "3", "-c", "tessedit_create_tsv=1"],
        input=buf.getvalue(),
        capture_output=True,
        env=env,
        check=True,
    )
    w, h = img.size
    out: list[Word] = []
    rows = csv.DictReader(
        io.StringIO(proc.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
    )
    line_ids: dict[tuple, int] = {}
    for r in rows:
        text = (r.get("text") or "").strip()
        if r.get("level") != "5" or not text:
            continue
        key = (r["block_num"], r["par_num"], r["line_num"])
        line = line_ids.setdefault(key, len(line_ids))
        x, y, bw, bh = (int(r[k]) for k in ("left", "top", "width", "height"))
        out.append(
            Word(
                text,
                Rect(x / w, y / h, (x + bw) / w, (y + bh) / h),
                line,
                max(0.0, float(r["conf"]) / 100),
            )
        )
    return out


ENGINES = {"rapidocr": _rapid_words, "tesseract": _tesseract_words}


def ocr_words(path: Path, engine: str | None = None) -> list[Word]:
    engine = engine or settings()["engine"]
    with Image.open(path) as im:
        return ENGINES[engine](im.convert("RGB"))


# --- as a text layer -----------------------------------------------------------------------


def words_to_page(words: list[Word]) -> PageText | None:
    """OCR words -> the PageText snap.py matches against. Characters are spread evenly over
    their word's box (OCR gives no per-character positions)."""
    chars: list[str] = []
    rects: list[Rect] = []
    starts: list[bool] = []
    ends: list[bool] = []
    for wd in words:
        text = "".join(wd.text.split()).casefold()
        if not text:
            continue
        step = (wd.rect.x1 - wd.rect.x0) / len(text)
        for i, ch in enumerate(text):
            chars.append(ch)
            rects.append(
                Rect(wd.rect.x0 + i * step, wd.rect.y0, wd.rect.x0 + (i + 1) * step, wd.rect.y1)
            )
            starts.append(i == 0 or not ch.isalnum() or not text[i - 1].isalnum())
            ends.append(i == len(text) - 1 or not ch.isalnum() or not text[i + 1].isalnum())
    return PageText("".join(chars), rects, starts, ends) if chars else None


def page_words(path: Path, engine: str | None = None) -> PageText | None:
    """Text layer of a PDF, or OCR of an image. None if the file has neither."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return page_text(path)
    if suffix in IMAGE_SUFFIXES:
        return words_to_page(ocr_words(path, engine))
    return None


def layout_text(words: list[Word]) -> str:
    """OCR words as plain text for the text-only LLM: words grouped into printed rows by
    vertical overlap (OCR engines often return each table cell as its own line), each row
    read left to right; a wide gap (another column) is written " | "."""
    if not words:
        return ""
    heights = sorted(w.rect.y1 - w.rect.y0 for w in words)
    tol = heights[len(heights) // 2] * 0.5
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.row_y):
        if rows and abs(w.row_y - sum(x.row_y for x in rows[-1]) / len(rows[-1])) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return "\n".join(_join_row(sorted(r, key=lambda w: w.row_x)) for r in rows)


COLUMN_GAP = 0.02  # page widths: a wider gap between two words means another column


def _join_row(row: list[Word]) -> str:
    out = row[0].text
    for prev, w in itertools.pairwise(row):
        out += (" | " if w.rect.x0 - prev.rect.x1 > COLUMN_GAP else " ") + w.text
    return out
