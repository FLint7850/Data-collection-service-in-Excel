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


DEFAULT_BRAND_STATE = {
    "status": "idle",
    "stage": "",
    "percent": 0,
    "currenturl": "",
    "processed": 0,
    "found_products": 0,
    "candidate_products": 0,
    "compared_products": 0,
    "queue_size": 0,
    "active_tasks": 0,
    "active_urls": [],
    "in_memory_products": 0,
    "failed_pages": 0,
    "stall_seconds": 0,
    "last_event": "",
    "last_warning": "",
    "new_count": 0,
    "missing_by_feed": [],
    "skipped": 0,
    "last_scan_at": "",
    "last_csv": "",
    "error": "",
    "started_at": "",
    "finished_at": "",
    "elapsed_seconds": 0,
    "next_run_at": "",
}


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
        "connection_methods",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column("scan_time", sa.String(length=8), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("primary_donor_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["primary_donor_id"], ["donors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "group_name", name="uq_brands_name_group_name"),
    )
    op.create_index("ix_brands_name", "brands", ["name"])
    op.create_table(
        "donors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("legacy_id", sa.String(length=32), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=False),
        sa.Column("site_url", sa.Text(), nullable=False),
        sa.Column("start_urls", sa.JSON(), nullable=False),
        sa.Column("thread_count", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("auto_connection_fallback", sa.Boolean(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("product_url_filters", sa.JSON(), nullable=False),
        sa.Column("extraction_rules", sa.JSON(), nullable=False),
        sa.Column("selector_settings", sa.JSON(), nullable=False),
        sa.Column("seen_models", sa.JSON(), nullable=False),
        sa.Column("known_new_products", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["connection_methods.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("legacy_id"),
    )
    op.create_index("ix_donors_brand_id", "donors", ["brand_id"])
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
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("legacy_id", sa.String(length=32), nullable=False),
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
        sa.UniqueConstraint("legacy_id"),
    )


def downgrade() -> None:
    op.drop_table("projects")
    op.drop_table("own_sites")
    op.drop_index("ix_donors_brand_id", table_name="donors")
    op.drop_table("donors")
    op.drop_index("ix_brands_name", table_name="brands")
    op.drop_table("brands")
    op.drop_table("connection_methods")
    op.drop_table("app_settings")
