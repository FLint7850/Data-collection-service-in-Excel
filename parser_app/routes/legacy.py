"""Compatibility endpoints and global scan event stream."""



from parser_app.runtime import *  # noqa: F401,F403



def reset_state(status: str = "idle", run_id: Optional[int] = None, thread_count: Optional[int] = None) -> None:
    with state_lock:
        if run_id is not None and run_id != active_run_id:
            return
        current_thread_count = thread_count or int(scan_state.get("thread_count", 4) or 4)
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
                "thread_count": current_thread_count,
            }
        )

def update_state(run_id: Optional[int] = None, **kwargs: object) -> None:
    with state_lock:
        if run_id is not None and run_id != active_run_id:
            return
        scan_state.update(kwargs)

def snapshot_state() -> Dict[str, object]:
    with state_lock:
        return dict(scan_state)

@app.post("/start")
def start_scan():
    global active_crawler, active_finish_event, active_run_id, active_stop_event, worker_thread

    current_status = snapshot_state()["status"]
    if current_status == "running" and worker_thread and worker_thread.is_alive():
        return jsonify({"error": "Сбор уже выполняется"}), 409

    payload = request.get_json(silent=True) or {}
    start_url = str(payload.get("start_url") or DEFAULT_START_URL).strip()
    thread_count = parse_thread_count(payload.get("thread_count"))

    with state_lock:
        active_run_id += 1
        run_id = active_run_id
        active_stop_event = threading.Event()
        active_finish_event = threading.Event()
        stop_signal = active_stop_event
        finish_signal = active_finish_event

    reset_state("running", thread_count=thread_count)

    crawler = ProductSiteCrawler([start_url], run_id, stop_signal, finish_signal, thread_count)
    active_crawler = crawler

    def target() -> None:
        try:
            crawler.run()
        except Exception as exc:  # noqa: BLE001 - показываем ошибку пользователю в интерфейсе.
            update_state(run_id, status="error", error=str(exc), currenturl="", download_ready=False)

    worker_thread = threading.Thread(target=target, daemon=True)
    worker_thread.start()
    return jsonify(snapshot_state())

@app.post("/stop")
def stop_scan():
    global active_crawler, active_run_id

    active_stop_event.set()
    with state_lock:
        active_run_id += 1
        active_crawler = None
    reset_state("idle")
    return jsonify(snapshot_state())

@app.post("/pause")
def pause_scan_with_result():
    global active_crawler, active_run_id

    if snapshot_state()["status"] != "running":
        return jsonify({"error": "Сбор не выполняется"}), 409

    active_finish_event.set()
    active_stop_event.set()
    crawler = active_crawler
    if crawler:
        crawler.finish_with_excel(partial=True)
        with state_lock:
            active_run_id += 1
            active_crawler = None
        return jsonify(snapshot_state())

    update_state(
        active_run_id,
        error="Останавливаю сбор и формирую Excel по уже найденным товарам...",
        currenturl="",
    )
    return jsonify(snapshot_state())

@app.post("/restart")
def restart_scan():
    global active_crawler, active_run_id

    active_stop_event.set()
    with state_lock:
        active_run_id += 1
        active_crawler = None
    reset_state("idle")
    return start_scan()

@app.get("/progress")
def progress_stream():
    def stream():
        while True:
            ensure_storage()
            with projects_lock:
                data = json.dumps(
                    {
                        "projects": [public_project(project) for project in projects.values()],
                        "news": public_news_settings(),
                        "connection_methods": public_connection_methods(),
                        "logs_signature": logs_signature(),
                    },
                    ensure_ascii=False,
                )
            yield f"event: progress\ndata: {data}\n\n"
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")

@app.get("/download")
def download_excel():
    current_state = snapshot_state()
    filename = str(current_state.get("filename") or "")
    path = EXPORT_DIR / filename
    if not filename or not path.exists():
        return jsonify({"error": "Файл еще не готов"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(filename))

@app.get("/api/projects/<project_id>/download")
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
