"""Review store (PostgreSQL) and the pipeline's evaluate()/review_entry() that feed it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import CFG, make_entry, make_po
from sqlalchemy import func, make_url, select

from trimatch.checks import Check
from trimatch.decide import Decision
from trimatch.pipeline import JsonReviewSink, evaluate, po_ref_of
from trimatch.schema import Invoice
from trimatch.store import db as store_db
from trimatch.store.cases import (
    StoreReviewSink,
    import_json_files,
    po_from_json,
    upsert_case,
)
from trimatch.store.models import Base, CaseStatus, ReviewCase


def entry_for(seed, e2e, refs, po_name: str) -> dict:
    return make_entry(seed, refs, po_name, e2e[po_name, "invoice"].label, e2e[po_name, "bl"].label)


# --- pure: evaluate() is the single decision path ----------------------------------------


@pytest.mark.parametrize(
    "po_name,action,codes",
    [
        ("PO-001", "draft", []),
        ("PO-002", "review", ["QTY_EXCEEDS_RECEIVED"]),
        ("PO-003", "draft", []),
        ("PO-004", "review", ["PRICE_OVER_TOLERANCE"]),
        ("PO-005", "draft", []),
    ],
)
def test_evaluate_e2e_scenarios(seed, e2e, refs, po_name, action, codes):
    inv, bl = e2e[po_name, "invoice"].label, e2e[po_name, "bl"].label
    ev = evaluate(inv, bl, make_po(seed, po_name), refs, CFG)
    assert ev.decision.action == action and ev.decision.codes == codes
    assert ev.partner_id == make_po(seed, po_name).partner_id
    assert len(ev.pairs) == len(inv.lines)


def test_po_ref_falls_back_to_bl(e2e):
    inv = e2e["PO-001", "invoice"].label.model_copy(update={"po_ref": None})
    assert po_ref_of(inv, e2e["PO-001", "bl"].label) == "PO-001"
    assert po_ref_of(inv, None) is None


def test_review_entry_round_trips(seed, e2e, refs):
    entry = entry_for(seed, e2e, refs, "PO-004")
    json.dumps(entry)  # plain JSON, no Decimals
    assert entry["reason_codes"] == ["PRICE_OVER_TOLERANCE"]
    assert Invoice.model_validate(entry["invoice"]) == e2e["PO-004", "invoice"].label
    assert po_from_json(entry["odoo_po"]) == make_po(seed, "PO-004")
    assert po_from_json(None) is None


def test_json_sink_writes_phase0_file(seed, e2e, refs, tmp_path):
    entry = entry_for(seed, e2e, refs, "PO-002")
    path = Path(JsonReviewSink(tmp_path)(entry))
    assert path.name.endswith(f"_{entry['invoice']['number']['value']}.json")
    assert json.loads(path.read_text(encoding="utf-8")) == entry


def test_upgrade_refuses_odoo_database():
    with pytest.raises(store_db.StoreNotConfigured, match="Odoo"):
        store_db.upgrade(make_url("postgresql+psycopg://u:p@127.0.0.1:1/trimatch"))


def test_decision_codes_sorted_and_unique():
    d = Decision("review", [Check("B", False), Check("A", False), Check("B", False)])
    assert d.codes == ["A", "B"]


# --- store (needs PostgreSQL) -------------------------------------------------------------


@pytest.fixture
def s(clean_db):
    with clean_db() as session:
        yield session
        session.rollback()


def test_migrations_match_models(sessions):
    with sessions() as session:
        ctx = MigrationContext.configure(session.connection())
        assert compare_metadata(ctx, Base.metadata) == []


def test_upsert_creates_then_refreshes_open_case(s, seed, e2e, refs):
    entry = entry_for(seed, e2e, refs, "PO-004")
    first = upsert_case(s, entry)
    assert first.outcome == "created"
    entry["reason_codes"] = ["PRICE_OVER_TOLERANCE", "LOW_CONFIDENCE"]
    second = upsert_case(s, entry)
    assert (second.case_id, second.outcome) == (first.case_id, "updated")
    case = s.get(ReviewCase, first.case_id)
    assert case.status == CaseStatus.open
    assert case.reason_codes == ["PRICE_OVER_TOLERANCE", "LOW_CONFIDENCE"]
    assert case.po_ref == "PO-004" and case.supplier_name == "Distribution Anfa SARL"
    assert case.invoice_file.replace("\\", "/").endswith("PO-004_invoice.pdf")
    assert po_from_json(case.odoo_po) == make_po(seed, "PO-004")


def test_decided_case_is_never_reopened(s, seed, e2e, refs):
    entry = entry_for(seed, e2e, refs, "PO-002")
    r = upsert_case(s, entry)
    s.get(ReviewCase, r.case_id).status = CaseStatus.rejected
    s.flush()
    again = upsert_case(s, entry)
    assert (again.case_id, again.outcome) == (r.case_id, "kept")
    assert s.get(ReviewCase, r.case_id).status == CaseStatus.rejected


def test_invalid_entry_is_refused(s, seed, e2e, refs):
    entry = entry_for(seed, e2e, refs, "PO-002")
    entry["invoice"]["lines"][0]["quantity"]["value"] = "not a number"
    with pytest.raises(ValueError):
        upsert_case(s, entry)
    assert s.scalar(select(func.count()).select_from(ReviewCase)) == 0


def test_store_sink_and_json_import_agree(clean_db, s, seed, e2e, refs, tmp_path):
    entry = entry_for(seed, e2e, refs, "PO-004")
    msg = StoreReviewSink(clean_db)(entry)
    assert msg.startswith("review case #1 (created)")
    path = Path(JsonReviewSink(tmp_path)(entry))
    [(f, r)] = import_json_files(s, [path])
    assert (f, r.case_id, r.outcome) == (path, 1, "updated")
    assert s.scalar(select(func.count()).select_from(ReviewCase)) == 1
