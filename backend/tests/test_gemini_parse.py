"""Gemini output parsing, offline (recorded response of a synthetic document)."""

import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from trimatch.config import REPO_ROOT
from trimatch.extract.gemini import check_path
from trimatch.extract.gemini_schema import (
    RDoc,
    RField,
    _f,
    parse_date,
    parse_decimal,
    parse_ice,
    parse_rate,
    parse_sentence,
    to_document,
)
from trimatch.money import totals
from trimatch.schema import Invoice

FIXTURE = Path(__file__).parent / "fixtures" / "gemini_PO-005_invoice_blur.json"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2 450,00", D("2450.00")),
        ("2 450,00", D("2450.00")),
        ("2.450,00", D("2450.00")),
        ("99,36", D("99.36")),
        ("12,5", D("12.5")),
        ("10", D(10)),
        ("4 810,00 DH", D("4810.00")),
        ("1710.50", D("1710.50")),
        ("abc", None),
        (None, None),
    ],
)
def test_parse_decimal(text, expected):
    assert parse_decimal(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("20 %", D(20)),
        ("TVA 20 %", D(20)),
        ("10%", D(10)),
        ("Exonéré", D(0)),
        ("EXONERE", D(0)),
        (None, None),
    ],
)
def test_parse_rate(text, expected):
    assert parse_rate(text) == expected


def test_parse_date_ice_sentence():
    assert parse_date("06/11/2026") == date(2026, 11, 6)
    assert parse_date("2026-11-06") == date(2026, 11, 6)
    assert parse_date("31/02/2026") is None
    assert parse_ice("999 528 614 000 104") == "999528614000104"
    assert parse_sentence("Paiement à 30 jours par virement.") == "Paiement à 30 jours par virement"


def test_unparseable_value_gets_zero_confidence():
    f = _f(RField(text="12,5O", confidence=0.97, box=[1, 2, 3, 4]), parse_decimal)
    assert f.value is None and f.confidence == 0.0


def test_box_is_converted_from_gemini_order():
    f = _f(RField(text="10", confidence=1, box=[100, 200, 150, 300]), parse_decimal)
    assert (f.source.x0, f.source.y0, f.source.x1, f.source.y1) == (0.2, 0.1, 0.3, 0.15)


def test_recorded_invoice_parses_and_adds_up():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = to_document(RDoc.model_validate_json(raw["text"]))
    assert isinstance(doc, Invoice)
    assert doc.supplier.ice.value == "999702846000146"
    assert doc.po_ref.value == "PO-005"
    ht, _vat, ttc = totals((ln.vat_rate.value, ln.line_total_ht.value) for ln in doc.lines)
    assert (doc.total_ht.value, doc.total_ttc.value) == (ht, ttc) == (D("2142.50"), D("2484.60"))


def test_only_synthetic_files_may_be_sent(tmp_path):
    secret = tmp_path / "real_invoice.pdf"
    secret.write_bytes(b"%PDF")
    with pytest.raises(PermissionError):
        check_path(secret)
    with pytest.raises(PermissionError):
        check_path(REPO_ROOT / "data" / "raw" / "x.pdf")
