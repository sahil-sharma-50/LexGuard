"""create append-only case ledger tables"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_case_ledger"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("decision_window", sa.String(length=6), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("underlying", sa.String(length=8), nullable=True),
        sa.Column("certificate_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("case_id"),
        sa.UniqueConstraint("certificate_id"),
        sa.UniqueConstraint("trading_date", "decision_window", name="uq_case_window"),
    )
    op.create_table(
        "case_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=False),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_table(
        "case_artifacts",
        sa.Column("artifact_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    op.create_table(
        "scheduler_leases",
        sa.Column("lease_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("decision_window", sa.String(length=5), nullable=False),
        sa.Column("owner", sa.String(length=128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("lease_id"),
        sa.UniqueConstraint("trading_date", "decision_window", name="uq_lease_window"),
    )
    op.create_table(
        "order_events",
        sa.Column("order_event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("alpaca_order_id", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("order_event_id"),
        sa.UniqueConstraint("alpaca_order_id"),
    )


def downgrade() -> None:
    op.drop_table("order_events")
    op.drop_table("scheduler_leases")
    op.drop_table("case_artifacts")
    op.drop_table("case_events")
    op.drop_table("cases")
