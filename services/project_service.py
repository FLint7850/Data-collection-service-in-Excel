"""Extracted application service module."""

from services.core_service import (
    DEFAULT_EXCLUSIONS,
    DEFAULT_START_URL,
    Dict,
    EXPORT_DIR,
    List,
    Optional,
    PROJECT_PROGRESS_FIELDS,
    Path,
    Project,
    csv,
    datetime,
    delete,
    ensure_storage,
    is_debug_visible_method,
    normalize_connection_method,
    normalize_extraction_rules,
    normalize_patterns,
    normalize_start_urls,
    output_text,
    parse_db_int,
    projects,
    projects_lock,
    repair_mojibake,
    repair_mojibake_text,
    safe_filename,
    select,
    session_scope,
    threading,
    time,
    uuid,
)


def make_state(thread_count: int = 4) -> Dict[str, object]:
    return {
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
        "thread_count": thread_count,
        "started_at": "",
        "finished_at": "",
        "elapsed_seconds": 0,
        "paused_with_result": False,
    }


def make_project(name: str = "Проект 1", start_urls: Optional[List[str]] = None) -> Dict[str, object]:
    project_id = uuid.uuid4().hex[:10]
    return {
        "id": project_id,
        "name": name,
        "start_urls": start_urls or [DEFAULT_START_URL],
        "thread_count": 4,
        "exclusions": DEFAULT_EXCLUSIONS.copy(),
        "product_url_filters": [],
        "product_url_exclusions": [],
        "extraction_rules": {},
        "state": make_state(4),
        "logs": [],
        "auto_cleanup": False,
        "connection_method": normalize_connection_method(None),
        "auto_connection_fallback": True,
        "persist_profile": False,
        "worker_thread": None,
        "stop_event": threading.Event(),
        "finish_event": threading.Event(),
        "crawler": None,
        "run_id": 0,
    }


def public_project(project: Dict[str, object], include_details: bool = True) -> Dict[str, object]:
    from services.progress_service import stable_project_state
    state = repair_mojibake(stable_project_state(project, dict(project["state"])))
    filename = str(state.get("filename") or "")
    if filename and (EXPORT_DIR / filename).exists():
        state["download_ready"] = True
    payload = {
        "id": project["id"],
        "name": repair_mojibake_text(project["name"]),
        "start_urls_count": len(project.get("start_urls", [])),
        "thread_count": project["thread_count"],
        "state": state,
        "connection_method": project.get("connection_method", "requests"),
    }
    if not include_details:
        return payload
    payload.update(
        {
            "start_urls": project["start_urls"],
            "exclusions": project["exclusions"],
            "product_url_filters": project.get("product_url_filters", []),
            "product_url_exclusions": project.get("product_url_exclusions", []),
            "extraction_rules": project.get("extraction_rules", {}),
            "auto_cleanup": project.get("auto_cleanup", False),
            "auto_connection_fallback": project.get("auto_connection_fallback", True),
            "persist_profile": bool(project.get("persist_profile", False)),
        }
    )
    return payload


