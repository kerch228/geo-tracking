"""Create spatial domain tables.

Revision ID: 20260924_01
Revises:
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "20260924_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "geozones",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "center",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column("radius_meters", sa.Float(), nullable=False),
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
        sa.CheckConstraint(
            "radius_meters > 0",
            name="ck_geozones_radius_positive",
        ),
        sa.CheckConstraint(
            "char_length(btrim(user_id)) > 0",
            name="ck_geozones_user_id_not_empty",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geozones_user_id", "geozones", ["user_id"])
    op.create_index(
        "ix_geozones_center_gist",
        "geozones",
        ["center"],
        postgresql_using="gist",
    )

    op.create_table(
        "device_locations",
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "point",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(device_id)) > 0",
            name="ck_device_locations_device_id_not_empty",
        ),
        sa.PrimaryKeyConstraint("device_id", "timestamp"),
    )


def downgrade() -> None:
    op.drop_table("device_locations")
    op.drop_index("ix_geozones_center_gist", table_name="geozones")
    op.drop_index("ix_geozones_user_id", table_name="geozones")
    op.drop_table("geozones")
