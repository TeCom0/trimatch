"""Duplicate invoices under a new number (plan-phase1-duplicate-invoice.md).

The same invoice number twice is caught before matching (ALREADY_DRAFTED). This catches a
re-issued copy: same supplier, same total TTC (within 0.01 MAD) and same invoice date as an
invoice already known, under a different number. Known means: a non-cancelled vendor bill
in Odoo, an invoice handled earlier in the same run, or an open or approved review case.
Deterministic; a false flag costs one review and the detail says exactly what matched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from trimatch.checks import Check
from trimatch.schema import Invoice

TOL = Decimal("0.01")


@dataclass(frozen=True)
class KnownInvoice:
    where: str  # "Odoo bill BILL/2026/11/0004", "review case #3", "FA-1.pdf earlier in this run"
    supplier_ice: str | None
    number: str | None
    total_ttc: Decimal | None
    invoice_date: date | None


def known_from(inv: Invoice, where: str) -> KnownInvoice:
    return KnownInvoice(
        where=where,
        supplier_ice=inv.supplier.ice.value,
        number=inv.number.value,
        total_ttc=inv.total_ttc.value,
        invoice_date=inv.date.value,
    )


def matches(inv: Invoice, k: KnownInvoice) -> bool:
    ice, number = inv.supplier.ice.value, inv.number.value
    total, day = inv.total_ttc.value, inv.date.value
    if None in (ice, total, day) or None in (k.supplier_ice, k.total_ttc, k.invoice_date):
        return False  # not enough to compare: REQUIRED_PRESENT already flags missing values
    return (
        k.supplier_ice == ice
        and k.number != number  # same number = the same invoice, handled as ALREADY_DRAFTED
        and k.invoice_date == day
        and abs(k.total_ttc - total) <= TOL
    )


def duplicate_check(inv: Invoice, known: list[KnownInvoice]) -> Check:
    hits = [k for k in known if matches(inv, k)]
    if not hits:
        return Check("DUPLICATE_SUSPECTED", True, doc="invoice")
    where = "; ".join(f"{k.where}{f' (number {k.number})' if k.number else ''}" for k in hits)
    return Check(
        "DUPLICATE_SUSPECTED",
        False,
        f"same supplier, total {inv.total_ttc.value} and date {inv.date.value.isoformat()} "
        f"as {where}",
        "invoice",
    )
