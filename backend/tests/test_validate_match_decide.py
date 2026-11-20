"""Every reason code of validate.py, match.py and decide.py, on generator ground truth.

Pure Python: no Odoo. The PO snapshot is built from the same data the seed puts in Odoo.
"""

from decimal import Decimal as D

import pytest

from trimatch.config import load_config
from trimatch.decide import confidence_check, decide
from trimatch.generate.data import build_split, load_seed_data
from trimatch.match import PoLine, PoSnapshot, match_order
from trimatch.validate import OdooRefs, validate_bl, validate_invoice

CFG = load_config()
SUPPLIER_ID = {"alwaha": 11, "anfa": 12, "hygipro": 13}


@pytest.fixture(scope="module")
def seed():
    return load_seed_data()


@pytest.fixture(scope="module")
def e2e(seed):
    return {
        (d.po_ref, d.kind): d.label
        for d in build_split("e2e", seed)
        if d.variant == "clean" and d.scenario != "duplicate_invoice"
    }


@pytest.fixture(scope="module")
def refs(seed):
    return OdooRefs(
        company_ice=seed["company"]["ice"],
        suppliers=[
            {"id": SUPPLIER_ID[s["key"]], "name": s["name"], "ice": s["ice"]}
            for s in seed["suppliers"]
        ],
    )


def po_snapshot(seed, name, *, billed=None):
    """What Odoo holds for a seeded PO: PO price, received qty per the seed."""
    po = next(p for p in seed["purchase_orders"] if p["name"] == name)
    products = {p["code"]: p for p in seed["products"]}
    lines = []
    for i, ln in enumerate(po["lines"]):
        p = products[ln["product"]]
        lines.append(
            PoLine(
                id=100 + i,
                default_code=p["code"],
                product_name=p["name"],
                uom=p["uom"],
                qty_ordered=D(str(ln["qty"])),
                qty_received=D(str(ln.get("received", ln["qty"]))),
                qty_invoiced=D(str((billed or {}).get(p["code"], 0))),
                price_unit=D(str(p["price"])),
            )
        )
    return PoSnapshot(
        id=1, name=name, partner_id=SUPPLIER_ID[po["supplier"]], state="purchase", lines=lines
    )


def codes_failed(checks):
    return sorted({c.code for c in checks if not c.ok})


def run(seed, e2e, refs, po_name, *, inv=None, bl="default", po="default", partner=None):
    inv = inv or e2e[po_name, "invoice"]
    bl = e2e[po_name, "bl"] if bl == "default" else bl
    po = po_snapshot(seed, po_name) if po == "default" else po
    partner = partner or (po.partner_id if po else None)
    checks = validate_invoice(inv, refs, CFG) + (validate_bl(bl, refs) if bl else [])
    checks += match_order(inv, bl, po, partner, CFG)[0]
    checks.append(confidence_check(inv, CFG, "invoice"))
    return checks


# --- the five e2e scenarios -------------------------------------------------------------


@pytest.mark.parametrize(
    "po,expected",
    [
        ("PO-001", []),
        ("PO-003", []),
        ("PO-005", []),
        ("PO-002", ["QTY_EXCEEDS_RECEIVED"]),
        ("PO-004", ["PRICE_OVER_TOLERANCE"]),
    ],
)
def test_e2e_scenarios(seed, e2e, refs, po, expected):
    checks = run(seed, e2e, refs, po)
    assert codes_failed(checks) == expected
    assert decide(checks).action == ("draft" if not expected else "review")


# --- validation -------------------------------------------------------------------------


def tampered(e2e, po, fn):
    inv = e2e[po, "invoice"].model_copy(deep=True)
    fn(inv)
    return inv


def test_line_math(seed, e2e, refs):
    inv = tampered(e2e, "PO-001", lambda i: setattr(i.lines[0].line_total_ht, "value", D("1.00")))
    assert "LINE_MATH" in codes_failed(run(seed, e2e, refs, "PO-001", inv=inv))


def test_sum_ht_and_vat_math(seed, e2e, refs):
    inv = tampered(e2e, "PO-005", lambda i: setattr(i.total_ht, "value", D("9999.00")))
    failed = codes_failed(run(seed, e2e, refs, "PO-005", inv=inv))
    assert "SUM_HT" in failed and "VAT_MATH" in failed


def test_vat_amount_wrong(seed, e2e, refs):
    inv = tampered(e2e, "PO-005", lambda i: setattr(i.vat[-1].amount, "value", D("300.00")))
    failed = codes_failed(run(seed, e2e, refs, "PO-005", inv=inv))
    assert "VAT_MATH" in failed and "SUM_TTC" in failed


def test_obsolete_rate(seed, e2e, refs):
    def to7(i):
        i.lines[1].vat_rate.value = D(7)

    inv = tampered(e2e, "PO-005", to7)
    assert "VAT_RATE_KNOWN" in codes_failed(run(seed, e2e, refs, "PO-005", inv=inv))


def test_ttc(seed, e2e, refs):
    inv = tampered(e2e, "PO-003", lambda i: setattr(i.total_ttc, "value", D("1.00")))
    assert codes_failed(run(seed, e2e, refs, "PO-003", inv=inv)) == ["SUM_TTC"]


def test_ice_supplier_customer(seed, e2e, refs):
    inv = tampered(e2e, "PO-003", lambda i: setattr(i.supplier.ice, "value", "999639125000125"))
    failed = codes_failed(run(seed, e2e, refs, "PO-003", inv=inv))
    assert {"ICE_FORMAT", "SUPPLIER_KNOWN"} <= set(failed)
    inv = tampered(e2e, "PO-003", lambda i: setattr(i.customer.ice, "value", "999528614000104"))
    assert "CUSTOMER_IS_US" in codes_failed(run(seed, e2e, refs, "PO-003", inv=inv))


