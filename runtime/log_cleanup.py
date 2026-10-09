"""Daily log retention independent of requests to the log viewer."""

import logging
import threading

from services.log_service import run_daily_log_cleanup


_logger = logging.getLogger(__name__)
_scheduler_lock = threading.Lock()
_scheduler_thread: threading.Thread | None = None
_poll_seconds = 60


def _cleanup_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            run_daily_log_cleanup()
        except Exception:
            _logger.exception("Не удалось выполнить фоновую очистку логов; повтор через минуту")
        stop_event.wait(_poll_seconds)


def start_log_cleanup_scheduler() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return
        _scheduler_thread = threading.Thread(
            target=_cleanup_loop,
            args=(threading.Event(),),
            name="log-cleanup-scheduler",
            daemon=True,
        )
        _scheduler_thread.start()
