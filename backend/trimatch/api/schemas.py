"""Request and response models of the review API. The React client's types are generated
from the OpenAPI document these produce (frontend/src/api/schema.d.ts)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trimatch.store.models import ActionKind, CaseStatus


class EditIn(BaseModel):
    doc: Literal["invoice", "bl"]
    path: str = Field(min_length=1, max_length=200, examples=["lines.2.unit_price_ht"])
    value: str | None = Field(
        description="New value as printed-normalised text: '2204.00', '2026-11-10', 'PO-004'."
    )


class RecheckIn(BaseModel):
    edits: list[EditIn] = []


class ApproveIn(RecheckIn):
    reason: str | None = Field(
        None, max_length=2000, description="Required when approving over an overridable check."
    )


class RejectIn(RecheckIn):
    reason: str = Field(max_length=2000)


class FailedCheck(BaseModel):
    code: str
    ok: bool
    detail: str
    doc: str
    line: int | None
    title: str
    hint: str
    overridable: bool
    fields: list[str]


class PoLineOut(BaseModel):
    id: int
    default_code: str | None
    product_name: str
    uom: str
    qty_ordered: Decimal
    qty_received: Decimal
    qty_invoiced: Decimal
    price_unit: Decimal


class PoOut(BaseModel):
    id: int
    name: str
    partner_id: int
    state: str
    lines: list[PoLineOut]


class BillRef(BaseModel):
    id: int
    name: str | None = None  # Odoo leaves draft bills unnamed
    state: str | None = None
    amount_total: float | None = None

    @field_validator("name", "state", "amount_total", mode="before")
    @classmethod
    def _odoo_false_is_none(cls, v: Any) -> Any:
        return None if v is False else v  # Odoo's JSON uses false for empty fields


class RecheckOut(BaseModel):
    action: Literal["draft", "review"]
    failed: list[FailedCheck]
    blocking: list[str]
    overridable: list[str]
    can_approve: bool
    needs_reason: bool
    already_drafted: BillRef | None
    po: PoOut | None


class CaseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_name: str | None
    supplier_ice: str | None
    invoice_number: str | None
    po_ref: str | None
    status: CaseStatus
    reason_codes: list[str]
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None


class DocumentInfo(BaseModel):
    file_name: str
    media_type: str
    pages: int


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc: str
    field_path: str
    old_value: Any
    new_value: Any
    old_confidence: float | None
    reviewer: str
    created_at: datetime


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: ActionKind
    reviewer: str
    reason: str | None
    overridden_codes: list[str]
    odoo_bill_id: int | None
    odoo_bill_name: str | None
    created_at: datetime


class CaseDetail(CaseSummary):
    reasons: list[FailedCheck] = Field(description="Failed checks when the case was created.")
    invoice: dict[str, Any] = Field(description="schema.Invoice as extracted (JSON).")
    bl: dict[str, Any] | None = Field(description="schema.DeliveryNote as extracted (JSON).")
    odoo_po: PoOut | None
    documents: dict[str, DocumentInfo]
    corrections: list[CorrectionOut]
    actions: list[ActionOut]
    first_opened_at: datetime | None


class ApproveOut(BaseModel):
    case: CaseSummary
    bill: BillRef
    corrections: int
    overridden: list[str]
    note_error: str | None


class RejectOut(BaseModel):
    case: CaseSummary
    corrections: int


class ReasonInfo(BaseModel):
    title: str
    hint: str
    overridable: bool
    fields: list[str]


class Meta(BaseModel):
    reviewer: str | None
    min_reason_chars: int
    reasons: dict[str, ReasonInfo]
    odoo_url: str


class ErrorOut(BaseModel):
    detail: str
    checks: list[FailedCheck] = []
