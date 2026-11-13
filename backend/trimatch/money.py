"""Money rules shared by the generator and (later) validate.py. Decimal only, half-up to 0.01."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def q2(x: Decimal | int | str) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(qty: Decimal, unit_price: Decimal) -> Decimal:
    return q2(qty * unit_price)


def vat_breakdown(
    lines: Iterable[tuple[Decimal, Decimal]],
) -> list[tuple[Decimal, Decimal, Decimal]]:
    """(rate, line_total_ht) pairs -> sorted [(rate, base_ht, vat_amount)].

    VAT is computed per rate on the summed base, then rounded (one rounding per rate).
    """
    bases: dict[Decimal, Decimal] = defaultdict(lambda: Decimal(0))
    for rate, total in lines:
        bases[Decimal(rate)] += total
    return [(rate, q2(base), q2(base * rate / 100)) for rate, base in sorted(bases.items())]


def totals(lines: Iterable[tuple[Decimal, Decimal]]) -> tuple[Decimal, list, Decimal]:
    """-> (total_ht, vat_breakdown, total_ttc)."""
    lines = list(lines)
    total_ht = q2(sum((t for _, t in lines), Decimal(0)))
    vat = vat_breakdown(lines)
    total_ttc = q2(total_ht + sum((a for _, _, a in vat), Decimal(0)))
    return total_ht, vat, total_ttc


def fr_amount(x: Decimal, decimals: int = 2) -> str:
    """French number format with a narrow no-break space as thousands separator: 2 450,00."""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",")


def fr_qty(x: Decimal) -> str:
    """Quantities: no decimals when whole (10), else comma decimals (12,5)."""
    if x == x.to_integral_value():
        return fr_amount(x, 0)
    return fr_amount(x.normalize(), max(1, -x.normalize().as_tuple().exponent))
