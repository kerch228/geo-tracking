"""Store only the latest location for each user device.

Revision ID: 20260924_02
Revises: 20260924_01
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_02"
down_revision: str | None = "20260924_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device_locations",
        sa.Column(
            "user_id",
            sa.String(length=128),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.alter_column("device_locations", "user_id", server_default=None)
    op.execute(
        "DELETE FROM device_locations older USING device_locations newer "
        "WHERE older.user_id = newer.user_id "
        "AND older.device_id = newer.device_id "
        "AND older.timestamp < newer.timestamp"
    )
    op.drop_constraint("device_locations_pkey", "device_locations", type_="primary")
    op.create_primary_key(
        "device_locations_pkey",
        "device_locations",
        ["user_id", "device_id"],
    )
    op.create_check_constraint(
        "ck_device_locations_user_id_not_empty",
        "device_locations",
        "char_length(btrim(user_id)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_device_locations_user_id_not_empty",
        "device_locations",
        type_="check",
    )
    op.drop_constraint("device_locations_pkey", "device_locations", type_="primary")
    op.create_primary_key(
        "device_locations_pkey",
        "device_locations",
        ["device_id", "timestamp"],
    )
    op.drop_column("device_locations", "user_id")
