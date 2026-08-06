"""supplier price-list converter

Revision ID: 20260806_0006
Revises: 20260803_0005
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0006"
down_revision = "20260803_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "price_converter" in tables:
        return
    op.create_table(
        "price_converter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_field", sa.String(length=255), nullable=False),
        sa.Column("price_field", sa.String(length=255), nullable=False),
        sa.Column("sheet_number", sa.Integer(), nullable=True),
        sa.Column("export_path", sa.String(length=500), nullable=False),
        sa.Column("file", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "price_converter" in tables:
        op.drop_table("price_converter")
