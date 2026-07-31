"""HTTP routes for this application area."""

from flask import Blueprint

from runtime.project_tasks import close_project_browser_session, start_project
from services.core_service import (
    DEFAULT_START_URL,
    EXPORT_DIR,
    ensure_storage,
    jsonify,
    normalize_connection_method,
    normalize_extraction_rules,
    normalize_patterns,
    normalize_start_urls,
    now_iso,
    output_text,
    projects,
    projects_lock,
    public_connection_methods,
    request,
    scan_dispatcher,
    send_file,
    threading,
)
from services.progress_service import register_progress_items
from services.project_service import (
    add_project_log,
    get_project,
    make_project,
    make_state,
    parse_thread_count,
    public_project,
    reset_project_state_after_form_save,
    save_projects,
    update_project_state,
)

bp = Blueprint("routes_projects", __name__)


@bp.get("/api/projects")
def api_projects():
    ensure_storage()
    summary = request.args.get("summary") == "1"
    with projects_lock:
        response = {
            "projects": [
                public_project(project, include_details=not summary)
                for project in projects.values()
            ],
            "connection_methods": public_connection_methods(),
        }
    if summary:
        response["progress_cursor"], _ = register_progress_items(
            project_items=response["projects"]
        )
    return jsonify(response)


@bp.get("/api/projects/<project_id>")
def api_get_project(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"project": public_project(project)})


@bp.post("/api/projects")
def api_create_project():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or f"Проект {len(projects) + 1}").strip()
    start_urls = normalize_start_urls(payload.get("start_urls") or DEFAULT_START_URL)
    project = make_project(name, start_urls)
    with projects_lock:
        projects[project["id"]] = project
        save_projects()
    add_project_log(project, "Проект создан", "success")
    return jsonify({"project": public_project(project)})


@bp.patch("/api/projects/<project_id>")
def api_update_project(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404

    payload = request.get_json(silent=True) or {}
    with projects_lock:
        if "name" in payload:
            project["name"] = str(payload.get("name") or project["name"]).strip() or project["name"]
        if "start_urls" in payload:
            project["start_urls"] = normalize_start_urls(payload.get("start_urls"))
        if "exclusions" in payload:
            project["exclusions"] = normalize_patterns(payload.get("exclusions"))
        if "product_url_filters" in payload:
            project["product_url_filters"] = normalize_patterns(payload.get("product_url_filters"))
        if "product_url_exclusions" in payload:
            project["product_url_exclusions"] = normalize_patterns(payload.get("product_url_exclusions"))
        if "extraction_rules" in payload:
            project["extraction_rules"] = normalize_extraction_rules(payload.get("extraction_rules"))
        if "thread_count" in payload:
            thread_count = parse_thread_count(payload.get("thread_count"))
            project["thread_count"] = thread_count
            state = dict(project["state"])
            state["thread_count"] = thread_count
            project["state"] = state
        if "connection_method" in payload:
            project["connection_method"] = normalize_connection_method(payload.get("connection_method"))
        if "auto_connection_fallback" in payload:
            project["auto_connection_fallback"] = bool(payload.get("auto_connection_fallback"))
        if "persist_profile" in payload:
            project["persist_profile"] = bool(payload.get("persist_profile"))
        if "auto_cleanup" in payload:
            project["auto_cleanup"] = bool(payload.get("auto_cleanup"))
        reset_project_state_after_form_save(project)
        save_projects()
    return jsonify({"project": public_project(project)})


@bp.delete("/api/projects/<project_id>")
def api_delete_project(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    with projects_lock:
        if len(projects) <= 1:
            return jsonify({"error": "Нельзя удалить последний проект"}), 400
        stop_event = project.get("stop_event")
        if isinstance(stop_event, threading.Event):
            stop_event.set()
        projects.pop(project_id, None)
        save_projects()
    return jsonify({"ok": True})


@bp.get("/api/projects/<project_id>/exclusions")
def api_project_exclusions(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"exclusions": project.get("exclusions", [])})


@bp.post("/api/projects/<project_id>/exclusions")
def api_project_add_exclusion(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "Пустое исключение"}), 400
    added = False
    with projects_lock:
        exclusions = project.setdefault("exclusions", [])
        if pattern not in exclusions:
            exclusions.append(pattern)
            added = True
            save_projects()
    return jsonify({"ok": True, "added": added, "pattern": pattern})


