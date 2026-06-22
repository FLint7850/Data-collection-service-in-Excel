"""Project persistence, runtime state and project logs."""



from parser_app.runtime import *  # noqa: F401,F403



def make_project(name: str = "Проект 1", start_urls: Optional[List[str]] = None) -> Dict[str, object]:
    project_id = uuid.uuid4().hex[:10]
    return {
        "id": project_id,
        "name": name,
        "start_urls": start_urls or [DEFAULT_START_URL],
        "thread_count": 4,
        "exclusions": DEFAULT_EXCLUSIONS.copy(),
        "product_url_filters": [],
        "extraction_rules": {},
        "state": make_state(4),
        "logs": [],
        "auto_cleanup": False,
        "connection_method": normalize_connection_method(None),
        "auto_connection_fallback": True,
        "worker_thread": None,
        "stop_event": threading.Event(),
        "finish_event": threading.Event(),
        "crawler": None,
        "run_id": 0,
    }

def public_project(project: Dict[str, object]) -> Dict[str, object]:
    state = repair_mojibake(dict(project["state"]))
    filename = str(state.get("filename") or "")
    if filename and (EXPORT_DIR / filename).exists():
        state["download_ready"] = True
    return {
        "id": project["id"],
        "name": repair_mojibake_text(project["name"]),
        "start_urls": project["start_urls"],
        "thread_count": project["thread_count"],
        "exclusions": project["exclusions"],
        "product_url_filters": project.get("product_url_filters", []),
        "extraction_rules": project.get("extraction_rules", {}),
        "state": state,
        "auto_cleanup": project.get("auto_cleanup", False),
        "connection_method": project.get("connection_method", "requests"),
        "auto_connection_fallback": project.get("auto_connection_fallback", True),
    }

def project_model_to_dict(row: Project) -> Dict[str, object]:
    thread_count = parse_thread_count(row.thread_count)
    project = {
        "id": str(row.id),
        "name": row.name,
        "start_urls": normalize_start_urls(row.start_urls or [DEFAULT_START_URL]),
        "thread_count": thread_count,
        "exclusions": normalize_patterns(row.exclusions or DEFAULT_EXCLUSIONS),
        "product_url_filters": normalize_patterns(row.product_url_filters or []),
        "extraction_rules": normalize_extraction_rules(row.extraction_rules or {}),
        "state": {**make_state(thread_count), **(row.state or {})},
        "logs": [],
        "auto_cleanup": bool(row.auto_cleanup),
        "connection_method": normalize_connection_method(row.connection_method),
        "auto_connection_fallback": bool(row.auto_connection_fallback),
        "worker_thread": None,
        "stop_event": threading.Event(),
        "finish_event": threading.Event(),
        "crawler": None,
        "run_id": 0,
    }
    if project["state"].get("status") == "running":
        project["state"]["status"] = "error"
        project["state"]["error"] = "Сбор был прерван перезапуском сервера. Запустите его снова."
    return project

def upsert_project_model(session, project: Dict[str, object]) -> int:
    row = get_project_row(session, project.get("id"))
    if row is None:
        legacy_id = str(project.get("id") or "").strip()
        row = Project(legacy_id=legacy_id if legacy_id and parse_db_int(legacy_id) is None else "", name=str(project.get("name") or "Проект"))
        session.add(row)
    row.name = str(project.get("name") or "Проект")
    row.start_urls = normalize_start_urls(project.get("start_urls") or DEFAULT_START_URL)
    row.thread_count = parse_thread_count(project.get("thread_count", 4))
    row.exclusions = normalize_patterns(project.get("exclusions", DEFAULT_EXCLUSIONS))
    row.product_url_filters = normalize_patterns(project.get("product_url_filters", []))
    row.extraction_rules = normalize_extraction_rules(project.get("extraction_rules", {}))
    row.state = dict(project.get("state") or make_state(row.thread_count))
    row.auto_cleanup = bool(project.get("auto_cleanup", False))
    row.connection_method = normalize_connection_method(project.get("connection_method"))
    row.auto_connection_fallback = bool(project.get("auto_connection_fallback", True))
    session.flush()
    return int(row.id)

