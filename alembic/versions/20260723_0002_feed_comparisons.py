"""feed comparison settings and supplier feeds

Revision ID: 20260723_0002
Revises: 20260608_0001
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0002"
down_revision = "20260608_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "feed_comparisons" not in tables:
        op.create_table(
            "feed_comparisons",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("state", sa.JSON(), nullable=False),
            sa.Column("export_path", sa.String(length=500), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if "supplier_feeds" not in tables:
        op.create_table(
            "supplier_feeds",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("feed_url", sa.Text(), nullable=False),
            sa.Column("model_field", sa.String(length=255), nullable=False),
            sa.Column("exclusions", sa.JSON(), nullable=False),
            sa.Column("replace_rules", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("feed_url", name="uq_supplier_feeds_feed_url"),
        )
    else:
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("supplier_feeds")}
        if "exclusions" not in columns:
            op.add_column(
                "supplier_feeds",
                sa.Column("exclusions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            )
        if "replace_rules" not in columns:
            op.add_column(
                "supplier_feeds",
                sa.Column("replace_rules", sa.Text(), nullable=False, server_default=sa.text("''")),
            )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "supplier_feeds" in tables:
        op.drop_table("supplier_feeds")
    if "feed_comparisons" in tables:
        op.drop_table("feed_comparisons")
