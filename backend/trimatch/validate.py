"""Deterministic document validation (SPEC section 6). Pure Python: Odoo data is passed in."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stdnum.ma import ice as ma_ice

from trimatch.checks import Check
from trimatch.config import MatchConfig
from trimatch.money import q2
from trimatch.schema import DeliveryNote, Invoice

TOL = Decimal("0.01")


@dataclass(frozen=True)
class OdooRefs:
    """What validation needs from Odoo, fetched once per run."""

    company_ice: str
    suppliers: list[dict]  # [{"id", "name", "ice"}]


def _v(field):
    return None if field is None else field.value


def _ice_ok(value: str | None) -> bool:
    return bool(value) and ma_ice.is_valid(value)


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOL


def validate_common(doc: DeliveryNote | Invoice, refs: OdooRefs, kind: str) -> list[Check]:
    out: list[Check] = []
    sup_ice, cust_ice = _v(doc.supplier.ice), _v(doc.customer.ice)
    bad = [n for n, v in (("supplier", sup_ice), ("customer", cust_ice)) if not _ice_ok(v)]
    out.append(Check("ICE_FORMAT", not bad, f"invalid ICE: {', '.join(bad)}" if bad else "", kind))

    matches = [s for s in refs.suppliers if s["ice"] == sup_ice]
    out.append(
        Check(
            "SUPPLIER_KNOWN",
            len(matches) == 1,
            "" if len(matches) == 1 else f"{len(matches)} Odoo suppliers with ICE {sup_ice}",
            kind,
        )
    )
    out.append(
        Check(
            "CUSTOMER_IS_US",
            cust_ice == refs.company_ice,
            "" if cust_ice == refs.company_ice else f"customer ICE {cust_ice} is not ours",
            kind,
        )
    )
    return out


def _required(doc: DeliveryNote | Invoice, kind: str) -> Check:
    names = ["number", "date"]
    if isinstance(doc, Invoice):
        names += ["total_ht", "total_ttc"]
    missing = [n for n in names if _v(getattr(doc, n)) is None]
    if _v(doc.supplier.ice) is None:
        missing.append("supplier.ice")
    if not doc.lines:
        missing.append("lines")
    for i, ln in enumerate(doc.lines):
        if _v(ln.quantity) is None:
            missing.append(f"lines.{i}.quantity")
        if isinstance(doc, Invoice) and None in (_v(ln.unit_price_ht), _v(ln.line_total_ht)):
            missing.append(f"lines.{i} price/total")
    return Check("REQUIRED_PRESENT", not missing, ", ".join(missing), kind)


def validate_invoice(inv: Invoice, refs: OdooRefs, cfg: MatchConfig) -> list[Check]:
    out = validate_common(inv, refs, "invoice")
    req = _required(inv, "invoice")
    out.append(req)
    if not req.ok:
        return out  # arithmetic checks need the values

    for i, ln in enumerate(inv.lines):
        expected = q2(ln.quantity.value * ln.unit_price_ht.value)
        ok = _close(expected, ln.line_total_ht.value)
        out.append(
            Check(
                "LINE_MATH",
                ok,
                ""
                if ok
                else f"{ln.quantity.value} x {ln.unit_price_ht.value} = {expected}, "
                f"document says {ln.line_total_ht.value}",
                "invoice",
                i,
            )
        )

    sum_lines = sum((ln.line_total_ht.value for ln in inv.lines), Decimal(0))
    ok = _close(sum_lines, inv.total_ht.value)
    out.append(
        Check(
            "SUM_HT",
            ok,
            "" if ok else f"lines sum to {sum_lines}, total HT is {inv.total_ht.value}",
            "invoice",
        )
    )

    rates = {_v(ln.vat_rate) for ln in inv.lines} | {_v(v.rate) for v in inv.vat}
    unknown = sorted(str(r) for r in rates if r is None or Decimal(r) not in cfg.vat_rates)
    out.append(
        Check(
            "VAT_RATE_KNOWN",
            not unknown,
            f"unknown rates: {', '.join(unknown)}" if unknown else "",
            "invoice",
        )
    )

    vat_problems = []
    for v in inv.vat:
        if None in (_v(v.rate), _v(v.base_ht), _v(v.amount)):
            vat_problems.append("incomplete VAT row")
            continue
        expected = q2(v.base_ht.value * v.rate.value / 100)
        if not _close(expected, v.amount.value):
            vat_problems.append(
                f"{v.rate.value}%: {v.base_ht.value} -> {expected}, document says {v.amount.value}"
            )
    bases = sum((_v(v.base_ht) or Decimal(0) for v in inv.vat), Decimal(0))
    if not _close(bases, inv.total_ht.value):
        vat_problems.append(f"VAT bases sum to {bases}, total HT is {inv.total_ht.value}")
    # Each line's rate must have a VAT row with the matching base.
    for rate in {_v(ln.vat_rate) for ln in inv.lines}:
        base = sum(
            (ln.line_total_ht.value for ln in inv.lines if _v(ln.vat_rate) == rate), Decimal(0)
        )
        row = [v for v in inv.vat if _v(v.rate) == rate]
        if not row or not _close(row[0].base_ht.value or Decimal(0), base):
            vat_problems.append(f"{rate}% lines sum to {base}, no matching VAT row")
    out.append(Check("VAT_MATH", not vat_problems, "; ".join(vat_problems), "invoice"))

    vat_total = sum((_v(v.amount) or Decimal(0) for v in inv.vat), Decimal(0))
    expected_ttc = inv.total_ht.value + vat_total
    ok = _close(expected_ttc, inv.total_ttc.value)
    out.append(
        Check(
            "SUM_TTC",
            ok,
            "" if ok else f"HT + VAT = {expected_ttc}, TTC is {inv.total_ttc.value}",
            "invoice",
        )
    )
    return out


def validate_bl(bl: DeliveryNote, refs: OdooRefs) -> list[Check]:
    return [*validate_common(bl, refs, "bl"), _required(bl, "bl")]