def save_projects() -> None:
    with projects_lock:
        with session_scope() as session:
            current_ids = set()
            rekey: List[tuple[str, str]] = []
            for old_key, project in list(projects.items()):
                db_id = upsert_project_model(session, project)
                public_id = str(db_id)
                current_ids.add(db_id)
                if str(project.get("id")) != public_id:
                    project["id"] = public_id
                if old_key != public_id:
                    rekey.append((old_key, public_id))
            for old_key, new_key in rekey:
                projects[new_key] = projects.pop(old_key)
            if current_ids:
                session.execute(delete(Project).where(Project.id.not_in(current_ids)))

def load_projects() -> None:
    with projects_lock:
        if projects:
            return
        with session_scope() as session:
            rows = session.scalars(select(Project).order_by(Project.created_at, Project.id)).all()

        if not rows:
            project = make_project("Проект 1", [DEFAULT_START_URL])
            projects[project["id"]] = project
            save_projects()
        else:
            for row in rows:
                projects[str(row.id)] = project_model_to_dict(row)

        if not projects:
            project = make_project("Проект 1", [DEFAULT_START_URL])
            projects[project["id"]] = project
            save_projects()
        load_logs()

def get_project(project_id: str) -> Optional[Dict[str, object]]:
    ensure_storage()
    with projects_lock:
        return projects.get(project_id)

def update_project_state(project: Dict[str, object], **kwargs: object) -> None:
    with projects_lock:
        state = dict(project.get("state", make_state(parse_thread_count(project.get("thread_count", 4)))))
        state.update(kwargs)
        project["state"] = state

def reset_project_state(project: Dict[str, object], status: str = "idle") -> None:
    thread_count = parse_thread_count(project.get("thread_count", 4))
    state = make_state(thread_count)
    state["status"] = status
    project["state"] = state

def project_worker_alive(project: Dict[str, object]) -> bool:
    worker = project.get("worker_thread")
    return isinstance(worker, threading.Thread) and worker.is_alive()

def reset_project_state_after_form_save(project: Dict[str, object]) -> None:
    if project_worker_alive(project):
        return
    status = str((project.get("state") or {}).get("status") or "idle")
    if status in {"running", "queued", "stopping"}:
        return
    project["crawler"] = None
    project["stop_mode"] = ""
    reset_project_state(project, "idle")

def add_project_log(project: Dict[str, object], message: str, level: str = "info") -> None:
    with projects_lock:
        logs = project.setdefault("logs", [])
        item = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "project_id": project["id"],
            "project_name": repair_mojibake_text(project["name"]),
            "level": level,
            "message": repair_mojibake_text(message),
        }
        logs.append(item)
        append_unified_log(item)
        if project.get("auto_cleanup"):
            cutoff = time.time() - 7 * 24 * 60 * 60
            logs[:] = [
                item
                for item in logs
                if datetime.fromisoformat(item["time"]).timestamp() >= cutoff
            ]
        save_logs()

def project_csv_prefix(project: Optional[Dict[str, object]]) -> str:
    source = safe_filename(str((project or {}).get("name") or "project"))
    return f"{source}_"

def project_csv_filename(project: Optional[Dict[str, object]], created_at: Optional[datetime] = None) -> str:
    created_at = created_at or datetime.now()
    return f"{project_csv_prefix(project)}{created_at.strftime('%d-%m-%Y_%H-%M-%S')}.csv"

def delete_project_csv_for_project(project: Dict[str, object], keep_filename: str = "") -> None:
    keep_filename = str(keep_filename or "").strip()
    state = project.get("state", {}) if isinstance(project.get("state"), dict) else {}
    filenames = {
        keep_filename,
        str(state.get("filename") or ""),
    }
    prefix = project_csv_prefix(project)
    try:
        for path in EXPORT_DIR.glob(f"{prefix}*.csv"):
            if path.is_file() and path.name not in filenames:
                path.unlink(missing_ok=True)
    except OSError:
        pass
    for filename in filenames:
        if not filename or filename == keep_filename:
            continue
        path = resolve_export_file(filename)
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
