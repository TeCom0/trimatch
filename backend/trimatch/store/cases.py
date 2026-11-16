"""Writing review cases: from the pipeline (StoreReviewSink) and from Phase 0 JSON files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trimatch.match import PoLine, PoSnapshot
from trimatch.schema import DeliveryNote, Invoice
from trimatch.store.models import CaseStatus, ReviewCase


def _value(doc: dict, *path: str) -> str | None:
    node = doc
    for key in path:
        node = (node or {}).get(key)
    return node.get("value") if isinstance(node, dict) else None


def case_key(entry: dict) -> str:
    inv = entry["invoice"]
    return f"{_value(inv, 'supplier', 'ice') or '?'}_{_value(inv, 'number') or '?'}"


@dataclass
class UpsertResult:
    case_id: int
    outcome: str  # "created" | "updated" | "kept" (case already decided; left untouched)


def upsert_case(session: Session, entry: dict) -> UpsertResult:
    """Insert a review case, or refresh an open one with the same supplier + invoice number.

    A case already approved or rejected is never reopened or overwritten by a new run.
    """
    # Validate before storing: the screen must be able to load what we store.
    Invoice.model_validate(entry["invoice"])
    if entry.get("bl"):
        DeliveryNote.model_validate(entry["bl"])
    key = case_key(entry)
    case = session.scalars(
        select(ReviewCase).where(ReviewCase.case_key == key).with_for_update()
    ).one_or_none()
    if case is not None and case.status != CaseStatus.open:
        return UpsertResult(case.id, "kept")
    outcome = "updated" if case else "created"
    if case is None:
        case = ReviewCase(case_key=key)
        session.add(case)
    inv = entry["invoice"]
    case.supplier_ice = _value(inv, "supplier", "ice")
    case.supplier_name = _value(inv, "supplier", "name")
    case.invoice_number = _value(inv, "number")
    case.po_ref = _value(inv, "po_ref") or (
        _value(entry["bl"], "po_ref") if entry.get("bl") else None
    )
    case.reason_codes = list(entry["reason_codes"])
    case.reasons = list(entry["reasons"])
    case.invoice = inv
    case.bl = entry.get("bl")
    case.odoo_po = entry.get("odoo_po")
    case.invoice_file = entry["files"]["invoice"]
    case.bl_file = entry["files"].get("bl")
    session.flush()
    return UpsertResult(case.id, outcome)


class StoreReviewSink:
    """Pipeline review sink that writes to the store (one transaction per case)."""

    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def __call__(self, entry: dict) -> str:
        with self.sessions.begin() as s:
            r = upsert_case(s, entry)
        return f"review case #{r.case_id} ({r.outcome})"


def import_json_files(session: Session, files: list[Path]) -> list[tuple[Path, UpsertResult]]:
    return [(f, upsert_case(session, json.loads(f.read_text(encoding="utf-8")))) for f in files]


def po_from_json(data: dict | None) -> PoSnapshot | None:
    """Inverse of dataclasses.asdict(PoSnapshot) after JSON (Decimals arrive as strings)."""
    if not data:
        return None
    dec = ("qty_ordered", "qty_received", "qty_invoiced", "price_unit")
    lines = [
        PoLine(**{k: (Decimal(str(v)) if k in dec else v) for k, v in ln.items()})
        for ln in data["lines"]
    ]
    return PoSnapshot(**{**data, "lines": lines})
