"""Require finite geozone radii.

Revision ID: 20260924_03
Revises: 20260924_02
Create Date: 2026-09-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260924_03"
down_revision: str | None = "20260924_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_geozones_radius_finite",
        "geozones",
        "radius_meters < 'Infinity'::double precision",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_geozones_radius_finite",
        "geozones",
        type_="check",
    )
