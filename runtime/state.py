"""Process-local runtime state shared by scanners and progress endpoints."""

import threading
from typing import Dict, Optional

from config import env_int
from progress_tracker import ProgressTracker


state_lock = threading.RLock()
projects_lock = threading.RLock()
news_lock = threading.RLock()
file_import_lock = threading.RLock()
feed_comparison_lock = threading.RLock()

active_stop_event = threading.Event()
active_finish_event = threading.Event()
file_import_stop_event = threading.Event()
feed_comparison_stop_event = threading.Event()

active_run_id = 0
worker_thread: Optional[threading.Thread] = None
file_import_worker_thread: Optional[threading.Thread] = None
feed_comparison_worker_thread: Optional[threading.Thread] = None
news_scheduler_thread: Optional[threading.Thread] = None
active_crawler = None

projects: Dict[str, Dict[str, object]] = {}
news_settings: Dict[str, object] = {}

FEED_STORAGE_LOCK = threading.RLock()
feed_snapshot_cache: Dict[str, object] = {"signature": (), "created_at": 0.0, "feeds": []}
connection_method_cache_lock = threading.Lock()
connection_method_cache: Dict[str, object] = {"loaded_at": 0.0, "methods": []}

news_stop_events: Dict[str, threading.Event] = {}
news_stop_modes: Dict[str, str] = {}
news_scan_threads: Dict[str, threading.Thread] = {}
news_browser_sessions: Dict[str, object] = {}
news_state_persisted_at: Dict[str, float] = {}

progress_tracker = ProgressTracker(
    journal_limit=env_int("PROGRESS_REVISION_JOURNAL_LIMIT", 4096, minimum=128, maximum=100_000)
)

PROJECT_PROGRESS_FIELDS = (
    "totalprocessed", "processed_products", "found_products", "in_memory_products",
    "queue_size", "active_tasks", "skipped", "failed_pages",
)
NEWS_PROGRESS_FIELDS = (
    "processed", "found_products", "candidate_products", "compared_products",
    "in_memory_products", "queue_size", "active_tasks", "failed_pages", "availability_skipped",
)

scan_state: Dict[str, object] = {
    "status": "idle",
    "percent": 0,
    "currenturl": "",
    "totalprocessed": 0,
    "processed_products": 0,
    "found_products": 0,
    "skipped": 0,
    "error": "",
    "download_ready": False,
    "download_url": "",
    "filename": "",
    "thread_count": 4,
}


def reset_state(status: str = "idle", run_id: Optional[int] = None, thread_count: Optional[int] = None) -> None:
    global active_run_id
    with state_lock:
        if run_id is not None:
            active_run_id = run_id
        scan_state.update(
            {
                "status": status,
                "percent": 0,
                "currenturl": "",
                "totalprocessed": 0,
                "processed_products": 0,
                "found_products": 0,
                "skipped": 0,
                "error": "",
                "download_ready": False,
                "download_url": "",
                "filename": "",
            }
        )
        if thread_count is not None:
            scan_state["thread_count"] = thread_count


def update_state(run_id: Optional[int] = None, **kwargs: object) -> None:
    with state_lock:
        if run_id is not None and run_id != active_run_id:
            return
        scan_state.update(kwargs)
