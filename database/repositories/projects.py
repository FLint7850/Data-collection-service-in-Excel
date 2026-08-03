"""Targeted project persistence."""

from typing import Mapping, Optional

from sqlalchemy.orm import Session

from database.session import session_scope
from models import Project


PROJECT_MUTABLE_FIELDS = {
    "name",
    "start_urls",
    "thread_count",
    "exclusions",
    "product_url_filters",
    "product_url_exclusions",
    "extraction_rules",
    "state",
    "auto_cleanup",
    "connection_method",
    "auto_connection_fallback",
    "persist_profile",
}


def update_project(project_id: int, values: Mapping[str, object], db_session: Optional[Session] = None) -> Project:
    if db_session is None:
        with session_scope() as owned_session:
            return update_project(project_id, values, owned_session)
    row = db_session.get(Project, int(project_id))
    if row is None:
        raise LookupError(f"Project {project_id} was not found")
    for field in PROJECT_MUTABLE_FIELDS.intersection(values):
        setattr(row, field, values[field])
    db_session.flush()
    return row


def delete_project(project_id: int, db_session: Optional[Session] = None) -> bool:
    if db_session is None:
        with session_scope() as owned_session:
            return delete_project(project_id, owned_session)
    row = db_session.get(Project, int(project_id))
    if row is None:
        return False
    db_session.delete(row)
    return True