@bp.delete("/api/projects/<project_id>/exclusions/<int:index>")
def api_project_delete_exclusion(project_id: str, index: int):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    with projects_lock:
        exclusions = project.setdefault("exclusions", [])
        if index < 0 or index >= len(exclusions):
            return jsonify({"error": "Исключение не найдено"}), 404
        removed = exclusions.pop(index)
        save_projects()
    return jsonify({"ok": True, "removed": removed})


@bp.get("/api/projects/<project_id>/product-url-filters")
def api_project_product_url_filters(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"product_url_filters": project.get("product_url_filters", [])})


@bp.post("/api/projects/<project_id>/product-url-filters")
def api_project_add_product_url_filter(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "Пустой фильтр ссылки"}), 400
    added = False
    with projects_lock:
        filters = project.setdefault("product_url_filters", [])
        if pattern not in filters:
            filters.append(pattern)
            added = True
            save_projects()
    return jsonify({"ok": True, "added": added, "pattern": pattern})


@bp.delete("/api/projects/<project_id>/product-url-filters/<int:index>")
def api_project_delete_product_url_filter(project_id: str, index: int):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    with projects_lock:
        filters = project.setdefault("product_url_filters", [])
        if index < 0 or index >= len(filters):
            return jsonify({"error": "Фильтр ссылки не найден"}), 404
        removed = filters.pop(index)
        save_projects()
    return jsonify({"ok": True, "removed": removed})


@bp.get("/api/projects/<project_id>/product-url-exclusions")
def api_project_product_url_exclusions(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"product_url_exclusions": project.get("product_url_exclusions", [])})


@bp.post("/api/projects/<project_id>/product-url-exclusions")
def api_project_add_product_url_exclusion(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "Пустое исключение товарной ссылки"}), 400
    added = False
    with projects_lock:
        exclusions = project.setdefault("product_url_exclusions", [])
        if pattern not in exclusions:
            exclusions.append(pattern)
            added = True
            save_projects()
    return jsonify({"ok": True, "added": added, "pattern": pattern})


@bp.delete("/api/projects/<project_id>/product-url-exclusions/<int:index>")
def api_project_delete_product_url_exclusion(project_id: str, index: int):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    with projects_lock:
        exclusions = project.setdefault("product_url_exclusions", [])
        if index < 0 or index >= len(exclusions):
            return jsonify({"error": "Исключение товарной ссылки не найдено"}), 404
        removed = exclusions.pop(index)
        save_projects()
    return jsonify({"ok": True, "removed": removed})


