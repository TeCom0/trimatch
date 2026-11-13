"""Extraction schema (SPEC section 5). Ground-truth labels use the same models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Box(BaseModel):
    page: int  # 1-based
    x0: float  # normalised 0..1, origin top-left
    y0: float
    x1: float
    y1: float


class Field(BaseModel, Generic[T]):  # noqa: UP046 (explicit Generic is clearest with pydantic)
    value: T | None
    confidence: float  # 0..1, from the extractor (1.0 in ground truth)
    source: Box | None = None  # where the value was read


class Party(BaseModel):
    name: Field[str]
    ice: Field[str]  # 15 digits, no spaces
    if_number: Field[str] | None = None
    tp_number: Field[str] | None = None  # taxe professionnelle (art. 145-III-2°)
    rc: Field[str] | None = None


class Line(BaseModel):
    description: Field[str]
    supplier_ref: Field[str] | None = None
    quantity: Field[Decimal]
    unit: Field[str] | None = None
    unit_price_ht: Field[Decimal] | None = None  # None on a BL without prices
    vat_rate: Field[Decimal] | None = None  # 0 (exempt), 10, 20 (percent)
    exemption_ref: Field[str] | None = None  # e.g. "art. 91-I-A-6°" on exempt lines
    line_total_ht: Field[Decimal] | None = None


class VatBreakdown(BaseModel):
    rate: Field[Decimal]
    base_ht: Field[Decimal]
    amount: Field[Decimal]


class DeliveryNote(BaseModel):
    doc_type: Literal["delivery_note"] = "delivery_note"
    supplier: Party
    customer: Party
    number: Field[str]
    date: Field[date]
    po_ref: Field[str] | None = None
    lines: list[Line]


class Invoice(BaseModel):
    doc_type: Literal["invoice"] = "invoice"
    supplier: Party
    customer: Party
    number: Field[str]
    date: Field[date]
    due_date: Field[date] | None = None
    payment_terms: Field[str] | None = None  # art. 145-III-7°
    po_ref: Field[str] | None = None
    bl_refs: list[Field[str]] = []
    currency: Literal["MAD"] = "MAD"
    lines: list[Line]
    total_ht: Field[Decimal]
    vat: list[VatBreakdown]
    total_ttc: Field[Decimal]


Document = DeliveryNote | Invoice


def truth(value: Any) -> Field:
    """A ground-truth field: confidence 1.0, box filled in after rendering."""
    return Field(value=value, confidence=1.0)


def get_path(model: BaseModel, path: str) -> Any:
    """Resolve a dotted path like 'lines.2.quantity' or 'vat.0.amount' on a document."""
    obj: Any = model
    for part in path.split("."):
        obj = obj[int(part)] if part.isdigit() else getattr(obj, part)
    return obj
