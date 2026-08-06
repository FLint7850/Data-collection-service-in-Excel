"""optional promotion settings for supplier price converter

Revision ID: 20260806_0007
Revises: 20260806_0006
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0007"
down_revision = "20260806_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "price_converter" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("price_converter")}
    if "promo_field" not in columns:
        op.add_column(
            "price_converter",
            sa.Column("promo_field", sa.String(length=255), nullable=False, server_default=""),
        )
    if "promo_date" not in columns:
        op.add_column(
            "price_converter",
            sa.Column("promo_date", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "price_converter" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("price_converter")}
    with op.batch_alter_table("price_converter") as batch_op:
        if "promo_date" in columns:
            batch_op.drop_column("promo_date")
        if "promo_field" in columns:
            batch_op.drop_column("promo_field")
