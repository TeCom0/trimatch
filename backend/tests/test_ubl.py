"""UBL 2.1 e-invoices: writer, schema check, parser, security, routing, planted cases."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from conftest import CFG, make_po

from trimatch.api import pages
from trimatch.extract import LabelExtractor, Routed
from trimatch.extract.ubl import (
    UblExtractor,
    load_mapping,
    parse_invoice,
    schema_errors,
    ubl_check,
    write_invoice,
)
from trimatch.generate.data import build_split, load_seed_data
from trimatch.generate.ubl_split import planted
from trimatch.pipeline import evaluate, file_checks
from trimatch.store.cases import case_key


@pytest.fixture(scope="module")
def invoices():
    return {
        d.doc_id: d.label
        for d in build_split("e2e", load_seed_data())
        if d.kind == "invoice" and d.variant == "clean"
    }


def values(doc) -> dict:
    """Field values only (no boxes, locators or confidence), numbers normalised."""

    def walk(o):
        if isinstance(o, dict) and "value" in o and "confidence" in o:
            v = o["value"]
            try:
                return str(Decimal(v).normalize()) if isinstance(v, str) else v
            except Exception:  # noqa: BLE001 (not a number)
                return v
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return walk(doc.model_dump(mode="json"))


def test_every_e2e_invoice_round_trips_through_valid_ubl(invoices):
    for doc_id, inv in invoices.items():
        xml = write_invoice(inv)
        assert schema_errors(xml) == [], doc_id
        assert values(parse_invoice(xml)) == values(inv), doc_id


def test_parsed_values_are_certain_and_say_where_they_came_from(invoices):
    inv = parse_invoice(write_invoice(invoices["e2e_PO-001_invoice_clean"]))
    assert inv.total_ttc.confidence == 1.0 and inv.total_ttc.source is None
    assert inv.total_ttc.locator == "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"
    assert inv.supplier.ice.locator.endswith("cbc:CompanyID[@schemeID='ICE']")
    assert inv.lines[1].unit_price_ht.locator == "cac:InvoiceLine[2]/cac:Price/cbc:PriceAmount"


def test_moroccan_mapping_exempt_lines_and_units(invoices):
    m = load_mapping()
    xml = write_invoice(invoices["e2e_PO-001_invoice_clean"]).decode()
    assert f'schemeID="{m.party["ice"]["scheme"]}"' in xml
    assert "<cbc:ID>E</cbc:ID>" in xml and "art. 91-I-A" in xml  # Boucherie-Marée: exempt
    assert 'unitCode="KGM"' in xml
    parsed = parse_invoice(xml.encode())
    assert {ln.vat_rate.value for ln in parsed.lines} == {Decimal(0)}
    assert parsed.lines[0].unit.value == "kg"


def test_schema_violation_is_reported_but_values_are_still_read(invoices):
    _, _, truth, xml = next(
        p for p in planted(invoices["e2e_PO-003_invoice_clean"]) if p[0] == "bad-schema"
    )
    [err] = schema_errors(xml)[:1]
    assert "cbc:Remise" in err and "{urn:" not in err  # short, readable
    assert parse_invoice(xml).number.value == truth.number.value


@pytest.mark.parametrize(
    "data,message",
    [
        (b"<Invoice", "not well-formed"),
        (
            (
                b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
                b"<x>&e;</x>"
            ),
            "DOCTYPE is not allowed",
        ),
        (b"<Order xmlns='urn:x'/>", "not a UBL Invoice"),
    ],
)
def test_unreadable_or_hostile_files_are_refused(data, message, tmp_path):
    assert message in schema_errors(data)[0]
    f = tmp_path / "x.xml"
    f.write_bytes(data)
    check = ubl_check(f)
    assert not check.ok and check.code == "UBL_INVALID"
    inv = UblExtractor().extract(f)  # never crashes the run: an empty invoice, all None
    assert inv.number.value is None and inv.lines == []


def test_xml_is_routed_to_the_parser_never_to_a_model(tmp_path, invoices):
    class Boom:
        name = "boom"

        def extract(self, path: Path):
            raise AssertionError("XML must not reach the model")

    f = tmp_path / "inv.xml"
    f.write_bytes(write_invoice(invoices["e2e_PO-004_invoice_clean"]))
    assert (
        Routed(Boom()).extract(f).number.value == invoices["e2e_PO-004_invoice_clean"].number.value
    )
    assert Routed(LabelExtractor()).name == "labels"


def test_file_checks_only_for_xml(tmp_path, invoices):
    good = tmp_path / "a.xml"
    good.write_bytes(write_invoice(invoices["e2e_PO-001_invoice_clean"]))
    assert [c.ok for c in file_checks(good)] == [True]
    assert file_checks(tmp_path / "scan.pdf") == []


@pytest.mark.parametrize(
    "key,codes",
    [
        ("bad-schema", ["UBL_INVALID"]),
        ("bad-total", ["SUM_TTC"]),
        ("bad-buyer", ["CUSTOMER_IS_US"]),
    ],
)
def test_planted_e_invoices_go_to_review_for_their_reason(
    key, codes, invoices, seed, e2e, refs, tmp_path
):
    _, _, _, xml = next(p for p in planted(invoices["e2e_PO-003_invoice_clean"]) if p[0] == key)
    f = tmp_path / f"{key}.xml"
    f.write_bytes(xml)
    ev = evaluate(
        UblExtractor().extract(f),
        e2e["PO-003", "bl"].label,
        make_po(seed, "PO-003"),
        refs,
        CFG,
        [],
        file_checks(f),
    )
    assert ev.decision.action == "review" and ev.decision.codes == codes


def test_xml_is_never_served_as_a_page_image(tmp_path):
    f = tmp_path / "a.xml"
    f.write_bytes(b"<x/>")
    assert pages.page_count(f) == 0
    with pytest.raises(IndexError):
        pages.page_image(f, 1)


def test_case_key_falls_back_to_the_file_name():
    entry = {
        "invoice": {"supplier": {"ice": {"value": None}}, "number": {"value": None}},
        "files": {"invoice": "data\\synthetic\\x\\broken.xml"},
    }
    assert case_key(entry) == "?_broken.xml"