@bp.post("/api/projects/<project_id>/start")
def api_project_start(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404

    payload = request.get_json(silent=True) or {}
    with projects_lock:
        if "start_urls" in payload:
            project["start_urls"] = normalize_start_urls(payload.get("start_urls"))
        if "product_url_filters" in payload:
            project["product_url_filters"] = normalize_patterns(payload.get("product_url_filters"))
        if "product_url_exclusions" in payload:
            project["product_url_exclusions"] = normalize_patterns(payload.get("product_url_exclusions"))
        if "extraction_rules" in payload:
            project["extraction_rules"] = normalize_extraction_rules(payload.get("extraction_rules"))
        if "thread_count" in payload:
            project["thread_count"] = parse_thread_count(payload.get("thread_count"))
        if "connection_method" in payload:
            project["connection_method"] = normalize_connection_method(payload.get("connection_method"))
        if "auto_connection_fallback" in payload:
            project["auto_connection_fallback"] = bool(payload.get("auto_connection_fallback"))
        if "persist_profile" in payload:
            project["persist_profile"] = bool(payload.get("persist_profile"))
        save_projects()

    try:
        state = start_project(project)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(state)


@bp.post("/api/projects/<project_id>/pause")
def api_project_pause(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    status = project.get("state", {}).get("status")
    if status not in {"running", "paused"}:
        return jsonify({"error": "Сбор не выполняется"}), 409
    finish_event = project.get("finish_event")
    stop_event = project.get("stop_event")
    project["stop_mode"] = "pause"
    if isinstance(finish_event, threading.Event):
        finish_event.set()
    if status == "running" and isinstance(stop_event, threading.Event):
        stop_event.set()
    crawler = project.get("crawler")
    if crawler:
        close_project_browser_session(project)
        crawler.finish_with_excel(partial=True)
    add_project_log(project, "Сбор приостановлен с формированием CSV", "warning")
    return jsonify(project["state"])


@bp.post("/api/projects/<project_id>/soft-pause")
def api_project_soft_pause(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    if project.get("state", {}).get("status") != "running":
        return jsonify({"error": "Сбор не выполняется"}), 409
    stop_event = project.get("stop_event")
    project["stop_mode"] = "pause"
    if isinstance(stop_event, threading.Event):
        stop_event.set()
    close_project_browser_session(project)
    update_project_state(project, error="Ставлю сбор на паузу...", currenturl="")
    add_project_log(project, "Запрошена обычная пауза", "warning")
    return jsonify(project["state"])


@bp.post("/api/projects/<project_id>/resume")
def api_project_resume(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    status = project.get("state", {}).get("status")
    if status not in {"paused", "partial"}:
        return jsonify({"error": "Продолжить можно только после паузы"}), 409
    try:
        state = start_project(project, resume=True)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(state)


@bp.post("/api/projects/<project_id>/stop")
def api_project_stop(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    scan_dispatcher.cancel(("project", str(project["id"])))
    stop_event = project.get("stop_event")
    if isinstance(stop_event, threading.Event):
        stop_event.set()
    close_project_browser_session(project)
    with projects_lock:
        project["stop_mode"] = "stop"
        project["run_id"] = int(project.get("run_id", 0)) + 1
        project["crawler"] = None
        state = dict(project.get("state") or make_state(parse_thread_count(project.get("thread_count", 4))))
        state.update(
            {
                "status": "idle",
                "currenturl": "",
                "active_urls": [],
                "active_tasks": 0,
                "queue_size": 0,
                "error": "",
                "finished_at": now_iso(),
                "paused_with_result": False,
            }
        )
        project["state"] = state
        save_projects()
    add_project_log(project, "Сбор остановлен", "warning")
    return jsonify(project["state"])


@bp.post("/api/projects/<project_id>/restart")
def api_project_restart(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    stop_event = project.get("stop_event")
    if isinstance(stop_event, threading.Event):
        stop_event.set()
    close_project_browser_session(project)
    worker = project.get("worker_thread")
    if isinstance(worker, threading.Thread) and worker.is_alive():
        with projects_lock:
            project["stop_mode"] = "stop"
            project["run_id"] = int(project.get("run_id", 0)) + 1
            project["crawler"] = None
        worker.join(timeout=3)
        if worker.is_alive():
            return jsonify({"error": "Предыдущий сбор еще завершается. Повторите перезапуск через несколько секунд."}), 409
    try:
        state = start_project(project)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(state)


@bp.get("/api/projects/<project_id>/download")
def download_project_csv(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    current_state = project.get("state", {})
    filename = str(current_state.get("filename") or "")
    path = EXPORT_DIR / filename
    if not filename or not path.exists():
        return jsonify({"error": "Файл еще не готов"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(filename))


