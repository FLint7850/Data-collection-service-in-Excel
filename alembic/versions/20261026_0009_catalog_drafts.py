"""Catalog draft with publication-time image handling.

Revision ID: 20261026_0009
Revises: 20261022_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20261026_0009"
down_revision = "20261022_0008"
branch_labels = None
depends_on = None


def upgrade():
    # The application also auto-creates newly introduced tables via Base.metadata.
    # Skip when that startup path ran before the Alembic upgrade.
    inspector = sa.inspect(op.get_bind())
    if "attribute_catalog_drafts" in inspector.get_table_names():
        return
    op.create_table(
        "attribute_catalog_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("attribute_products.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("shop_id", sa.Integer(), sa.ForeignKey("attribute_shop_connections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("price", sa.String(64), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    if "attribute_catalog_drafts" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("attribute_catalog_drafts")
