"""Reason codes as a reviewer sees them: a title, what to do, which fields to look at, and
whether a reviewer may override the check (plan-phase1-review-screen.md, decision D2).

`fields` are field paths on the check's document ("invoice" or "bl"); "{line}" is replaced
by the check's line index. The review screen highlights them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from trimatch.checks import Check


@dataclass(frozen=True)
class Reason:
    title: str
    hint: str
    overridable: bool = False
    fields: tuple[str, ...] = ()


REASONS: dict[str, Reason] = {
    "ICE_FORMAT": Reason(
        "ICE is not valid",
        "An ICE has 15 digits and passes the mod-97 check. Usually a misread digit.",
        fields=("supplier.ice", "customer.ice"),
    ),
    "SUPPLIER_KNOWN": Reason(
        "Supplier not found in Odoo",
        "No single Odoo supplier has this ICE. Check the ICE, or create the supplier in Odoo.",
        fields=("supplier.ice", "supplier.name"),
    ),
    "CUSTOMER_IS_US": Reason(
        "Customer is not our company",
        "The customer ICE on the document is not ours. Check the ICE or reject the document.",
        fields=("customer.ice", "customer.name"),
    ),
    "REQUIRED_PRESENT": Reason(
        "Required value missing",
        "A required value was not read. Type it from the document.",
    ),
    "LINE_MATH": Reason(
        "Line total does not add up",
        "Quantity × unit price differs from the line total. Usually one misread number.",
        fields=(
            "lines.{line}.quantity",
            "lines.{line}.unit_price_ht",
            "lines.{line}.line_total_ht",
        ),
    ),
    "SUM_HT": Reason(
        "Lines do not add up to total HT",
        "The sum of the line totals differs from the total excl. tax.",
        fields=("total_ht",),
    ),
    "VAT_RATE_KNOWN": Reason(
        "Unknown VAT rate",
        "Only 0 (exempt), 10 and 20 % exist in 2026 (CGI art. 99, 91).",
        fields=("vat",),
    ),
    "VAT_MATH": Reason(
        "VAT breakdown does not add up",
        "A VAT base × rate differs from the VAT amount, or the bases differ from the line totals.",
        fields=("vat", "total_ht"),
    ),
    "SUM_TTC": Reason(
        "Total incl. tax does not add up",
        "Total HT + VAT differs from the total TTC.",
        fields=("total_ht", "total_ttc"),
    ),
    "LOW_CONFIDENCE": Reason(
        "Low extraction confidence",
        "The extractor was unsure about a required value. Check it against the document.",
        overridable=True,
    ),
    "PO_NOT_FOUND": Reason(
        "Purchase order not found",
        "No confirmed Odoo PO with this reference. Check the PO reference on the document.",
        fields=("po_ref",),
    ),
    "PO_SUPPLIER_MISMATCH": Reason(
        "PO belongs to another supplier",
        "The PO found in Odoo is for a different supplier than the invoice.",
        fields=("po_ref", "supplier.ice"),
    ),
    "BL_MISSING": Reason(
        "Delivery note missing",
        "A three-way match needs the delivery note. Wait for it or reject.",
    ),
    "LINE_UNMATCHED": Reason(
        "Line not on the purchase order",
        "This line could not be paired with a PO line by reference or description.",
        fields=("lines.{line}.supplier_ref", "lines.{line}.description"),
    ),
    "QTY_EXCEEDS_RECEIVED": Reason(
        "Billed more than received",
        "The supplier bills goods Odoo has not received. Reject and ask for a credit note, "
        "or validate a further receipt in Odoo first.",
        fields=("lines.{line}.quantity",),
    ),
    "QTY_BL_MISMATCH": Reason(
        "Delivery note disagrees with the receipt",
        "The BL quantity differs from what Odoo received. Check the BL; approve with a reason "
        "if the receipt in Odoo is right.",
        overridable=True,
        fields=("lines.{line}.quantity",),
    ),
    "PRICE_OVER_TOLERANCE": Reason(
        "Price differs from the PO",
        "The unit price is outside the tolerance. Approve with a reason if the new price was "
        "agreed, otherwise reject.",
        overridable=True,
        fields=("lines.{line}.unit_price_ht",),
    ),
    "BILL_TOTAL_MISMATCH": Reason(
        "Odoo totals differ from the invoice",
        "The draft Odoo computed did not match the invoice totals, so it was not kept.",
        fields=("total_ht", "total_ttc", "vat"),
    ),
}

OVERRIDABLE = frozenset(code for code, r in REASONS.items() if r.overridable)

_UNKNOWN = Reason("Check failed", "")


def describe(check: Check) -> dict:
    """A failed check as the review screen shows it."""
    r = REASONS.get(check.code, _UNKNOWN)
    line = check.line
    fields = [f.replace("{line}", str(line)) for f in r.fields if line is not None or "{" not in f]
    if check.code in ("LOW_CONFIDENCE", "REQUIRED_PRESENT") and check.detail:
        fields += _named_fields(check.detail)
    return {
        **check.to_dict(),
        "title": r.title,
        "hint": r.hint,
        "overridable": r.overridable,
        "fields": fields,
    }


def _named_fields(detail: str) -> list[str]:
    """Field paths named in a LOW_CONFIDENCE / REQUIRED_PRESENT detail (decide.py, validate.py).

    "below 0.85: number (0.40), lines.1.quantity (0.62)" -> ["number", "lines.1.quantity"]
    "number, lines.0 price/total" -> ["number", "lines.0.unit_price_ht", "lines.0.line_total_ht"]
    """
    out: list[str] = []
    for part in detail.split(":", 1)[-1].split(","):
        name = part.strip().split(" (")[0].strip()
        if name.endswith(" price/total"):
            base = name.removesuffix(" price/total")
            out += [f"{base}.unit_price_ht", f"{base}.line_total_ht"]
        elif name:
            out.append(name)
    return out


def catalogue() -> dict[str, dict]:
    return {code: asdict(r) for code, r in REASONS.items()}
