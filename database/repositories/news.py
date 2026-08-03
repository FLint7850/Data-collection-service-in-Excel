"""Targeted brand and donor persistence."""

from typing import Mapping, Optional

from sqlalchemy.orm import Session

from database.session import session_scope
from models import Brand, Donor


BRAND_MUTABLE_FIELDS = {
    "name", "search_name", "group_name", "state", "enabled", "schedule_type",
    "scan_time", "weekday", "next_run_at", "primary_donor_id",
}
DONOR_MUTABLE_FIELDS = {
    "site_url", "start_urls", "thread_count", "connection_id",
    "auto_connection_fallback", "exclusions", "product_url_filters",
    "product_url_exclusions", "extraction_rules", "selector_settings",
    "seen_models", "known_new_products",
}


def update_brand(brand_id: int, values: Mapping[str, object], db_session: Optional[Session] = None) -> Brand:
    if db_session is None:
        with session_scope() as owned_session:
            return update_brand(brand_id, values, owned_session)
    row = db_session.get(Brand, int(brand_id))
    if row is None:
        raise LookupError(f"Brand {brand_id} was not found")
    for field in BRAND_MUTABLE_FIELDS.intersection(values):
        setattr(row, field, values[field])
    db_session.flush()
    return row


def update_donor(donor_id: int, values: Mapping[str, object], db_session: Optional[Session] = None) -> Donor:
    if db_session is None:
        with session_scope() as owned_session:
            return update_donor(donor_id, values, owned_session)
    row = db_session.get(Donor, int(donor_id))
    if row is None:
        raise LookupError(f"Donor {donor_id} was not found")
    for field in DONOR_MUTABLE_FIELDS.intersection(values):
        setattr(row, field, values[field])
    db_session.flush()
    return row


def delete_donor(donor_id: int, db_session: Optional[Session] = None) -> bool:
    if db_session is None:
        with session_scope() as owned_session:
            return delete_donor(donor_id, owned_session)
    row = db_session.get(Donor, int(donor_id))
    if row is None:
        return False
    db_session.delete(row)
    return True


def delete_brand(brand_id: int, db_session: Optional[Session] = None) -> bool:
    if db_session is None:
        with session_scope() as owned_session:
            return delete_brand(brand_id, owned_session)
    row = db_session.get(Brand, int(brand_id))
    if row is None:
        return False
    db_session.delete(row)
    return True
