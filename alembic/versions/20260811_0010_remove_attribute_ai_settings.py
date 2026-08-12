"""remove legacy attribute API settings

Revision ID: 20260811_0010
Revises: 20260811_0009
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_0010"
down_revision = "20260811_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "app_settings" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("app_settings")}
    if "attribute_ai" in columns:
        op.drop_column("app_settings", "attribute_ai")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "app_settings" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("app_settings")}
    if "attribute_ai" not in columns:
        op.add_column(
            "app_settings",
            sa.Column("attribute_ai", sa.JSON(), nullable=False, server_default="{}"),
        )
