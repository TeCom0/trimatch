"""Extractor interface (SPEC 2). Step 3 ships the label extractor; Gemini comes in step 4."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from trimatch.config import REPO_ROOT
from trimatch.schema import DeliveryNote, Invoice

Document = DeliveryNote | Invoice
_doc_adapter: TypeAdapter[Document] = TypeAdapter(Document)


class Extractor(Protocol):
    name: str

    def extract(self, path: Path) -> Document: ...


class LabelExtractor:
    """Returns the generator's ground truth for a synthetic file (an oracle, confidence 1.0).

    Used to test the deterministic back half of the pipeline on its own. The label is
    found by file stem: data/synthetic/<split>/<stem>.* -> data/labels/<split>/<stem>.json.
    """

    name = "labels"

    def __init__(self, labels_root: Path = REPO_ROOT / "data" / "labels"):
        self.labels_root = labels_root

    def extract(self, path: Path) -> Document:
        label = self.labels_root / path.parent.name / f"{path.stem}.json"
        if not label.is_file():
            raise FileNotFoundError(f"no ground-truth label for {path} (looked for {label})")
        return _doc_adapter.validate_json(label.read_text(encoding="utf-8"))


class Routed:
    """XML e-invoices are parsed (extract/ubl.py), never sent to a model; every other file
    goes to `base` (Gemini, or the labels oracle)."""

    def __init__(self, base: Extractor):
        from trimatch.extract.ubl import UblExtractor

        self.base, self.ubl = base, UblExtractor()
        self.name = base.name
        self.max_workers = getattr(base, "max_workers", 1)

    def extract(self, path: Path) -> Document:
        if path.suffix.lower() == ".xml":
            return self.ubl.extract(path)
        return self.base.extract(path)


def get_extractor(name: str) -> Extractor:
    if name == "labels":
        return Routed(LabelExtractor())
    if name == "gemini":
        from trimatch.extract.gemini import GeminiExtractor

        return Routed(GeminiExtractor())
    if name in ("local-vlm", "local-ocr-llm"):
        from trimatch.extract.local import LocalVlmExtractor, OcrLlmExtractor

        return Routed(LocalVlmExtractor() if name == "local-vlm" else OcrLlmExtractor())
    raise ValueError(
        f"unknown extractor {name!r} (available: labels, gemini, local-vlm, local-ocr-llm)"
    )
