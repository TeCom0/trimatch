"""Local extractors through Ollama on this machine (docs/plan-phase1-local-extractors.md).

- LocalVlmExtractor ("local-vlm"): a vision model reads the page image.
- OcrLlmExtractor ("local-ocr-llm"): OCR words (extract/ocr.py), laid out by lines, are read
  by a text model.

Both fill the same response schema as Gemini (gemini_schema.RDoc), so parsing, boxes
(snapped onto the PDF text layer or OCR words), validation and matching are unchanged.
Nothing leaves the machine: Ollama listens on 127.0.0.1 only. These are the only extractors
allowed for real documents. Responses are cached on disk like Gemini's.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import time
from pathlib import Path

import httpx
import pypdfium2 as pdfium
import yaml
from PIL import Image

from trimatch.config import CONFIG_DIR, REPO_ROOT
from trimatch.extract.gemini import NotADocument, snapped_boxes
from trimatch.extract.gemini_schema import RDoc, to_document
from trimatch.extract.ocr import IMAGE_SUFFIXES, layout_text, ocr_words
from trimatch.pdfium_lock import PDFIUM_LOCK
from trimatch.schema import DeliveryNote, Invoice

CACHE_ROOT = REPO_ROOT / "data" / "cache" / "local"
PROMPT = (Path(__file__).parent / "prompt_fr.md").read_text(encoding="utf-8")
OCR_PREAMBLE = (Path(__file__).parent / "prompt_ocr_fr.md").read_text(encoding="utf-8")
VLM_RULES = (Path(__file__).parent / "prompt_vlm_fr.md").read_text(encoding="utf-8")


def load_local_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "local.yaml").read_text(encoding="utf-8"))


def page_png(path: Path, max_side: int) -> bytes:
    """The page as PNG, longest side <= max_side px (vision models resize anyway)."""
    if path.suffix.lower() == ".pdf":
        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(path)
            try:
                img = pdf[0].render(scale=2.0).to_pil()
            finally:
                pdf.close()
    else:
        with Image.open(path) as im:
            img = im.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _OllamaExtractor:
    name = "local"
    kind = "base"
    max_workers = 1  # one model on one GPU: requests run one after another

    def __init__(self, model: str | None = None, use_cache: bool = True):
        cfg = load_local_config()
        self.cfg = cfg
        self.url = cfg["ollama_url"].rstrip("/")
        self.model = model or cfg[self.kind]["model"]
        self.options = {"temperature": 0, **cfg[self.kind].get("options", {})}
        self.use_cache = use_cache
        self.prompt_hash = self._prompt_hash()
        self.cache_dir = CACHE_ROOT / self.model.replace(":", "_") / self.prompt_hash
        self.calls = 0
        self._lock = threading.Lock()

    def _prompt(self) -> str:
        return PROMPT

    def _prompt_hash(self) -> str:
        schema = json.dumps(self.schema(), sort_keys=True)
        extra = json.dumps({"opts": self.options, "kind": self.kind}, sort_keys=True)
        return hashlib.sha256((self._prompt() + schema + extra).encode()).hexdigest()[:12]

    with_boxes = True  # ask the model for boxes (a vision model can give them)

    def _messages(self, path: Path) -> list[dict]:
        raise NotImplementedError

    def schema(self) -> dict:
        """RDoc's JSON schema; without the box field when the model can't see positions
        (fewer output tokens: constrained decoding is the slow part on this GPU)."""
        schema = RDoc.model_json_schema()
        if not self.with_boxes:
            rf = schema["$defs"]["RField"]
            rf["properties"].pop("box", None)
            rf["required"] = [k for k in rf["required"] if k != "box"]
        return schema

    def parse(self, text: str) -> RDoc:
        data = json.loads(text)
        box_order = self.cfg[self.kind].get("box_order", "yxyx")

        def walk(o):
            if isinstance(o, dict):
                if "text" in o and "confidence" in o:
                    b = o.get("box") or []
                    if box_order == "xyxy" and len(b) == 4:
                        b = [b[1], b[0], b[3], b[2]]  # Qwen-VL gives [x1, y1, x2, y2]
                    o["box"] = b
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(data)
        return RDoc.model_validate(data)

    def raw(self, path: Path) -> dict:
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        cache = self.cache_dir / f"{sha}.json"
        if self.use_cache and cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))
        t0 = time.perf_counter()
        messages = self._messages(path)
        prep = time.perf_counter() - t0
        body = {
            "model": self.model,
            "messages": messages,
            "format": self.schema(),
            "stream": False,
            "think": False,
            "options": self.options,
        }
        t1 = time.perf_counter()
        resp = httpx.post(f"{self.url}/api/chat", json=body, timeout=900)
        resp.raise_for_status()
        out = resp.json()
        with self._lock:
            self.calls += 1
        record = {
            "file": str(path.resolve().relative_to(REPO_ROOT).as_posix())
            if path.resolve().is_relative_to(REPO_ROOT)
            else path.name,
            "sha256": sha,
            "model": self.model,
            "model_version": out.get("model"),
            "prompt_hash": self.prompt_hash,
            "latency_s": round(prep + time.perf_counter() - t1, 2),
            "prep_s": round(prep, 2),
            "usage": {
                "prompt_tokens": out.get("prompt_eval_count"),
                "output_tokens": out.get("eval_count"),
                "thinking_tokens": 0,
                "total_tokens": (out.get("prompt_eval_count") or 0) + (out.get("eval_count") or 0),
            },
            "text": out["message"]["content"],
        }
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
        return record

    def extract(self, path: Path) -> DeliveryNote | Invoice:
        rdoc = self.parse(self.raw(path)["text"])
        doc = to_document(rdoc, snapped_boxes(rdoc, path))
        if doc is None:
            raise NotADocument(f"{path.name}: the model says this is neither an invoice nor a BL")
        return doc


class LocalVlmExtractor(_OllamaExtractor):
    name = "local-vlm"
    kind = "vlm"

    def _prompt(self) -> str:
        return PROMPT + "\n" + VLM_RULES

    def _messages(self, path: Path) -> list[dict]:
        img = page_png(path, self.cfg["vlm"]["max_side"])
        return [
            {
                "role": "user",
                "content": self._prompt(),
                "images": [base64.b64encode(img).decode("ascii")],
            }
        ]


class OcrLlmExtractor(_OllamaExtractor):
    name = "local-ocr-llm"
    kind = "ocr_llm"
    with_boxes = False

    def _prompt(self) -> str:
        return OCR_PREAMBLE + "\n" + PROMPT

    def _messages(self, path: Path) -> list[dict]:
        if path.suffix.lower() == ".pdf":
            # A born-digital PDF: render and OCR it like a scan, so the text the model sees
            # comes the same way for every document.
            words = ocr_words_from_png(page_png(path, 2400))
        elif path.suffix.lower() in IMAGE_SUFFIXES:
            words = ocr_words(path)
        else:
            raise ValueError(f"{path.name}: not a page image or PDF")
        text = layout_text(words)
        return [
            {"role": "system", "content": self._prompt()},
            {"role": "user", "content": f"OCR du document, ligne par ligne :\n\n{text}"},
        ]


def ocr_words_from_png(png: bytes):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "page.png"
        f.write_bytes(png)
        return ocr_words(f)
