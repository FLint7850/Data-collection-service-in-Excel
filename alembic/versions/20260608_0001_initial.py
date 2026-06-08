"""initial sqlite schema

Revision ID: 20260608_0001
Revises:
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260608_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auto_cleanup", sa.Boolean(), nullable=False),
        sa.Column("smtp", sa.JSON(), nullable=False),
        sa.Column("feed_storage", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        sa.Column("group_type", sa.String(length=32), nullable=False),
        sa.Column("collapsed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "group_type", name="uq_brands_name_group_type"),
    )
    op.create_index("ix_brands_name", "brands", ["name"])
    op.create_table(
        "own_sites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False),
        sa.Column("feed_generate_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feed_url", name="uq_own_sites_feed_url"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("start_urls", sa.JSON(), nullable=False),
        sa.Column("thread_count", sa.Integer(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("product_url_filters", sa.JSON(), nullable=False),
        sa.Column("extraction_rules", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("auto_cleanup", sa.Boolean(), nullable=False),
        sa.Column("connection_method", sa.String(length=64), nullable=False),
        sa.Column("auto_connection_fallback", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("found_products", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "donors",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=False),
        sa.Column("site_url", sa.Text(), nullable=False),
        sa.Column("start_urls", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column("scan_time", sa.String(length=8), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.String(length=64), nullable=False),
        sa.Column("thread_count", sa.Integer(), nullable=False),
        sa.Column("connection_method", sa.String(length=64), nullable=False),
        sa.Column("auto_connection_fallback", sa.Boolean(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("product_url_filters", sa.JSON(), nullable=False),
        sa.Column("extraction_rules", sa.JSON(), nullable=False),
        sa.Column("selector_settings", sa.JSON(), nullable=False),
        sa.Column("seen_models", sa.JSON(), nullable=False),
        sa.Column("known_new_products", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_donors_brand_id", "donors", ["brand_id"])

def downgrade() -> None:
    op.drop_index("ix_donors_brand_id", table_name="donors")
    op.drop_table("donors")
    op.drop_table("scan_runs")
    op.drop_table("projects")
    op.drop_table("own_sites")
    op.drop_index("ix_brands_name", table_name="brands")
    op.drop_table("brands")
    op.drop_table("app_settings")
