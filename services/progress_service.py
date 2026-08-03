"""Extracted application service module."""

from runtime.state import PROJECT_PROGRESS_FIELDS, news_lock, news_settings, progress_tracker, projects, projects_lock
from typing import Dict, Iterable, List, Optional
from services.scraping import clean_text


def is_active_status(status: object) -> bool:
    return str(status or "") in {"running", "queued", "pausing", "stopping"}


def progress_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def has_positive_progress_value(state: Dict[str, object], fields: Iterable[str]) -> bool:
    return any(progress_int(state.get(field, 0)) > 0 for field in fields)


def same_progress_run(current: Dict[str, object], previous: Dict[str, object]) -> bool:
    current_started = str(current.get("started_at") or "")
    previous_started = str(previous.get("started_at") or "")
    return not current_started or not previous_started or current_started == previous_started


def is_empty_active_progress_state(state: Dict[str, object], fields: Iterable[str]) -> bool:
    return (
        is_active_status(state.get("status"))
        and not has_positive_progress_value(state, fields)
        and not str(state.get("currenturl") or "").strip()
    )


def merge_stable_progress_state(
    state: Dict[str, object],
    previous: Optional[Dict[str, object]],
    fields: Iterable[str],
) -> Dict[str, object]:
    if not previous or not same_progress_run(state, previous) or not is_active_status(state.get("status")):
        return state
    merged = dict(state)
    for field in fields:
        if progress_int(merged.get(field, 0)) == 0 and progress_int(previous.get(field, 0)) > 0:
            merged[field] = previous[field]
    if not is_empty_active_progress_state(state, fields):
        return merged
    for field in (
        "percent",
        "currenturl",
        "active_urls",
        "last_event",
        "last_warning",
        "elapsed_seconds",
        "stall_seconds",
    ):
        value = merged.get(field)
        if value in ("", None, 0, []) and previous.get(field):
            merged[field] = previous[field]
    return merged


def stable_project_state(project: Dict[str, object], state: Dict[str, object]) -> Dict[str, object]:
    if not is_active_status(state.get("status")):
        return state
    previous = project.get("_last_progress_state")
    return merge_stable_progress_state(
        state,
        previous if isinstance(previous, dict) else None,
        PROJECT_PROGRESS_FIELDS,
    )


def projects_progress_payload() -> List[Dict[str, object]]:
    from services.projects import public_project
    with projects_lock:
        return [public_project(project, include_details=False) for project in projects.values()]


def news_progress_payload() -> List[Dict[str, object]]:
    from runtime.news_tasks import cleanup_stale_news_transitions
    from services.news import public_news_monitor
    cleanup_stale_news_transitions()
    with news_lock:
        return [
            public_news_monitor(monitor, include_details=False)
            for monitor in news_settings.get("monitors", [])
            if isinstance(monitor, dict)
        ]


def register_progress_items(
    project_items: Optional[List[Dict[str, object]]] = None,
    news_items: Optional[List[Dict[str, object]]] = None,
) -> tuple[str, Dict[str, object]]:
    if project_items is not None:
        progress_tracker.synchronize("projects", project_items)
    if news_items is not None:
        progress_tracker.synchronize("news", news_items)
    return progress_tracker.cursor, {}


def publish_project_progress(project: Dict[str, object]) -> None:
    from services.projects import public_project
    progress_tracker.publish(
        "projects",
        public_project(project, include_details=False),
    )


def publish_projects_progress_snapshot(*, initialize: bool = False) -> str:
    return progress_tracker.synchronize(
        "projects",
        projects_progress_payload(),
        initialize=initialize,
    )


def progress_payload(
    include_projects: bool,
    include_news: bool,
    previous_cursor: str = "",
) -> Dict[str, object]:
    sections = []
    if include_projects:
        sections.append("projects")
    if include_news:
        sections.append("news")

    delta = progress_tracker.delta(previous_cursor, sections)
    if delta is not None:
        return delta

    payload: Dict[str, object] = {}
    if include_projects:
        project_items = projects_progress_payload()
        progress_tracker.synchronize("projects", project_items)
        payload["replace_projects"] = True
        payload["upsert_projects"] = project_items
    if include_news:
        news_items = news_progress_payload()
        progress_tracker.synchronize("news", news_items)
        payload["replace_news"] = True
        payload["upsert_news"] = news_items
    payload["cursor"] = progress_tracker.cursor
    return payload


def publish_news_monitor_progress(monitor: Dict[str, object]) -> None:
    from services.news import public_news_monitor
    progress_tracker.publish(
        "news",
        public_news_monitor(monitor, include_details=False),
    )


def publish_news_brand_progress(monitor: Dict[str, object]) -> None:
    group = clean_text(str(monitor.get("group") or ""))
    brand = clean_text(str(monitor.get("brand") or ""))
    with news_lock:
        brand_monitors = [
            item
            for item in news_settings.get("monitors", [])
            if isinstance(item, dict)
            and clean_text(str(item.get("group") or "")) == group
            and clean_text(str(item.get("brand") or "")) == brand
        ]
        for item in brand_monitors:
            publish_news_monitor_progress(item)


def publish_news_progress_snapshot(*, initialize: bool = False) -> str:
    return progress_tracker.synchronize(
        "news",
        news_progress_payload(),
        initialize=initialize,
    )


def public_news_monitor_progress(monitor: Dict[str, object]) -> Dict[str, object]:
    from services.news import public_news_monitor
    public_monitor = public_news_monitor(monitor, include_details=True)
    return {
        "id": str(public_monitor["id"]),
        "state": public_monitor["state"],
    }
