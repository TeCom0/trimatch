"""DUPLICATE_SUSPECTED: a re-issued invoice under a new number (plan-phase1-duplicate-invoice)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import CFG, make_entry, make_po
from fastapi.testclient import TestClient
from test_api import FakeOdoo

from trimatch.api import app as api_app
from trimatch.duplicates import KnownInvoice, duplicate_check, known_from, matches
from trimatch.pipeline import evaluate, process
from trimatch.schema import Invoice
from trimatch.store.cases import known_cases, upsert_case
from trimatch.store.models import CaseStatus, ReviewCase


def reissued(inv: Invoice, number: str = "FA-HP-2026-9999") -> Invoice:
    return inv.model_copy(update={"number": inv.number.model_copy(update={"value": number})})


@pytest.fixture
def inv5(e2e):
    return e2e["PO-005", "invoice"].label


# --- the rule ------------------------------------------------------------------------------


def test_same_supplier_total_and_date_under_another_number(inv5):
    k = known_from(inv5, "Odoo bill BILL/1")
    assert matches(reissued(inv5), k)
    c = duplicate_check(reissued(inv5), [k])
    assert not c.ok and "Odoo bill BILL/1" in c.detail and inv5.number.value in c.detail


def test_same_number_is_not_a_duplicate_here(inv5):
    # same invoice number = the same invoice: ALREADY_DRAFTED handles it before matching
    assert not matches(inv5, known_from(inv5, "x"))


@pytest.mark.parametrize(
    "change",
    [
        {"total_ttc": Decimal("0.02")},
        {"invoice_date": timedelta(days=1)},
        {"supplier_ice": "999999999999999"},
    ],
)
def test_any_difference_means_not_a_duplicate(inv5, change):
    k = known_from(inv5, "x")
    field, delta = next(iter(change.items()))
    value = delta if field == "supplier_ice" else getattr(k, field) + delta
    k = KnownInvoice(**{**k.__dict__, field: value})
    assert duplicate_check(reissued(inv5), [k]).ok


def test_total_within_one_centime_still_matches(inv5):
    k = known_from(inv5, "x")
    k = KnownInvoice(**{**k.__dict__, "total_ttc": k.total_ttc + Decimal("0.01")})
    assert matches(reissued(inv5), k)


def test_missing_values_are_not_compared(inv5):
    blank = inv5.total_ttc.model_copy(update={"value": None})
    copy = reissued(inv5).model_copy(update={"total_ttc": blank})
    assert not matches(copy, known_from(inv5, "x"))


def test_evaluate_blocks_the_copy(seed, e2e, refs, inv5):
    ev = evaluate(
        reissued(inv5),
        e2e["PO-005", "bl"].label,
        make_po(seed, "PO-005"),
        refs,
        CFG,
        [known_from(inv5, "Odoo bill BILL/1")],
    )
    assert ev.decision.action == "review" and ev.decision.codes == ["DUPLICATE_SUSPECTED"]


# --- the pipeline: same run, Odoo, order ----------------------------------------------------


class DictExtractor:
    def __init__(self, docs: dict[str, object]):
        self.docs = docs

    def extract(self, path: Path):
        return self.docs[path.name]


def test_same_run_flags_the_later_copy_even_in_a_dry_run(seed, refs, e2e, inv5):
    copy = reissued(inv5)  # same date: the file name decides which one came first
    docs = {
        "a_original.pdf": inv5,
        "b_copy.pdf": copy,
        "bl.pdf": e2e["PO-005", "bl"].label,
    }
    results, _ = process(
        [Path(n) for n in docs], DictExtractor(docs), FakeOdoo(seed, refs), dry_run=True
    )
    by = {r.invoice_file: r.decision for r in results}
    assert by["a_original.pdf"].action == "draft"
    assert by["b_copy.pdf"].codes == ["DUPLICATE_SUSPECTED"]
    assert "a_original.pdf earlier in this run" in by["b_copy.pdf"].reasons[0].detail


def test_copy_of_a_bill_already_in_odoo(seed, refs, e2e, inv5, tmp_path):
    from trimatch.pipeline import JsonReviewSink

    odoo = FakeOdoo(seed, refs)
    po = make_po(seed, "PO-005")
    odoo.create_draft_bill(po, inv5, [])
    docs = {"copy.pdf": reissued(inv5), "bl.pdf": e2e["PO-005", "bl"].label}
    results, _ = process(
        [Path(n) for n in docs], DictExtractor(docs), odoo, review_sink=JsonReviewSink(tmp_path)
    )
    [r] = results
    assert "DUPLICATE_SUSPECTED" in r.decision.codes
    assert "Odoo bill #500" in next(c.detail for c in r.decision.reasons if not c.ok)
    assert len(odoo.live_bills) == 1  # no second bill


# --- the store and the review screen --------------------------------------------------------


def test_store_cases_count_unless_rejected_or_itself(clean_db, seed, refs, e2e, inv5):
    bl = e2e["PO-005", "bl"].label
    with clean_db.begin() as s:
        first = upsert_case(s, make_entry(seed, refs, "PO-005", inv5, bl)).case_id
        assert [k.where for k in known_cases(s, reissued(inv5))] == [f"review case #{first} (open)"]
        assert known_cases(s, reissued(inv5), exclude_case_id=first) == []
        s.get(ReviewCase, first).status = CaseStatus.rejected
        s.flush()
        assert known_cases(s, reissued(inv5)) == []


def test_review_screen_blocks_a_copy_of_an_open_case(clean_db, seed, refs, e2e, inv5):
    bl = e2e["PO-005", "bl"].label
    with clean_db.begin() as s:
        upsert_case(s, make_entry(seed, refs, "PO-005", inv5, bl))
        copy_id = upsert_case(s, make_entry(seed, refs, "PO-005", reissued(inv5), bl)).case_id
    odoo = FakeOdoo(seed, refs)
    app = api_app.create_app(
        sessions=clean_db, odoo=lambda: odoo, reviewer="R", cfg=CFG, frontend_dist=None
    )
    client = TestClient(app)
    r = client.post(f"/api/reviews/{copy_id}/recheck", json={}).json()
    assert r["blocking"] == ["DUPLICATE_SUSPECTED"] and not r["can_approve"]
    dup = r["failed"][0]
    assert dup["title"] == "Possible double billing" and "review case #1 (open)" in dup["detail"]
    a = client.post(f"/api/reviews/{copy_id}/approve", json={"reason": "x" * 20})
    assert a.status_code == 422 and odoo.bills == []
