"""store application logs in sqlite

Revision ID: 20260731_0004
Revises: 20260731_0003
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0004"
down_revision = "20260731_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "application_logs" in inspector.get_table_names():
        return
    op.create_table(
        "application_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=False),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_application_logs_created_at", "application_logs", ["created_at"])
    op.create_index("ix_application_logs_level", "application_logs", ["level"])


def downgrade() -> None:
    op.drop_index("ix_application_logs_level", table_name="application_logs")
    op.drop_index("ix_application_logs_created_at", table_name="application_logs")
    op.drop_table("application_logs")
