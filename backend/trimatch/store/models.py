"""Review store tables (plan-phase1-review-screen.md). PostgreSQL, SQLAlchemy 2 typed ORM.

A `review_case` is one invoice (+ its BL) the pipeline sent to review. `correction` rows are
the labelled data: every value a reviewer changed, with what the extractor read, its
confidence and its box. `review_action` is the audit record of an approve or reject.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    ARRAY,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Deterministic constraint names, so later migrations can alter them.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        list[str]: ARRAY(String),
        datetime: DateTime(timezone=True),
    }


class CaseStatus(StrEnum):
    open = "open"
    approved = "approved"
    rejected = "rejected"


class ActionKind(StrEnum):
    approve = "approve"
    reject = "reject"


def _enum(e: type[StrEnum], name: str) -> Enum:
    # Stored as text with a CHECK constraint: adding a value later is a one-line migration.
    return Enum(e, name=name, native_enum=False, create_constraint=True, length=16)


class ReviewCase(Base):
    __tablename__ = "review_case"

    id: Mapped[int] = mapped_column(primary_key=True)
    # "<supplier ICE>_<invoice number>" as extracted: one case per supplier invoice.
    case_key: Mapped[str] = mapped_column(String(200), unique=True)
    supplier_ice: Mapped[str | None] = mapped_column(String(32))
    supplier_name: Mapped[str | None] = mapped_column(String(200))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    po_ref: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[CaseStatus] = mapped_column(
        _enum(CaseStatus, "case_status"), default=CaseStatus.open, index=True
    )
    reason_codes: Mapped[list[str]]
    reasons: Mapped[list[Any]]  # [{"code", "ok", "detail", "doc", "line"}]
    invoice: Mapped[dict[str, Any]]  # schema.Invoice as JSON, as extracted
    bl: Mapped[dict[str, Any] | None]  # schema.DeliveryNote as JSON
    odoo_po: Mapped[dict[str, Any] | None]  # match.PoSnapshot when the case was created
    invoice_file: Mapped[str] = mapped_column(Text)
    bl_file: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    first_opened_at: Mapped[datetime | None]
    decided_at: Mapped[datetime | None]

    corrections: Mapped[list[Correction]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="Correction.id"
    )
    actions: Mapped[list[ReviewAction]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="ReviewAction.id"
    )


class Correction(Base):
    __tablename__ = "correction"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("review_case.id", ondelete="CASCADE"), index=True
    )
    doc: Mapped[str] = mapped_column(String(16))  # "invoice" | "bl"
    field_path: Mapped[str] = mapped_column(String(200))  # e.g. "lines.2.unit_price_ht"
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    old_confidence: Mapped[float | None]
    source: Mapped[dict[str, Any] | None]  # the box the extractor read the value from
    reviewer: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    case: Mapped[ReviewCase] = relationship(back_populates="corrections")


class ReviewAction(Base):
    __tablename__ = "review_action"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("review_case.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[ActionKind] = mapped_column(_enum(ActionKind, "action_kind"))
    reviewer: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    overridden_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    odoo_bill_id: Mapped[int | None] = mapped_column(Integer)
    odoo_bill_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    case: Mapped[ReviewCase] = relationship(back_populates="actions")
