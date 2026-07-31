"""add normalized brand search name

Revision ID: 20260731_0003
Revises: 20260723_0002
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0003"
down_revision = "20260723_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "brands" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("brands")}
    if "search_name" not in columns:
        op.add_column(
            "brands",
            sa.Column(
                "search_name",
                sa.String(length=255),
                nullable=False,
                server_default="",
            ),
        )
    op.execute(
        "UPDATE brands SET search_name = lower(trim(name)) "
        "WHERE search_name IS NULL OR trim(search_name) = ''"
    )
    indexes = {index["name"] for index in inspector.get_indexes("brands")}
    if "ix_brands_search_name" not in indexes:
        op.create_index("ix_brands_search_name", "brands", ["search_name"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "brands" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("brands")}
    if "ix_brands_search_name" in indexes:
        op.drop_index("ix_brands_search_name", table_name="brands")
    columns = {column["name"] for column in inspector.get_columns("brands")}
    if "search_name" in columns:
        op.drop_column("brands", "search_name")
