"""complete attribute assistant workflow

Revision ID: 20260811_0009
Revises: 20260810_0008
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_0009"
down_revision = "20260810_0008"
branch_labels = None
depends_on = None


def _add_columns(table: str, definitions: list[tuple[str, sa.types.TypeEngine, object]]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table)}
    for name, column_type, default in definitions:
        if name in existing:
            continue
        op.add_column(
            table,
            sa.Column(name, column_type, nullable=False, server_default=default),
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "attribute_categories" not in tables:
        return

    _add_columns(
        "attribute_categories",
        [
            ("parent_name", sa.String(length=255), ""),
            ("external_key", sa.String(length=128), ""),
        ],
    )
    _add_columns(
        "attribute_templates",
        [
            ("product_type", sa.String(length=255), ""),
            ("is_default", sa.Boolean(), sa.false()),
            ("version", sa.Integer(), "1"),
        ],
    )
    _add_columns(
        "attribute_template_fields",
        [("is_active", sa.Boolean(), sa.true())],
    )
    _add_columns(
        "attribute_allowed_values",
        [
            ("value_type", sa.String(length=32), "value"),
            ("is_global", sa.Boolean(), sa.false()),
            ("is_recommended", sa.Boolean(), sa.true()),
            ("is_active", sa.Boolean(), sa.true()),
            ("source", sa.String(length=64), "import"),
        ],
    )
    _add_columns(
        "attribute_batches",
        [
            ("report_filename", sa.String(length=500), ""),
            ("input_mode", sa.String(length=32), "csv"),
            ("processing_mode", sa.String(length=32), "suggest"),
            ("source_urls", sa.JSON(), "[]"),
        ],
    )
    _add_columns(
        "attribute_products",
        [
            ("source_url", sa.Text(), ""),
            ("category_name", sa.String(length=255), ""),
            ("brand", sa.String(length=255), ""),
            ("donor_urls", sa.JSON(), "[]"),
        ],
    )
    _add_columns(
        "attribute_product_values",
        [("source_details", sa.JSON(), "{}")],
    )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "attribute_template_revisions" not in tables:
        op.create_table(
            "attribute_template_revisions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("template_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("report", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["template_id"], ["attribute_templates.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_attribute_template_revisions_template_id",
            "attribute_template_revisions",
            ["template_id"],
        )
    if "attribute_donors" not in tables:
        op.create_table(
            "attribute_donors",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column("base_url", sa.Text(), nullable=False),
            sa.Column("selectors", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("domain", name="uq_attribute_donors_domain"),
        )
        op.create_index("ix_attribute_donors_name", "attribute_donors", ["name"])
    if "attribute_mapping_rules" not in tables:
        op.create_table(
            "attribute_mapping_rules",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("donor_id", sa.Integer(), nullable=False),
            sa.Column("template_id", sa.Integer(), nullable=True),
            sa.Column("template_field_id", sa.Integer(), nullable=False),
            sa.Column("donor_attribute_name", sa.String(length=255), nullable=False),
            sa.Column("normalized_donor_name", sa.String(length=255), nullable=False),
            sa.Column("confidence", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["donor_id"], ["attribute_donors.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["template_id"], ["attribute_templates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["template_field_id"], ["attribute_template_fields.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "donor_id",
                "template_id",
                "normalized_donor_name",
                name="uq_attribute_mapping_rules_scope",
            ),
        )
        op.create_index("ix_attribute_mapping_rules_template_id", "attribute_mapping_rules", ["template_id"])
    if "attribute_donor_product_sources" not in tables:
        op.create_table(
            "attribute_donor_product_sources",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("donor_id", sa.Integer(), nullable=True),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("raw_html_path", sa.Text(), nullable=False),
            sa.Column("parsed_data", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["attribute_products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["donor_id"], ["attribute_donors.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_attribute_donor_product_sources_product_id",
            "attribute_donor_product_sources",
            ["product_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "attribute_donor_product_sources" in tables:
        op.drop_index("ix_attribute_donor_product_sources_product_id", table_name="attribute_donor_product_sources")
        op.drop_table("attribute_donor_product_sources")
    if "attribute_mapping_rules" in tables:
        op.drop_index("ix_attribute_mapping_rules_template_id", table_name="attribute_mapping_rules")
        op.drop_table("attribute_mapping_rules")
    if "attribute_donors" in tables:
        op.drop_index("ix_attribute_donors_name", table_name="attribute_donors")
        op.drop_table("attribute_donors")
    if "attribute_template_revisions" in tables:
        op.drop_index("ix_attribute_template_revisions_template_id", table_name="attribute_template_revisions")
        op.drop_table("attribute_template_revisions")

