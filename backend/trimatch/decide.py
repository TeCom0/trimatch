"""Decision (SPEC 7.4): draft only if every check passes and the required fields are confident."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from trimatch.checks import Check, failed
from trimatch.config import MatchConfig
from trimatch.schema import DeliveryNote, Field, Invoice


@dataclass
class Decision:
    action: Literal["draft", "review", "skip"]
    reasons: list[Check] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return sorted({c.code for c in self.reasons})


def required_fields(doc: DeliveryNote | Invoice) -> dict[str, Field | None]:
    out: dict[str, Field | None] = {
        "number": doc.number,
        "date": doc.date,
        "supplier.ice": doc.supplier.ice,
        "po_ref": doc.po_ref,
    }
    if isinstance(doc, Invoice):
        out |= {"total_ht": doc.total_ht, "total_ttc": doc.total_ttc}
    for i, ln in enumerate(doc.lines):
        out[f"lines.{i}.quantity"] = ln.quantity
        out[f"lines.{i}.supplier_ref"] = ln.supplier_ref
        if isinstance(doc, Invoice):
            out[f"lines.{i}.unit_price_ht"] = ln.unit_price_ht
            out[f"lines.{i}.line_total_ht"] = ln.line_total_ht
    return out


def confidence_check(doc: DeliveryNote | Invoice, cfg: MatchConfig, kind: str) -> Check:
    low = [
        f"{name} ({f.confidence:.2f})"
        for name, f in required_fields(doc).items()
        if f is not None and f.value is not None and f.confidence < cfg.min_field_confidence
    ]
    return Check(
        "LOW_CONFIDENCE",
        not low,
        f"below {cfg.min_field_confidence}: {', '.join(low)}" if low else "",
        kind,
    )


def decide(checks: list[Check]) -> Decision:
    bad = failed(checks)
    return Decision("review", bad) if bad else Decision("draft")