def test_required_present(seed, e2e, refs):
    inv = tampered(e2e, "PO-003", lambda i: setattr(i.number, "value", None))
    assert "REQUIRED_PRESENT" in codes_failed(run(seed, e2e, refs, "PO-003", inv=inv))


# --- matching ---------------------------------------------------------------------------


def test_po_not_found(seed, e2e, refs):
    assert codes_failed(run(seed, e2e, refs, "PO-001", po=None)) == ["PO_NOT_FOUND"]


def test_po_of_other_supplier(seed, e2e, refs):
    failed = codes_failed(run(seed, e2e, refs, "PO-001", partner=SUPPLIER_ID["anfa"]))
    assert "PO_SUPPLIER_MISMATCH" in failed


def test_bl_missing(seed, e2e, refs):
    assert codes_failed(run(seed, e2e, refs, "PO-001", bl=None)) == ["BL_MISSING"]


def test_already_billed_counts(seed, e2e, refs):
    po = po_snapshot(seed, "PO-001", billed={"BMW-PL01": 40})
    assert codes_failed(run(seed, e2e, refs, "PO-001", po=po)) == ["QTY_EXCEEDS_RECEIVED"]


def test_kg_tolerance_two_percent(seed, e2e, refs):
    # 40 kg received; invoice 40.5 kg (+1.25%) passes, 41 kg (+2.5%) does not.
    for qty, ok in ((D("40.5"), True), (D(41), False)):

        def bump(i, qty=qty):
            ln = i.lines[1]
            ln.quantity.value = qty
            ln.line_total_ht.value = (qty * ln.unit_price_ht.value).quantize(D("0.01"))

        inv = tampered(e2e, "PO-001", bump)
        checks = match_order(
            inv, e2e["PO-001", "bl"], po_snapshot(seed, "PO-001"), SUPPLIER_ID["alwaha"], CFG
        )[0]
        assert ("QTY_EXCEEDS_RECEIVED" in codes_failed(checks)) is not ok


def test_countable_has_no_tolerance(seed, e2e, refs):
    def bump(i):
        ln = i.lines[0]  # ANF-EM15, 50 packs
        ln.quantity.value = D(51)

    inv = tampered(e2e, "PO-003", bump)
    checks = match_order(
        inv, e2e["PO-003", "bl"], po_snapshot(seed, "PO-003"), SUPPLIER_ID["anfa"], CFG
    )[0]
    assert "QTY_EXCEEDS_RECEIVED" in codes_failed(checks)


def test_bl_disagrees_with_receipt(seed, e2e, refs):
    bl = e2e["PO-003", "bl"].model_copy(deep=True)
    bl.lines[2].quantity.value = D(6)
    assert codes_failed(run(seed, e2e, refs, "PO-003", bl=bl)) == ["QTY_BL_MISMATCH"]


def test_price_tolerance_one_percent(seed, e2e, refs):
    for price, ok in ((D("92.80"), True), (D("93.20"), False)):  # +0.87%, +1.30% over 92.00

        def set_price(i, price=price):
            ln = next(x for x in i.lines if x.supplier_ref.value == "ANF-HT05")
            ln.unit_price_ht.value = price

        inv = tampered(e2e, "PO-003", set_price)
        checks = match_order(
            inv, e2e["PO-003", "bl"], po_snapshot(seed, "PO-003"), SUPPLIER_ID["anfa"], CFG
        )[0]
        assert ("PRICE_OVER_TOLERANCE" in codes_failed(checks)) is not ok


def test_line_not_on_po(seed, e2e, refs):
    def foreign(i):
        i.lines[0].supplier_ref.value = "XXX-999"
        i.lines[0].description.value = "Huile d'olive extra vierge"

    inv = tampered(e2e, "PO-003", foreign)
    assert "LINE_UNMATCHED" in codes_failed(run(seed, e2e, refs, "PO-003", inv=inv))


def test_pairs_by_description_when_ref_missing(seed, e2e, refs):
    def drop_refs(i):
        for ln in i.lines:
            ln.supplier_ref = None

    inv = tampered(e2e, "PO-005", drop_refs)
    checks, pairs = match_order(
        inv, e2e["PO-005", "bl"], po_snapshot(seed, "PO-005"), SUPPLIER_ID["hygipro"], CFG
    )
    assert codes_failed(checks) == [] and len(pairs) == 5


# --- decision ---------------------------------------------------------------------------


def test_low_confidence_goes_to_review(seed, e2e, refs):
    inv = tampered(e2e, "PO-001", lambda i: setattr(i.lines[0].quantity, "confidence", 0.6))
    checks = run(seed, e2e, refs, "PO-001", inv=inv)
    d = decide(checks)
    assert d.action == "review" and d.codes == ["LOW_CONFIDENCE"]


def test_unread_values_go_to_review_without_crashing_the_match(seed, e2e, refs):
    inv = e2e["PO-002", "invoice"]
    lines = [ln.model_copy(deep=True) for ln in inv.lines]
    lines[0].quantity.value = None
    lines[1].unit_price_ht.value = None
    bl = e2e["PO-002", "bl"]
    bl_lines = [ln.model_copy(deep=True) for ln in bl.lines]
    bl_lines[0].quantity.value = None
    checks = run(
        seed,
        e2e,
        refs,
        "PO-002",
        inv=inv.model_copy(update={"lines": lines}),
        bl=bl.model_copy(update={"lines": bl_lines}),
    )
    assert "REQUIRED_PRESENT" in codes_failed(checks)
    assert decide(checks).action == "review"
