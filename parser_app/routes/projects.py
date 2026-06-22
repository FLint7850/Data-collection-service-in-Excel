"""Project-control API endpoints."""



from parser_app.runtime import *  # noqa: F401,F403



@app.get("/api/projects")
def api_projects():
    ensure_storage()
    with projects_lock:
        return jsonify(
            {
                "projects": [public_project(project) for project in projects.values()],
                "connection_methods": public_connection_methods(),
            }
        )

@app.post("/api/projects")
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

@app.patch("/api/projects/<project_id>")
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
        if "product_url_filters" in payload:
            project["product_url_filters"] = normalize_patterns(payload.get("product_url_filters"))
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
        if "auto_cleanup" in payload:
            project["auto_cleanup"] = bool(payload.get("auto_cleanup"))
        reset_project_state_after_form_save(project)
        save_projects()
    return jsonify({"project": public_project(project)})

@app.delete("/api/projects/<project_id>")
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

@app.get("/api/projects/<project_id>/exclusions")
def api_project_exclusions(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"exclusions": project.get("exclusions", [])})

@app.post("/api/projects/<project_id>/exclusions")
def api_project_add_exclusion(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "Пустое исключение"}), 400
    with projects_lock:
        exclusions = project.setdefault("exclusions", [])
        if pattern not in exclusions:
            exclusions.append(pattern)
            save_projects()
    return jsonify({"exclusions": project.get("exclusions", [])})

@app.delete("/api/projects/<project_id>/exclusions/<int:index>")
def api_project_delete_exclusion(project_id: str, index: int):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    with projects_lock:
        exclusions = project.setdefault("exclusions", [])
        if index < 0 or index >= len(exclusions):
            return jsonify({"error": "Исключение не найдено"}), 404
        exclusions.pop(index)
        save_projects()
    return jsonify({"exclusions": project.get("exclusions", [])})

@app.get("/api/projects/<project_id>/product-url-filters")
def api_project_product_url_filters(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"product_url_filters": project.get("product_url_filters", [])})

@app.post("/api/projects/<project_id>/product-url-filters")
def api_project_add_product_url_filter(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "Пустой фильтр ссылки"}), 400
    with projects_lock:
        filters = project.setdefault("product_url_filters", [])
        if pattern not in filters:
            filters.append(pattern)
            save_projects()
    return jsonify({"product_url_filters": project.get("product_url_filters", [])})

@app.delete("/api/projects/<project_id>/product-url-filters/<int:index>")
def api_project_delete_product_url_filter(project_id: str, index: int):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    with projects_lock:
        filters = project.setdefault("product_url_filters", [])
        if index < 0 or index >= len(filters):
            return jsonify({"error": "Фильтр ссылки не найден"}), 404
        filters.pop(index)
        save_projects()
    return jsonify({"product_url_filters": project.get("product_url_filters", [])})

def start_project(project: Dict[str, object], resume: bool = False) -> Dict[str, object]:
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
    if crawler:
        crawler.run_id = int(project["run_id"])
        crawler.stop_signal = project["stop_event"]
        crawler.finish_signal = project["finish_event"]
        crawler.thread_count = parse_thread_count(project.get("thread_count", 4))
        crawler.exclusions = list(project.get("exclusions", DEFAULT_EXCLUSIONS))
        crawler.extraction_rules = normalize_extraction_rules(project.get("extraction_rules", {}))
        crawler.product_url_filters = product_url_filter_patterns(project.get("product_url_filters", []), crawler.extraction_rules)
        crawler.connection_method = normalize_connection_method(project.get("connection_method"))
        crawler.auto_connection_fallback = bool(project.get("auto_connection_fallback", True))
        crawler.active_connection_method = crawler.connection_method
        crawler.connection_method_state["active_method"] = crawler.connection_method
        crawler.excel_finalized = False
    else:
        reset_project_state(project, "running")
        crawler = ProductSiteCrawler(
            list(project.get("start_urls", [DEFAULT_START_URL])),
            int(project["run_id"]),
            project["stop_event"],
            project["finish_event"],
            parse_thread_count(project.get("thread_count", 4)),
            project=project,
            exclusions=list(project.get("exclusions", DEFAULT_EXCLUSIONS)),
            product_url_filters=list(project.get("product_url_filters", [])),
            extraction_rules=normalize_extraction_rules(project.get("extraction_rules", {})),
            connection_method=project.get("connection_method", "requests"),
            auto_connection_fallback=bool(project.get("auto_connection_fallback", True)),
        )
        project["crawler"] = crawler

    def target() -> None:
        try:
            crawler.run(resume=resume)
        except Exception as exc:  # noqa: BLE001
            update_project_state(project, status="error", error=str(exc), currenturl="", download_ready=False)
            add_project_log(project, f"Критическая ошибка: {exc}", "error")

    worker_thread = threading.Thread(target=target, daemon=True)
    project["worker_thread"] = worker_thread
    worker_thread.start()
    add_project_log(project, "Продолжение поставлено в очередь" if resume else "Сбор поставлен в очередь запуска", "info")
    return project["state"]

@app.post("/api/projects/<project_id>/start")
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
        if "extraction_rules" in payload:
            project["extraction_rules"] = normalize_extraction_rules(payload.get("extraction_rules"))
        if "thread_count" in payload:
            project["thread_count"] = parse_thread_count(payload.get("thread_count"))
        if "connection_method" in payload:
            project["connection_method"] = normalize_connection_method(payload.get("connection_method"))
        if "auto_connection_fallback" in payload:
            project["auto_connection_fallback"] = bool(payload.get("auto_connection_fallback"))
        save_projects()

    try:
        state = start_project(project)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(state)

@app.post("/api/projects/<project_id>/pause")
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
        crawler.finish_with_excel(partial=True)
    add_project_log(project, "Сбор приостановлен с формированием CSV", "warning")
    return jsonify(project["state"])

@app.post("/api/projects/<project_id>/soft-pause")
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
    update_project_state(project, error="Ставлю сбор на паузу...", currenturl="")
    add_project_log(project, "Запрошена обычная пауза", "warning")
    return jsonify(project["state"])

@app.post("/api/projects/<project_id>/resume")
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

@app.post("/api/projects/<project_id>/stop")
def api_project_stop(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    stop_event = project.get("stop_event")
    if isinstance(stop_event, threading.Event):
        stop_event.set()
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
                "eta_seconds": None,
                "finished_at": now_iso(),
                "paused_with_result": False,
            }
        )
        project["state"] = state
        save_projects()
    add_project_log(project, "Сбор остановлен", "warning")
    return jsonify(project["state"])

@app.post("/api/projects/<project_id>/restart")
def api_project_restart(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    stop_event = project.get("stop_event")
    if isinstance(stop_event, threading.Event):
        stop_event.set()
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
