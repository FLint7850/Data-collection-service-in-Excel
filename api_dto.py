from __future__ import annotations

from typing import Dict, Iterable


NEWS_MONITOR_SUMMARY_FIELDS = frozenset(
    {
        "id",
        "brand_id",
        "primary_donor_id",
        "group",
        "brand",
        "site_url",
        "start_urls",
        "enabled",
        "state",
    }
)

NEWS_MONITOR_DETAIL_FIELDS = frozenset(
    {
        *NEWS_MONITOR_SUMMARY_FIELDS,
        "brand_created_at",
        "created_at",
        "schedule_type",
        "scan_time",
        "weekday",
        "next_run_at",
        "thread_count",
        "connection_id",
        "connection_method",
        "auto_connection_fallback",
        "exclusions",
        "product_url_filters",
        "product_url_exclusions",
        "extraction_rules",
        "selector_settings",
    }
)

NEWS_MONITOR_SUMMARY_STATE_FIELDS = frozenset(
    {
        "status",
        "percent",
        "processed",
        "found_products",
        "candidate_products",
        "compared_products",
        "in_memory_products",
        "queue_size",
        "active_tasks",
        "failed_pages",
        "availability_skipped",
        "new_count",
        "missing_by_feed",
        "last_event",
        "last_warning",
        "last_scan_at",
        "error",
        "started_at",
        "elapsed_seconds",
    }
)


def select_fields(
    source: Dict[str, object],
    fields: Iterable[str],
) -> Dict[str, object]:
    return {key: source[key] for key in fields if key in source}


def news_monitor_dto(
    source: Dict[str, object],
    *,
    include_details: bool,
) -> Dict[str, object]:
    fields = (
        NEWS_MONITOR_DETAIL_FIELDS
        if include_details
        else NEWS_MONITOR_SUMMARY_FIELDS
    )
    return select_fields(source, fields)


def news_monitor_state_dto(
    source: Dict[str, object],
    *,
    include_details: bool,
) -> Dict[str, object]:
    if include_details:
        return source
    return select_fields(source, NEWS_MONITOR_SUMMARY_STATE_FIELDS)
