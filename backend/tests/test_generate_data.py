from decimal import Decimal as D

import pytest
from stdnum.ma import ice

from trimatch.generate.data import build_split, load_seed_data
from trimatch.money import line_total, totals
from trimatch.schema import Invoice


@pytest.fixture(scope="module")
def data():
    return load_seed_data()


def _invoices(docs):
    seen, out = set(), []
    for d in docs:
        if d.kind == "invoice" and id(d.label) not in seen:
            seen.add(id(d.label))
            out.append(d)
    return out


@pytest.mark.parametrize("split", ["e2e", "dev", "test"])
def test_invoice_totals_are_consistent(split, data):
    for d in _invoices(build_split(split, data)):
        inv: Invoice = d.label
        for ln in inv.lines:
            assert ln.line_total_ht.value == line_total(ln.quantity.value, ln.unit_price_ht.value)
            assert (ln.exemption_ref is not None) == (ln.vat_rate.value == 0)
        ht, vat, ttc = totals((ln.vat_rate.value, ln.line_total_ht.value) for ln in inv.lines)
        assert inv.total_ht.value == ht
        assert [(v.rate.value, v.base_ht.value, v.amount.value) for v in inv.vat] == vat
        assert inv.total_ttc.value == ttc


def test_all_ices_valid(data):
    for party in [data["company"], *data["suppliers"]]:
        assert ice.is_valid(party["ice"]), party["name"]


def test_vat_rates_are_2026_rates(data):
    assert {p["vat"] for p in data["products"]} <= {0, 10, 20}


def test_e2e_scenarios_match_spec(data):
    docs = {
        (d.po_ref, d.kind): d.label
        for d in build_split("e2e", data)
        if d.variant == "clean" and d.scenario != "duplicate_invoice"
    }
    assert len(docs) == 10

    # PO-002: BL shows 14 kg merlan (received), invoice bills the ordered 20 kg.
    bl2 = {ln.supplier_ref.value: ln.quantity.value for ln in docs["PO-002", "bl"].lines}
    inv2 = {ln.supplier_ref.value: ln.quantity.value for ln in docs["PO-002", "invoice"].lines}
    assert bl2["BMW-ME01"] == D(14) and inv2["BMW-ME01"] == D(20)

    # PO-004: ANF-HT05 billed +8% over the PO price (92.00 -> 99.36); others at PO price.
    prices = {
        ln.supplier_ref.value: ln.unit_price_ht.value for ln in docs["PO-004", "invoice"].lines
    }
    assert prices["ANF-HT05"] == D("99.36")
    assert prices["ANF-EM15"] == D("21.00")

    # Clean POs: BL qty == invoice qty == ordered.
    for po in ("PO-001", "PO-003", "PO-005"):
        bl = [ln.quantity.value for ln in docs[po, "bl"].lines]
        inv = [ln.quantity.value for ln in docs[po, "invoice"].lines]
        assert bl == inv


def test_e2e_each_doc_has_clean_and_one_degraded(data):
    docs = build_split("e2e", data)
    assert len(docs) == 22  # 5 POs x (BL + invoice) x 2, plus PO-005's re-issued invoice x 2
    assert sum(d.variant == "clean" for d in docs) == 11
    assert {d.variant for d in docs if d.variant != "clean"} == {
        "rot",
        "blur",
        "stamp",
        "handwriting",
    }


def test_reissued_invoice_is_the_same_invoice_under_a_new_number(data):
    docs = build_split("e2e", data)
    [orig] = [d for d in docs if d.doc_id == "e2e_PO-005_invoice_clean"]
    [copy] = [d for d in docs if d.doc_id == "e2e_PO-005r_invoice_clean"]
    assert copy.scenario == "duplicate_invoice" and copy.ctx["duplicata"]
    assert copy.label.number.value != orig.label.number.value
    same = orig.label.model_copy(update={"number": copy.label.number})
    assert copy.label == same  # lines, totals, date, BL ref, parties: identical
    assert not any(d.doc_id.startswith("e2e_PO-005r_bl") for d in docs)


@pytest.mark.parametrize("split", ["e2e", "dev"])
def test_same_seed_same_data(split, data):
    a = [d.label.model_dump_json() for d in build_split(split, data)]
    b = [d.label.model_dump_json() for d in build_split(split, data)]
    assert a == b


def test_dev_and_test_differ(data):
    dev = {d.label.number.value for d in build_split("dev", data)}
    test = {d.label.number.value for d in build_split("test", data)}
    assert dev != test
    assert len(build_split("dev", data)) == 200
