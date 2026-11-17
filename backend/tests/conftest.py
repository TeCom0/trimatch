"""Shared fixtures: generator ground truth as 'extracted' documents, the PO snapshots Odoo
would return for the seeded POs, and a disposable PostgreSQL review store.

Store fixtures need TRIMATCH_TEST_DB_URL (CI service container) or, locally, the database
from `trimatch db init --test-db`. Its public schema is dropped and rebuilt from the
migrations. Without either, tests that use them skip.
"""

from __future__ import annotations

import os
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import make_url, text

from trimatch.config import load_config
from trimatch.generate.data import build_split, load_seed_data
from trimatch.match import PoLine, PoSnapshot
from trimatch.pipeline import Extracted, Result, evaluate, review_entry
from trimatch.schema import DeliveryNote, Invoice
from trimatch.store import db as store_db
from trimatch.validate import OdooRefs

CFG = load_config()
SUPPLIER_ID = {"alwaha": 11, "anfa": 12, "hygipro": 13}


@pytest.fixture(scope="session")
def seed():
    return load_seed_data()


@pytest.fixture(scope="session")
def e2e(seed):
    return {
        (d.po_ref, d.kind): d
        for d in build_split("e2e", seed)
        if d.variant == "clean" and d.scenario != "duplicate_invoice"
    }


@pytest.fixture(scope="session")
def refs(seed):
    return OdooRefs(
        company_ice=seed["company"]["ice"],
        suppliers=[
            {"id": SUPPLIER_ID[s["key"]], "name": s["name"], "ice": s["ice"]}
            for s in seed["suppliers"]
        ],
    )


def make_po(seed, name: str) -> PoSnapshot:
    """What Odoo holds for a seeded PO: PO prices, received quantities, nothing billed."""
    po = next(p for p in seed["purchase_orders"] if p["name"] == name)
    products = {p["code"]: p for p in seed["products"]}
    return PoSnapshot(
        id=int(name.split("-")[1]),
        name=name,
        partner_id=SUPPLIER_ID[po["supplier"]],
        state="purchase",
        lines=[
            PoLine(
                id=100 * int(name.split("-")[1]) + i,
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


def make_entry(
    seed,
    refs,
    po_name: str,
    inv: Invoice,
    bl: DeliveryNote | None,
    inv_path: Path | str | None = None,
    bl_path: Path | str | None = None,
) -> dict:
    """A review entry exactly as `trimatch process` would store it."""
    po = make_po(seed, po_name)
    ev = evaluate(inv, bl, po, refs, CFG)
    res = Result("inv", "bl", "x", inv.number.value, po_name, ev.decision)
    return review_entry(
        res,
        Extracted(Path(inv_path or f"data/synthetic/e2e/{po_name}_invoice.pdf"), inv),
        Extracted(Path(bl_path or f"data/synthetic/e2e/{po_name}_bl.pdf"), bl) if bl else None,
        po,
    )


def _test_db_url():
    if raw := os.environ.get("TRIMATCH_TEST_DB_URL"):
        return make_url(raw)
    try:
        return store_db.database_url("trimatch_review_test")
    except store_db.StoreNotConfigured:
        return None


@pytest.fixture(scope="session")
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
def clean_db(sessions):
    with sessions.begin() as session:
        session.execute(text("TRUNCATE review_case RESTART IDENTITY CASCADE"))
    return sessions
