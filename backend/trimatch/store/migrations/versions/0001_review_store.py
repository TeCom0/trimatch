"""review store

Revision ID: 0001
Revises:
Create Date: 2026-11-16 13:14:16.073341
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_case",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_key", sa.String(length=200), nullable=False),
        sa.Column("supplier_ice", sa.String(length=32), nullable=True),
        sa.Column("supplier_name", sa.String(length=200), nullable=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=True),
        sa.Column("po_ref", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "approved",
                "rejected",
                name="case_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason_codes", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("invoice", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bl", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("odoo_po", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("invoice_file", sa.Text(), nullable=False),
        sa.Column("bl_file", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_case")),
        sa.UniqueConstraint("case_key", name=op.f("uq_review_case_case_key")),
    )
    op.create_index(op.f("ix_review_case_status"), "review_case", ["status"], unique=False)
    op.create_table(
        "correction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("doc", sa.String(length=16), nullable=False),
        sa.Column("field_path", sa.String(length=200), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("old_confidence", sa.Double(), nullable=True),
        sa.Column("source", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["review_case.id"],
            name=op.f("fk_correction_case_id_review_case"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correction")),
    )
    op.create_index(op.f("ix_correction_case_id"), "correction", ["case_id"], unique=False)
    op.create_table(
        "review_action",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "approve",
                "reject",
                name="action_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("overridden_codes", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("odoo_bill_id", sa.Integer(), nullable=True),
        sa.Column("odoo_bill_name", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["review_case.id"],
            name=op.f("fk_review_action_case_id_review_case"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_action")),
    )
    op.create_index(op.f("ix_review_action_case_id"), "review_action", ["case_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_review_action_case_id"), table_name="review_action")
    op.drop_table("review_action")
    op.drop_index(op.f("ix_correction_case_id"), table_name="correction")
    op.drop_table("correction")
    op.drop_index(op.f("ix_review_case_status"), table_name="review_case")
    op.drop_table("review_case")
