"""Three-way match: invoice <-> PO (Odoo) <-> BL (SPEC section 7). Pure Python.

The PO snapshot comes from the Odoo adapter. Quantities are compared against what is
still billable on the PO line: qty_received - qty_invoiced. Slice assumption: one BL per
PO, so the BL quantity is compared with the line's total received quantity.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz

from trimatch.checks import Check
from trimatch.config import MatchConfig
from trimatch.schema import DeliveryNote, Invoice, Line


@dataclass(frozen=True)
class PoLine:
    id: int
    default_code: str | None
    product_name: str
    uom: str
    qty_ordered: Decimal
    qty_received: Decimal
    qty_invoiced: Decimal
    price_unit: Decimal


@dataclass(frozen=True)
class PoSnapshot:
    id: int
    name: str
    partner_id: int
    state: str
    lines: list[PoLine]


@dataclass(frozen=True)
class LinePair:
    invoice_line: int  # index on the invoice
    po_line: PoLine
    bl_line: int | None  # index on the BL


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def pair_lines(
    doc_lines: list[Line], po_lines: list[PoLine], min_score: float
) -> dict[int, PoLine]:
    """Document line index -> PO line, one-to-one. Supplier ref first, then fuzzy description."""
    result: dict[int, PoLine] = {}
    free = list(po_lines)
    by_code = {pl.default_code: pl for pl in po_lines if pl.default_code}
    for i, ln in enumerate(doc_lines):
        ref = ln.supplier_ref.value if ln.supplier_ref else None
        if ref and ref in by_code and by_code[ref] in free:
            result[i] = by_code[ref]
            free.remove(by_code[ref])
    candidates = []
    for i, ln in enumerate(doc_lines):
        if i in result or not ln.description.value:
            continue
        for pl in free:
            score = fuzz.token_sort_ratio(_norm(ln.description.value), _norm(pl.product_name))
            if score >= min_score:
                candidates.append((score, i, pl))
    for _score, i, pl in sorted(candidates, key=lambda c: -c[0]):
        if i not in result and pl in free:
            result[i] = pl
            free.remove(pl)
    return result


def _qty_tol(pl: PoLine, qty: Decimal, cfg: MatchConfig) -> Decimal:
    if pl.uom in cfg.weight_units:
        return abs(qty) * cfg.qty_tolerance_weight_pct / 100
    return cfg.qty_tolerance_countable


def match_order(
    inv: Invoice,
    bl: DeliveryNote | None,
    po: PoSnapshot | None,
    supplier_partner_id: int | None,
    cfg: MatchConfig,
) -> tuple[list[Check], list[LinePair]]:
    checks: list[Check] = []
    po_ref = inv.po_ref.value if inv.po_ref else None
    if po is None:
        checks.append(Check("PO_NOT_FOUND", False, f"no confirmed PO {po_ref!r} in Odoo"))
        return checks, []
    checks.append(Check("PO_NOT_FOUND", True))
    same = supplier_partner_id is not None and po.partner_id == supplier_partner_id
    checks.append(
        Check(
            "PO_SUPPLIER_MISMATCH",
            same,
            "" if same else f"{po.name} belongs to another supplier than the invoice",
        )
    )
    checks.append(Check("BL_MISSING", bl is not None, "" if bl else "no delivery note received"))

    inv_pairs = pair_lines(inv.lines, po.lines, cfg.description_match_min_score)
    bl_pairs = pair_lines(bl.lines, po.lines, cfg.description_match_min_score) if bl else {}
    bl_by_po = {pl.id: i for i, pl in bl_pairs.items()}

    for i, ln in enumerate(inv.lines):
        if i not in inv_pairs:
            checks.append(
                Check(
                    "LINE_UNMATCHED",
                    False,
                    f"{ln.description.value!r} is not on {po.name}",
                    "invoice",
                    i,
                )
            )
    if bl:
        for i, ln in enumerate(bl.lines):
            if i not in bl_pairs:
                checks.append(
                    Check(
                        "LINE_UNMATCHED",
                        False,
                        f"{ln.description.value!r} is not on {po.name}",
                        "bl",
                        i,
                    )
                )
    if not any(c.code == "LINE_UNMATCHED" for c in checks):
        checks.append(Check("LINE_UNMATCHED", True))

    pairs: list[LinePair] = []
    for i, pl in inv_pairs.items():
        ln = inv.lines[i]
        qty, price = ln.quantity.value, ln.unit_price_ht.value
        bl_i = bl_by_po.get(pl.id)
        pairs.append(LinePair(i, pl, bl_i))
        name = pl.default_code or pl.product_name

        billable = pl.qty_received - pl.qty_invoiced
        ok = qty <= billable + _qty_tol(pl, billable, cfg)
        checks.append(
            Check(
                "QTY_EXCEEDS_RECEIVED",
                ok,
                ""
                if ok
                else f"{name}: invoiced {qty} {pl.uom}, received {pl.qty_received}, "
                f"already billed {pl.qty_invoiced}",
                "invoice",
                i,
            )
        )

        if bl and bl_i is not None:
            bl_qty = bl.lines[bl_i].quantity.value
            ok = abs(bl_qty - pl.qty_received) <= _qty_tol(pl, pl.qty_received, cfg)
            checks.append(
                Check(
                    "QTY_BL_MISMATCH",
                    ok,
                    ""
                    if ok
                    else f"{name}: BL says {bl_qty} {pl.uom}, Odoo receipt says {pl.qty_received}",
                    "bl",
                    bl_i,
                )
            )

        if pl.price_unit:
            diff_pct = abs(price - pl.price_unit) / pl.price_unit * 100
            ok = diff_pct <= cfg.price_tolerance_pct
        else:
            diff_pct, ok = Decimal(0), price == 0
        checks.append(
            Check(
                "PRICE_OVER_TOLERANCE",
                ok,
                ""
                if ok
                else f"{name}: invoiced {price}, PO price {pl.price_unit} "
                f"({diff_pct:+.1f}% vs {cfg.price_tolerance_pct}% allowed)",
                "invoice",
                i,
            )
        )
    return checks, pairs
