"""Review store (PostgreSQL) and the pipeline's evaluate()/review_entry() that feed it.

Store tests need a disposable database: TRIMATCH_TEST_DB_URL (CI service container), or
locally `trimatch db init --test-db` (database trimatch_review_test). Its public schema is
dropped and rebuilt from the migrations. Without either, they skip.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal as D
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, make_url, select, text

from trimatch.config import load_config
from trimatch.decide import Decision
from trimatch.generate.data import build_split, load_seed_data
from trimatch.match import PoLine, PoSnapshot
from trimatch.pipeline import (
    Extracted,
    JsonReviewSink,
    Result,
    evaluate,
    po_ref_of,
    review_entry,
)
from trimatch.schema import Invoice
from trimatch.store import db as store_db
from trimatch.store.cases import (
    StoreReviewSink,
    import_json_files,
    po_from_json,
    upsert_case,
)
from trimatch.store.models import Base, CaseStatus, ReviewCase
from trimatch.validate import OdooRefs

CFG = load_config()
SUPPLIER_ID = {"alwaha": 11, "anfa": 12, "hygipro": 13}


# --- fixtures: generator ground truth as "extracted" documents ---------------------------


@pytest.fixture(scope="module")
def seed():
    return load_seed_data()


@pytest.fixture(scope="module")
def e2e(seed):
    return {(d.po_ref, d.kind): d for d in build_split("e2e", seed) if d.variant == "clean"}


@pytest.fixture(scope="module")
def refs(seed):
    return OdooRefs(
        company_ice=seed["company"]["ice"],
        suppliers=[
            {"id": SUPPLIER_ID[s["key"]], "name": s["name"], "ice": s["ice"]}
            for s in seed["suppliers"]
        ],
    )


def po_snapshot(seed, name) -> PoSnapshot:
    po = next(p for p in seed["purchase_orders"] if p["name"] == name)
    products = {p["code"]: p for p in seed["products"]}
    return PoSnapshot(
        id=1,
        name=name,
        partner_id=SUPPLIER_ID[po["supplier"]],
        state="purchase",
        lines=[
            PoLine(
                id=100 + i,
                default_code=ln["product"],
                product_name=products[ln["product"]]["name"],
                uom=products[ln["product"]]["uom"],
                qty_ordered=D(str(ln["qty"])),
                qty_received=D(str(ln.get("received", ln["qty"]))),
                qty_invoiced=D(0),
                price_unit=D(str(products[ln["product"]]["price"])),
            )
            for i, ln in enumerate(po["lines"])
        ],
    )


def entry_for(seed, e2e, refs, po_name: str) -> dict:
    inv, bl = e2e[po_name, "invoice"], e2e[po_name, "bl"]
    po = po_snapshot(seed, po_name)
    ev = evaluate(inv.label, bl.label, po, refs, CFG)
    res = Result("inv.pdf", "bl.pdf", "x", inv.label.number.value, po_name, ev.decision, None, None)
    return review_entry(
        res,
        Extracted(Path(f"data/synthetic/e2e/{po_name}_invoice.pdf"), inv.label),
        Extracted(Path(f"data/synthetic/e2e/{po_name}_bl.pdf"), bl.label),
        po,
    )


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
    ev = evaluate(inv, bl, po_snapshot(seed, po_name), refs, CFG)
    assert ev.decision.action == action and ev.decision.codes == codes
    assert ev.partner_id == po_snapshot(seed, po_name).partner_id
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
    assert po_from_json(entry["odoo_po"]) == po_snapshot(seed, "PO-004")
    assert po_from_json(None) is None


def test_json_sink_writes_phase0_file(seed, e2e, refs, tmp_path):
    entry = entry_for(seed, e2e, refs, "PO-002")
    path = Path(JsonReviewSink(tmp_path)(entry))
    assert path.name.endswith(f"_{entry['invoice']['number']['value']}.json")
    assert json.loads(path.read_text(encoding="utf-8")) == entry


def test_upgrade_refuses_odoo_database():
    with pytest.raises(store_db.StoreNotConfigured, match="Odoo"):
        store_db.upgrade(make_url("postgresql+psycopg://u:p@127.0.0.1:1/trimatch"))


# --- store (needs PostgreSQL) -------------------------------------------------------------


def _test_db_url():
    if raw := os.environ.get("TRIMATCH_TEST_DB_URL"):
        return make_url(raw)
    try:
        return store_db.database_url("trimatch_review_test")
    except store_db.StoreNotConfigured:
        return None


@pytest.fixture(scope="module")
def sessions():
    url = _test_db_url()
    if url is None:
        pytest.skip("no test database (TRIMATCH_TEST_DB_URL or `trimatch db init --test-db`)")
    eng = store_db.engine(url)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    except Exception as exc:  # noqa: BLE001 (any connection failure means: no database here)
        pytest.skip(f"test database not reachable: {exc}")
    store_db.upgrade(url)
    return store_db.session_factory(url)


@pytest.fixture
def s(sessions):
    with sessions.begin() as session:
        session.execute(text("TRUNCATE review_case RESTART IDENTITY CASCADE"))
    with sessions() as session:
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
    assert case.invoice_file.endswith("PO-004_invoice.pdf")
    assert po_from_json(case.odoo_po) == po_snapshot(seed, "PO-004")


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


def test_store_sink_and_json_import_agree(sessions, s, seed, e2e, refs, tmp_path):
    entry = entry_for(seed, e2e, refs, "PO-004")
    msg = StoreReviewSink(sessions)(entry)
    assert msg.startswith("review case #1 (created)")
    path = Path(JsonReviewSink(tmp_path)(entry))
    [(f, r)] = import_json_files(s, [path])
    assert (f, r.case_id, r.outcome) == (path, 1, "updated")
    assert s.scalar(select(func.count()).select_from(ReviewCase)) == 1


def test_decision_type_unchanged():
    # The CLI and the API both read Decision.codes; keep it sorted and unique.
    from trimatch.checks import Check

    d = Decision("review", [Check("B", False), Check("A", False), Check("B", False)])
    assert d.codes == ["A", "B"]
