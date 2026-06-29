"""runtime indexes

Revision ID: 20260629_0002
Revises: 20260608_0001
Create Date: 2026-06-29
"""
from alembic import op

revision = "20260629_0002"
down_revision = "20260608_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_brands_enabled_next_run ON brands (enabled, next_run_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_donors_connection_id ON donors (connection_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_updated_at ON projects (updated_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_projects_updated_at")
    op.execute("DROP INDEX IF EXISTS ix_donors_connection_id")
    op.execute("DROP INDEX IF EXISTS ix_brands_enabled_next_run")