def project_model_to_dict(row: Project) -> Dict[str, object]:
    thread_count = parse_thread_count(row.thread_count)
    state = {**make_state(thread_count), **(row.state or {})}
    state.pop("eta_seconds", None)
    project = {
        "id": str(row.id),
        "name": row.name,
        "start_urls": normalize_start_urls(row.start_urls or [DEFAULT_START_URL]),
        "thread_count": thread_count,
        "exclusions": normalize_patterns(row.exclusions or DEFAULT_EXCLUSIONS),
        "product_url_filters": normalize_patterns(row.product_url_filters or []),
        "product_url_exclusions": normalize_patterns(getattr(row, "product_url_exclusions", None) or []),
        "extraction_rules": normalize_extraction_rules(row.extraction_rules or {}),
        "state": state,
        "logs": [],
        "auto_cleanup": bool(row.auto_cleanup),
        "connection_method": normalize_connection_method(row.connection_method),
        "auto_connection_fallback": bool(row.auto_connection_fallback),
        "persist_profile": bool(getattr(row, "persist_profile", False)),
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
    row.product_url_exclusions = normalize_patterns(project.get("product_url_exclusions", []))
    row.extraction_rules = normalize_extraction_rules(project.get("extraction_rules", {}))
    row.state = dict(project.get("state") or make_state(row.thread_count))
    row.auto_cleanup = bool(project.get("auto_cleanup", False))
    row.connection_method = normalize_connection_method(project.get("connection_method"))
    row.auto_connection_fallback = bool(project.get("auto_connection_fallback", True))
    row.persist_profile = bool(project.get("persist_profile", False))
    session.flush()
    return int(row.id)


def save_projects() -> None:
    from services.progress_service import publish_projects_progress_snapshot
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
        publish_projects_progress_snapshot()


def load_projects() -> None:
    from services.log_service import load_logs
    from services.progress_service import publish_projects_progress_snapshot
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
        publish_projects_progress_snapshot(initialize=True)


def get_project(project_id: str) -> Optional[Dict[str, object]]:
    ensure_storage()
    with projects_lock:
        return projects.get(project_id)


def update_project_state(project: Dict[str, object], **kwargs: object) -> None:
    from services.progress_service import has_positive_progress_value, is_active_status, merge_stable_progress_state, publish_project_progress
    with projects_lock:
        state = dict(project.get("state", make_state(parse_thread_count(project.get("thread_count", 4)))))
        state.update(kwargs)
        if is_active_status(state.get("status")):
            previous = project.get("_last_progress_state")
            state = merge_stable_progress_state(
                state,
                previous if isinstance(previous, dict) else None,
                PROJECT_PROGRESS_FIELDS,
            )
            if has_positive_progress_value(state, PROJECT_PROGRESS_FIELDS) or str(state.get("currenturl") or "").strip():
                project["_last_progress_state"] = dict(state)
        else:
            project.pop("_last_progress_state", None)
        project["state"] = state
        publish_project_progress(project)


def reset_project_state(project: Dict[str, object], status: str = "idle") -> None:
    from services.progress_service import publish_project_progress
    thread_count = parse_thread_count(project.get("thread_count", 4))
    state = make_state(thread_count)
    state["status"] = status
    project["state"] = state
    project.pop("_last_progress_state", None)
    publish_project_progress(project)


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
    from services.log_service import append_unified_log, save_logs
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
    from services.news_service import resolve_export_file
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


def parse_thread_count(value: object) -> int:
    try:
        return max(1, min(int(value or 4), 16))
    except (TypeError, ValueError):
        return 4


def project_runtime_thread_count(project: Dict[str, object]) -> int:
    method = normalize_connection_method(project.get("connection_method"))
    if bool(project.get("persist_profile", False)) or is_debug_visible_method(method):
        return 1
    return parse_thread_count(project.get("thread_count", 4))


def get_project_row(session, public_id: object) -> Optional[Project]:
    db_id = parse_db_int(public_id)
    if db_id is not None:
        row = session.get(Project, db_id)
        if row is not None:
            return row
    legacy_id = str(public_id or "").strip()
    if not legacy_id:
        return None
    return session.scalar(select(Project).where(Project.legacy_id == legacy_id))


def create_export_file(rows: List[Dict[str, str]], project: Optional[Dict[str, object]] = None) -> Path:
    if project:
        filename = project_csv_filename(project)
    else:
        filename = f"export_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}.csv"
    path = EXPORT_DIR / filename

    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";")
        writer.writerow(["URL товара", "_MODEL_", "_PRICE_"])
        for row in rows:
            writer.writerow([output_text(row.get("url", "")), output_text(row.get("model", "")), output_text(row.get("price", ""))])

    return path


__all__ = ['make_state', 'make_project', 'public_project', 'project_model_to_dict', 'upsert_project_model', 'save_projects', 'load_projects', 'get_project', 'update_project_state', 'reset_project_state', 'project_worker_alive', 'reset_project_state_after_form_save', 'add_project_log', 'project_csv_prefix', 'project_csv_filename', 'delete_project_csv_for_project', 'parse_thread_count', 'project_runtime_thread_count', 'get_project_row', 'create_export_file']
