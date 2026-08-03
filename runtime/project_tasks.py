"""Extracted application service module."""

import shutil
import threading
from config import DEFAULT_EXCLUSIONS, DEFAULT_START_URL, PROJECT_PROFILE_DIR
from pathlib import Path
from services.connections import normalize_connection_method
from services.normalization import normalize_extraction_rules, normalize_patterns, safe_filename
from typing import Dict, Optional
from services.scraping import (
    BotasaurusBrowserSession,
    BotasaurusDebugVisibleSession,
    ProductSiteCrawler,
    product_url_filter_patterns,
)


def close_project_browser_session(project: Dict[str, object]) -> None:
    crawler = project.get("crawler")
    if isinstance(crawler, ProductSiteCrawler):
        crawler.close_browser_sessions()


def project_profile_storage_dir(project: Dict[str, object]) -> Path:
    project_id = safe_filename(str(project.get("id") or "project"))
    return PROJECT_PROFILE_DIR / project_id


def project_should_keep_browser_profile(project: Dict[str, object]) -> bool:
    if bool(project.get("persist_profile", False)):
        return True
    method = normalize_connection_method(project.get("connection_method"))
    return method == "protected-site" or bool(project.get("auto_connection_fallback", True))


def project_browser_profile_dir(project: Dict[str, object]) -> Optional[Path]:
    if not project_should_keep_browser_profile(project):
        return None
    return project_profile_storage_dir(project)


def cleanup_project_profile_if_disabled(project: Dict[str, object]) -> None:
    if project_should_keep_browser_profile(project):
        return
    profile_dir = project_profile_storage_dir(project)
    try:
        root = PROJECT_PROFILE_DIR.resolve()
        target = profile_dir.resolve()
        if target == root or root not in target.parents or not target.exists():
            return
        shutil.rmtree(target, ignore_errors=True)
    except Exception:
        pass


def start_project(project: Dict[str, object], resume: bool = False) -> Dict[str, object]:
    from services.projects import add_project_log, project_runtime_thread_count, reset_project_state
    worker = project.get("worker_thread")
    state = project.get("state", {})
    if isinstance(worker, threading.Thread) and worker.is_alive():
        if state.get("status") == "running":
            raise RuntimeError("Сбор уже выполняется")
        worker.join(timeout=2)
        if worker.is_alive():
            raise RuntimeError("Предыдущий поток еще завершается. Повторите через несколько секунд.")

    project["stop_event"] = threading.Event()
    project["finish_event"] = threading.Event()
    project["stop_mode"] = ""
    project["run_id"] = int(project.get("run_id", 0)) + 1

    crawler = project.get("crawler") if resume else None
    profile_dir = project_browser_profile_dir(project)
    runtime_thread_count = project_runtime_thread_count(project)
    if crawler:
        crawler.close_browser_sessions()
        cleanup_project_profile_if_disabled(project)
        crawler.run_id = int(project["run_id"])
        crawler.stop_signal = project["stop_event"]
        crawler.finish_signal = project["finish_event"]
        crawler.thread_count = runtime_thread_count
        crawler.exclusions = list(project.get("exclusions", DEFAULT_EXCLUSIONS))
        crawler.extraction_rules = normalize_extraction_rules(project.get("extraction_rules", {}))
        crawler.product_url_filters = product_url_filter_patterns(project.get("product_url_filters", []), crawler.extraction_rules)
        crawler.product_url_exclusions = normalize_patterns(project.get("product_url_exclusions", []))
        crawler.connection_method = normalize_connection_method(project.get("connection_method"))
        crawler.auto_connection_fallback = bool(project.get("auto_connection_fallback", True))
        crawler.profile_dir = profile_dir
        crawler.browser_session = BotasaurusBrowserSession(
            project["stop_event"],
            crawler.thread_count,
            profile_dir=crawler.profile_dir,
        )
        crawler.debug_visible_session = BotasaurusDebugVisibleSession(
            project["stop_event"],
            str(crawler.profile_dir) if crawler.profile_dir is not None else "protected_sites_debug_visible",
        )
        crawler.active_connection_method = crawler.connection_method
        crawler.connection_method_state["active_method"] = crawler.connection_method
        crawler.excel_finalized = False
    else:
        cleanup_project_profile_if_disabled(project)
        reset_project_state(project, "queued")
        crawler = ProductSiteCrawler(
            list(project.get("start_urls", [DEFAULT_START_URL])),
            int(project["run_id"]),
            project["stop_event"],
            project["finish_event"],
            runtime_thread_count,
            project=project,
            exclusions=list(project.get("exclusions", DEFAULT_EXCLUSIONS)),
            product_url_filters=list(project.get("product_url_filters", [])),
            product_url_exclusions=list(project.get("product_url_exclusions", [])),
            extraction_rules=normalize_extraction_rules(project.get("extraction_rules", {})),
            connection_method=project.get("connection_method", "requests"),
            auto_connection_fallback=bool(project.get("auto_connection_fallback", True)),
            profile_dir=profile_dir,
        )
        project["crawler"] = crawler

    def target() -> None:
        from services.projects import add_project_log, reset_project_state, update_project_state
        try:
            if resume:
                update_project_state(project, status="running", error="")
            else:
                reset_project_state(project, "running")
            crawler.run(resume=resume)
        except Exception as exc:  # noqa: BLE001
            update_project_state(project, status="error", error=str(exc), currenturl="", download_ready=False)
            add_project_log(project, f"Критическая ошибка: {exc}", "error")
        finally:
            if project.get("worker_thread") is threading.current_thread():
                project["worker_thread"] = None

    thread = threading.Thread(
        target=target,
        name=f"project-scan-{project['id']}",
        daemon=True,
    )
    project["worker_thread"] = thread
    thread.start()
    add_project_log(project, "Продолжение запущено" if resume else "Сбор запущен", "info")
    return project["state"]
