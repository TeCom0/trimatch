"""Page images for the document viewer. PDFs are rasterised with pypdfium2 and cached on
disk under data/cache/pages; JPEG/PNG scans are served as they are (one page)."""

from __future__ import annotations

import hashlib
import io
import mimetypes
import uuid
from pathlib import Path

import pypdfium2 as pdfium

from trimatch.config import REPO_ROOT
from trimatch.pdfium_lock import PDFIUM_LOCK

CACHE_DIR = REPO_ROOT / "data" / "cache" / "pages"
SCALE = 2.0  # 144 dpi: sharp enough to read small print when zoomed


def media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def page_count(path: Path) -> int:
    if media_type(path) != "application/pdf":
        return 1
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(path)
        try:
            return len(pdf)
        finally:
            pdf.close()


def page_image(path: Path, page: int, cache_dir: Path | None = None) -> tuple[bytes, str]:
    """-> (image bytes, media type) for a 1-based page. Raises IndexError on a bad page."""
    mt = media_type(path)
    if mt != "application/pdf":
        if page != 1:
            raise IndexError(page)
        return path.read_bytes(), mt
    stat = path.stat()
    key = hashlib.sha256(
        f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{page}|{SCALE}".encode()
    ).hexdigest()[:32]
    cache_dir = cache_dir or CACHE_DIR
    cached = cache_dir / f"{key}.png"
    if cached.is_file():
        return cached.read_bytes(), "image/png"
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(path)
        try:
            if not 1 <= page <= len(pdf):
                raise IndexError(page)
            image = pdf[page - 1].render(scale=SCALE).to_pil()
        finally:
            pdf.close()
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(f".{uuid.uuid4().hex}.tmp")  # unique: concurrent renders
    tmp.write_bytes(data)
    tmp.replace(cached)
    return data, "image/png"
