"""add per-project and per-donor scraping proxy switches

Revision ID: 20261022_0008
Revises: 20260806_0007
Create Date: 2026-10-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20261022_0008"
down_revision = "20260806_0007"
branch_labels = None
depends_on = None


def _add_use_proxy(table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "use_proxy" not in columns:
        op.add_column(
            table_name,
            sa.Column(
                "use_proxy",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def upgrade() -> None:
    _add_use_proxy("projects")
    _add_use_proxy("donors")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in ("donors", "projects"):
        if table_name not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "use_proxy" in columns:
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_column("use_proxy")
