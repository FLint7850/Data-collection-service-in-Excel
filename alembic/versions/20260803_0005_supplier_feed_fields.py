"""add configurable supplier feed fields

Revision ID: 20260803_0005
Revises: 20260731_0004
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260803_0005"
down_revision = "20260731_0004"
branch_labels = None
depends_on = None


FIELD_NAMES = ("name_field", "price_field", "brand_field", "url_field")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "supplier_feeds" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("supplier_feeds")}
    for field_name in FIELD_NAMES:
        if field_name not in columns:
            op.add_column(
                "supplier_feeds",
                sa.Column(
                    field_name,
                    sa.String(length=255),
                    nullable=False,
                    server_default="",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "supplier_feeds" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("supplier_feeds")}
    for field_name in reversed(FIELD_NAMES):
        if field_name in columns:
            op.drop_column("supplier_feeds", field_name)
