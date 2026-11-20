"""Local extractors and OCR helpers: pure parts only (CI has no Ollama, no OCR models)."""

from __future__ import annotations

import json

import pytest

from trimatch.extract.gemini_schema import RDoc
from trimatch.extract.ocr import Word, layout_text, words_to_page
from trimatch.extract.snap import Item, Rect, occurrences, snap

# --- OCR words as text and as a text layer ---------------------------------------------------


def W(text, x0, y0, x1, y1, line=0):
    return Word(text, Rect(x0, y0, x1, y1), line, 0.99)


ROW = [
    W("ANF-HT05", 0.08, 0.400, 0.15, 0.410),
    W("Huile", 0.20, 0.401, 0.24, 0.411),
    W("de", 0.245, 0.401, 0.26, 0.411),
    W("table", 0.265, 0.401, 0.30, 0.411),
    W("99,36", 0.70, 0.399, 0.75, 0.409),
]


def test_layout_groups_cells_into_rows_and_marks_columns():
    other = W("Total", 0.60, 0.50, 0.65, 0.51)
    text = layout_text([*reversed(ROW), other])
    assert text.splitlines() == ["ANF-HT05 | Huile de table | 99,36", "Total"]


def test_words_become_a_text_layer_snap_can_match():
    pt = words_to_page(ROW)
    [r] = occurrences(pt, "99,36")
    assert r.x0 == pytest.approx(0.70) and r.x1 == pytest.approx(0.75)
    [r] = occurrences(pt, "Huile de table")  # spaces ignored, spans three words
    assert r.x0 == pytest.approx(0.20) and r.x1 == pytest.approx(0.30)
    assert occurrences(pt, "9,3") == []  # starts mid-word inside "99,36"
    assert words_to_page([]) is None


# --- scans: stricter snapping ------------------------------------------------------------------

PAGE = words_to_page(
    [
        W("10", 0.80, 0.40, 0.82, 0.41),
        W("%", 0.825, 0.40, 0.835, 0.41),
        W("10", 0.80, 0.43, 0.82, 0.44),
        W("%", 0.825, 0.43, 0.835, 0.44),
        W("FA-1", 0.80, 0.10, 0.85, 0.11),
    ]
)


def test_scan_takes_a_repeated_value_only_when_clearly_nearest():
    near_first = Rect(0.80, 0.401, 0.835, 0.411)
    out = snap([Item("a", "10 %", near_first)], PAGE, scan=True)
    assert not out["a"].approximate and out["a"].y0 == pytest.approx(0.40)
    between = Rect(0.80, 0.415, 0.835, 0.425)  # halfway: not clear
    out = snap([Item("b", "10 %", between)], PAGE, scan=True)
    assert out["b"].approximate


def test_scan_unique_value_far_from_the_model_box_stays_approximate():
    far = Rect(0.10, 0.80, 0.15, 0.81)
    assert snap([Item("n", "FA-1", far)], PAGE, scan=True)["n"].approximate
    near = Rect(0.80, 0.105, 0.85, 0.115)
    assert not snap([Item("n", "FA-1", near)], PAGE, scan=True)["n"].approximate


def test_scan_without_model_boxes_keeps_unique_values_only():
    out = snap([Item("n", "FA-1", None), Item("r", "10 %", None)], PAGE, scan=True)
    assert not out["n"].approximate and "r" not in out


# --- local extractor response handling ---------------------------------------------------------


def _rfield(text, box=None):
    f = {"text": text, "confidence": 0.9}
    if box is not None:
        f["box"] = box
    return f


def _doc(box=None) -> dict:
    party = {k: _rfield(None, box) for k in ("name", "ice", "if_number", "tp_number", "rc")}
    return {
        "doc_type": "invoice",
        "supplier": party,
        "customer": party,
        **{
            k: _rfield("x", box)
            for k in (
                "number",
                "date",
                "due_date",
                "payment_terms",
                "po_ref",
                "total_ht",
                "total_ttc",
            )
        },
        "bl_refs": [],
        "lines": [],
        "vat": [],
    }


@pytest.fixture
def extractors(monkeypatch):
    from trimatch.extract import local

    cfg = {
        "ollama_url": "http://127.0.0.1:1",
        "vlm": {"model": "m", "max_side": 100, "box_order": "xyxy", "options": {}},
        "ocr_llm": {"model": "t", "options": {}},
    }
    monkeypatch.setattr(local, "load_local_config", lambda: cfg)
    return local.LocalVlmExtractor(), local.OcrLlmExtractor()


def test_vision_model_boxes_are_reordered_to_ymin_xmin(extractors):
    vlm, _ = extractors
    rdoc = vlm.parse(json.dumps(_doc(box=[774, 108, 920, 126])))  # Qwen: x1, y1, x2, y2
    assert rdoc.number.box == [108, 774, 126, 920]


def test_text_model_gets_no_box_field_and_parses_without_it(extractors):
    _, ocr_llm = extractors
    rf = ocr_llm.schema()["$defs"]["RField"]
    assert "box" not in rf["properties"] and "box" not in rf["required"]
    rdoc = ocr_llm.parse(json.dumps(_doc()))
    assert isinstance(rdoc, RDoc) and rdoc.number.box == []
    assert ocr_llm.prompt_hash != extractors[0].prompt_hash


def test_stratified_subset_balances_variants_and_types():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from eval.run import stratified

    docs = [
        {"doc_id": f"{v}{t}{i}", "variant": v, "doc_type": t}
        for v in ("clean", "rot", "blur")
        for t in ("invoice", "delivery_note")
        for i in range(3)
    ]
    sub = stratified({"documents": docs}, 6)["documents"]
    assert len(sub) == 6
    assert {(d["variant"], d["doc_type"]) for d in sub} == {
        (v, t) for v in ("clean", "rot", "blur") for t in ("invoice", "delivery_note")
    }


def test_unreadable_file_goes_to_review_instead_of_stopping_the_run(tmp_path, seed, refs):
    from pathlib import Path

    from test_api import FakeOdoo

    from trimatch.extract.gemini import NotADocument
    from trimatch.pipeline import JsonReviewSink, process

    class Broken:
        name = "broken"

        def extract(self, path: Path):
            raise NotADocument(f"{path.name}: no valid JSON after 2 tries")

    results, _ = process(
        [Path("a.pdf")], Broken(), FakeOdoo(seed, refs), review_sink=JsonReviewSink(tmp_path)
    )
    [r] = results
    assert r.decision.action == "review" and "EXTRACTION_FAILED" in r.decision.codes
    assert "no valid JSON" in next(
        c.detail for c in r.decision.reasons if c.code == "EXTRACTION_FAILED"
    )
    assert list(tmp_path.glob("*.json"))  # a case for a person


def test_retry_room_doubles_the_output_budget():
    from trimatch.extract.local import _is_json, _more_room

    assert _more_room({"num_predict": 4096, "num_ctx": 8192}) == {
        "num_predict": 8192,
        "num_ctx": 12288,
    }
    assert _is_json('{"a": 1}') and not _is_json('{"a": ')
