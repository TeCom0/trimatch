"""Live test against the local Odoo (SPEC 9 items 3-4). Skipped unless TRIMATCH_ODOO_TESTS=1.

Needs: the seeded Odoo running, ODOO_API_KEY in .env, and `trimatch.generate --split e2e`.
It does not reset anything: drafts from an earlier run count as ALREADY_DRAFTED.
"""

import os
from pathlib import Path

import pytest

from trimatch.config import REPO_ROOT
from trimatch.extract import LabelExtractor
from trimatch.odoo_adapter import OdooClient
from trimatch.pipeline import JsonReviewSink, process

pytestmark = [
    pytest.mark.odoo,
    pytest.mark.skipif(os.environ.get("TRIMATCH_ODOO_TESTS") != "1", reason="needs local Odoo"),
]

E2E = REPO_ROOT / "data" / "synthetic" / "e2e"
EXPECTED_REVIEW = {"PO-002": ["QTY_EXCEEDS_RECEIVED"], "PO-004": ["PRICE_OVER_TOLERANCE"]}


def _clean() -> list[Path]:
    files = sorted(E2E.glob("*_clean.pdf"))
    if len(files) != 11:
        pytest.skip("run `python -m trimatch.generate --split e2e` first")
    return files


def test_three_drafts_two_reviews_and_idempotent(tmp_path):
    client = OdooClient.from_env()
    for run in (1, 2):
        results, _ = process(
            _clean(), LabelExtractor(), client, review_sink=JsonReviewSink(tmp_path)
        )
        copy = [r for r in results if r.invoice_file.startswith("e2e_PO-005r_")]
        by_po = {r.po_ref: r for r in results if r not in copy}
        assert set(by_po) == {"PO-001", "PO-002", "PO-003", "PO-004", "PO-005"}
        [c] = copy  # the re-issued PO-005 invoice: never drafted
        assert c.decision.action == "review"
        assert c.decision.codes == ["DUPLICATE_SUSPECTED", "QTY_EXCEEDS_RECEIVED"]
        for po, codes in EXPECTED_REVIEW.items():
            assert by_po[po].decision.action == "review" and by_po[po].decision.codes == codes
        for po in ("PO-001", "PO-003", "PO-005"):
            d = by_po[po].decision
            if run == 2:
                assert d.action == "skip" and d.codes == ["ALREADY_DRAFTED"]
            else:
                assert d.action in ("draft", "skip")
            bills = client.find_bill(client.po_snapshot(po).partner_id, by_po[po].invoice_number)
            assert len(bills) == 1 and bills[0]["state"] == "draft"


def test_dry_run_degraded_copies_decide_like_clean(tmp_path):
    client = OdooClient.from_env()
    degraded = sorted(E2E.glob("*.jpg"))
    results, _ = process(
        degraded, LabelExtractor(), client, dry_run=True, review_sink=JsonReviewSink(tmp_path)
    )
    by_po = {r.po_ref: r.decision for r in results if not r.invoice_file.startswith("e2e_PO-005r")}
    [copy] = [r for r in results if r.invoice_file.startswith("e2e_PO-005r")]
    # caught within the run, or against the draft the test above left in Odoo (then the
    # PO's quantities are billed too, so QTY_EXCEEDS_RECEIVED joins)
    assert copy.decision.action == "review" and "DUPLICATE_SUSPECTED" in copy.decision.codes
    for po, codes in EXPECTED_REVIEW.items():
        assert by_po[po].codes == codes
    assert not list(tmp_path.iterdir())  # dry run writes nothing
