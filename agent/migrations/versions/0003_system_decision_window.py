"""Allow the SYSTEM case window used by runtime initialization."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_system_decision_window"
down_revision: str | Sequence[str] | None = "0002_broker_durability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "cases",
        "decision_window",
        existing_type=sa.String(length=5),
        type_=sa.String(length=6),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "cases",
        "decision_window",
        existing_type=sa.String(length=6),
        type_=sa.String(length=5),
        existing_nullable=False,
    )
