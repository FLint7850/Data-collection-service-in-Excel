"""attribute assistant domain tables

Revision ID: 20260810_0008
Revises: 20260806_0007
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_0008"
down_revision = "20260806_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "attribute_categories" in inspector.get_table_names():
        return
    op.create_table(
        "attribute_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("full_path", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("full_path", name="uq_attribute_categories_full_path"),
    )
    op.create_table(
        "attribute_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["attribute_categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", "name", name="uq_attribute_templates_category_name"),
    )
    op.create_index("ix_attribute_templates_category_id", "attribute_templates", ["category_id"])
    op.create_table(
        "attribute_template_fields",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("is_composite", sa.Boolean(), nullable=False),
        sa.Column("separator", sa.String(length=16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("use_dash_if_empty", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["attribute_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "group_name", "name", name="uq_attribute_template_fields_name"),
    )
    op.create_index("ix_attribute_template_fields_template_id", "attribute_template_fields", ["template_id"])
    op.create_table(
        "attribute_allowed_values",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["field_id"], ["attribute_template_fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_id", "normalized_value", name="uq_attribute_allowed_values_normalized"),
    )
    op.create_index("ix_attribute_allowed_values_field_id", "attribute_allowed_values", ["field_id"])
    op.create_table(
        "attribute_value_synonyms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("allowed_value_id", sa.Integer(), nullable=False),
        sa.Column("synonym", sa.Text(), nullable=False),
        sa.Column("normalized_synonym", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["allowed_value_id"], ["attribute_allowed_values.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("allowed_value_id", "normalized_synonym", name="uq_attribute_value_synonyms_normalized"),
    )
    op.create_table(
        "attribute_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("source_filename", sa.String(length=500), nullable=False),
        sa.Column("stored_filename", sa.String(length=500), nullable=False),
        sa.Column("export_filename", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("products_count", sa.Integer(), nullable=False),
        sa.Column("attributes_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["attribute_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attribute_batches_created_at", "attribute_batches", ["created_at"])
    op.create_table(
        "attribute_products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["attribute_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attribute_products_batch_id", "attribute_products", ["batch_id"])
    op.create_index("ix_attribute_products_model", "attribute_products", ["model"])
    op.create_table(
        "attribute_product_values",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("template_field_id", sa.Integer(), nullable=True),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        sa.Column("attribute_name", sa.String(length=255), nullable=False),
        sa.Column("current_value", sa.Text(), nullable=False),
        sa.Column("proposed_value", sa.Text(), nullable=False),
        sa.Column("final_value", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_in_template", sa.Boolean(), nullable=False),
        sa.Column("is_extra_attribute", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["attribute_products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_field_id"], ["attribute_template_fields.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attribute_product_values_product_id", "attribute_product_values", ["product_id"])
    op.create_index("ix_attribute_product_values_status", "attribute_product_values", ["status"])
    op.create_table(
        "attribute_processing_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["attribute_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["attribute_products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attribute_processing_logs_batch_id", "attribute_processing_logs", ["batch_id"])
    op.create_index("ix_attribute_processing_logs_product_id", "attribute_processing_logs", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_attribute_processing_logs_product_id", table_name="attribute_processing_logs")
    op.drop_index("ix_attribute_processing_logs_batch_id", table_name="attribute_processing_logs")
    op.drop_table("attribute_processing_logs")
    op.drop_index("ix_attribute_product_values_status", table_name="attribute_product_values")
    op.drop_index("ix_attribute_product_values_product_id", table_name="attribute_product_values")
    op.drop_table("attribute_product_values")
    op.drop_index("ix_attribute_products_model", table_name="attribute_products")
    op.drop_index("ix_attribute_products_batch_id", table_name="attribute_products")
    op.drop_table("attribute_products")
    op.drop_index("ix_attribute_batches_created_at", table_name="attribute_batches")
    op.drop_table("attribute_batches")
    op.drop_table("attribute_value_synonyms")
    op.drop_index("ix_attribute_allowed_values_field_id", table_name="attribute_allowed_values")
    op.drop_table("attribute_allowed_values")
    op.drop_index("ix_attribute_template_fields_template_id", table_name="attribute_template_fields")
    op.drop_table("attribute_template_fields")
    op.drop_index("ix_attribute_templates_category_id", table_name="attribute_templates")
    op.drop_table("attribute_templates")
    op.drop_table("attribute_categories")
