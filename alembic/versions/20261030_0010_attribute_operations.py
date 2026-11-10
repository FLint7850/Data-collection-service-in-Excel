"""Persist Attribute Assistant background operations.

Revision ID: 20261030_0010
Revises: 20261026_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20261030_0010"
down_revision = "20261026_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "attribute_batch_operations" not in inspector.get_table_names():
        op.create_table(
            "attribute_batch_operations",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "batch_id",
                sa.Integer(),
                sa.ForeignKey("attribute_batches.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("stage", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("state", sa.JSON(), nullable=False),
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("attribute_batch_operations")}
    if "ix_attribute_batch_operations_batch_updated" not in indexes:
        op.create_index(
            "ix_attribute_batch_operations_batch_updated",
            "attribute_batch_operations",
            ["batch_id", "updated_at"],
        )
    if "ix_attribute_batch_operations_status" not in indexes:
        op.create_index(
            "ix_attribute_batch_operations_status",
            "attribute_batch_operations",
            ["status"],
        )


def downgrade() -> None:
    if "attribute_batch_operations" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("attribute_batch_operations")
