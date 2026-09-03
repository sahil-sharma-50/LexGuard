"""Add durable broker intents and append-only order observations."""

from collections.abc import Sequence
from datetime import timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "0002_broker_durability"
down_revision: str | Sequence[str] | None = "0001_case_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _drop_legacy_order_id_unique_constraint()
    with op.batch_alter_table("order_events", recreate="auto") as batch:
        batch.add_column(sa.Column("role", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("signed_quantities_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("client_order_id", sa.String(length=128), nullable=True))

    # Legacy rows predate role/signed quantity metadata.  Backfill safe entry
    # defaults so restart readers can continue projecting those observations.
    order_events = sa.table(
        "order_events",
        sa.column("role", sa.String(length=16)),
        sa.column("signed_quantities_json", sa.JSON()),
        sa.column("order_event_id", sa.Integer()),
        sa.column("occurred_at", sa.DateTime(timezone=True)),
        sa.column("deadline_at", sa.DateTime(timezone=True)),
    )
    op.execute(order_events.update().where(order_events.c.role.is_(None)).values(role="entry"))
    op.execute(
        order_events.update()
        .where(order_events.c.signed_quantities_json.is_(None))
        .values(signed_quantities_json={})
    )
    bind = op.get_bind()
    for row in bind.execute(
        sa.select(order_events.c.order_event_id, order_events.c.occurred_at).where(
            order_events.c.deadline_at.is_(None)
        )
    ):
        if row.occurred_at is not None:
            bind.execute(
                order_events.update()
                .where(order_events.c.order_event_id == row.order_event_id)
                .values(deadline_at=row.occurred_at + timedelta(seconds=90))
            )

    op.create_table(
        "entry_intents",
        sa.Column("intent_key", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("certificate_id", sa.String(length=36), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("order_ids_json", sa.JSON(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("intent_key"),
        sa.UniqueConstraint("client_order_id"),
    )
    op.create_table(
        "close_intents",
        sa.Column("intent_key", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=True),
        sa.Column("symbols_json", sa.JSON(), nullable=False),
        sa.Column("signed_quantities_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_order_id", sa.String(length=128), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("intent_key"),
    )


def _drop_legacy_order_id_unique_constraint() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "order_events" not in inspector.get_table_names():
        return
    constraints = [
        item
        for item in inspector.get_unique_constraints("order_events")
        if tuple(item.get("column_names") or ()) == ("alpaca_order_id",)
    ]
    if not constraints:
        return
    constraint_name = constraints[0].get("name")
    if bind.dialect.name != "sqlite" and constraint_name:
        op.drop_constraint(constraint_name, "order_events", type_="unique")
        return
    metadata = sa.MetaData()
    table = sa.Table("order_events", metadata, autoload_with=bind)
    for constraint in list(table.constraints):
        if isinstance(constraint, sa.UniqueConstraint) and tuple(
            column.name for column in constraint.columns
        ) == ("alpaca_order_id",):
            table.constraints.remove(constraint)
    with op.batch_alter_table("order_events", recreate="always", copy_from=table):
        pass


def downgrade() -> None:
    op.drop_table("close_intents")
    op.drop_table("entry_intents")
    with op.batch_alter_table("order_events", recreate="auto") as batch:
        batch.drop_column("client_order_id")
        batch.drop_column("deadline_at")
        batch.drop_column("signed_quantities_json")
        batch.drop_column("role")
