"""Unified log storage, cleanup and log API."""



from parser_app.runtime import *  # noqa: F401,F403



def write_logs_file(data: List[Dict[str, object]]) -> None:
    LOGS_FILE.parent.mkdir(exist_ok=True)
    LOGS_FILE.write_text(json.dumps(repair_mojibake(data), ensure_ascii=False, indent=2), encoding="utf-8")

def append_unified_log(item: Dict[str, object]) -> None:
    item = repair_mojibake(item)
    LOG_DIR.mkdir(exist_ok=True)
    timestamp = str(item.get("time") or datetime.now(MSK_TZ).isoformat(timespec="seconds"))
    level = str(item.get("level") or "info").upper()
    project_name = repair_mojibake_text(item.get("project_name") or item.get("project_id") or "system")
    message = repair_mojibake_text(item.get("message") or "")
    line = f"{timestamp} [{level}] {project_name}: {message}\n"
    try:
        with UNIFIED_LOG_LOCK:
            UNIFIED_LOG_FILE.open("a", encoding="utf-8").write(line)
    except OSError:
        print(line, end="", flush=True)

def read_logs_file() -> List[Dict[str, object]]:
    if not LOGS_FILE.exists():
        return []
    try:
        data = json.loads(LOGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [repair_mojibake(item) for item in data if isinstance(item, dict)]

def get_log_auto_cleanup() -> bool:
    with session_scope() as db_session:
        app_setting = db_session.get(AppSetting, 1)
        return bool(app_setting.auto_cleanup) if app_setting else False

def set_log_auto_cleanup(value: bool) -> bool:
    global LOG_AUTO_CLEANUP
    LOG_AUTO_CLEANUP = bool(value)
    with session_scope() as db_session:
        app_setting = db_session.get(AppSetting, 1)
        if app_setting is None:
            app_setting = AppSetting(id=1)
            db_session.add(app_setting)
        app_setting.auto_cleanup = LOG_AUTO_CLEANUP
    return LOG_AUTO_CLEANUP

def log_time_from_path(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, MSK_TZ).isoformat(timespec="seconds")
    except OSError:
        return datetime.now(MSK_TZ).isoformat(timespec="seconds")

def read_tail_lines(path: Path, limit: int = LOG_TAIL_LINES) -> List[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if limit > 0:
        return lines[-limit:]
    return lines

def read_unified_log_file() -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for line in read_tail_lines(UNIFIED_LOG_FILE):
        line = line.strip()
        if not line:
            continue
        match = UNIFIED_LOG_RE.match(line)
        if match:
            entries.append(
                repair_mojibake(
                    {
                        "time": match.group("time"),
                        "level": match.group("level").lower(),
                        "project_name": match.group("project_name"),
                        "message": match.group("message"),
                    }
                )
            )
            continue
        entries.append(
            repair_mojibake(
                {
                    "time": log_time_from_path(UNIFIED_LOG_FILE),
                    "level": "info",
                    "project_name": UNIFIED_LOG_FILE.name,
                    "message": line,
                }
            )
        )
    return entries

def read_plain_log_file(path: Path, project_name: str, level: str) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    timestamp = log_time_from_path(path)
    for line in read_tail_lines(path):
        line = line.strip()
        if not line:
            continue
        entries.append(
            repair_mojibake(
                {
                    "time": timestamp,
                    "level": level,
                    "project_name": project_name,
                    "message": line,
                }
            )
        )
    return entries

def iter_server_log_files() -> Iterable[Path]:
    for directory in (LOG_DIR / "server-output", LOG_DIR / "server-error"):
        if not directory.exists():
            continue
        try:
            files = sorted(
                [path for path in directory.iterdir() if path.is_file()],
                key=lambda item: item.stat().st_mtime,
            )
        except OSError:
            continue
        yield from files

def combined_log_entries() -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    entries.extend(read_logs_file())
    entries.extend(read_unified_log_file())
    entries.extend(read_plain_log_file(LOG_DIR / "flask-error.log", "flask-error.log", "error"))
    for path in iter_server_log_files():
        level = "error" if path.parent.name == "server-error" else "info"
        entries.extend(read_plain_log_file(path, path.name, level))

    deduped: List[Dict[str, object]] = []
    seen: Set[tuple[str, str, str, str]] = set()
    for item in entries:
        normalized = repair_mojibake(item)
        key = (
            str(normalized.get("time") or ""),
            str(normalized.get("level") or ""),
            str(normalized.get("project_name") or normalized.get("project_id") or ""),
            str(normalized.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped

def is_recent_log_entry(item: Dict[str, object], cutoff: float) -> bool:
    try:
        return datetime.fromisoformat(str(item.get("time") or "")).timestamp() >= cutoff
    except (TypeError, ValueError):
        return True

def log_line_timestamp(line: str) -> Optional[float]:
    match = re.match(r"^(?:\[(?P<bracket>[^\]]+)\]|(?P<plain>\S+))", line.strip())
    if not match:
        return None
    raw_value = match.group("bracket") or match.group("plain")
    try:
        return datetime.fromisoformat(raw_value).timestamp()
    except ValueError:
        return None

def iter_runtime_log_files() -> Iterable[Path]:
    for path in (LOGS_FILE, UNIFIED_LOG_FILE, LOG_DIR / "flask-error.log"):
        if path.exists() and path.is_file():
            yield path
    yield from iter_server_log_files()

def clear_runtime_log_files() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    write_logs_file([])
    for path in iter_runtime_log_files():
        if path == LOGS_FILE:
            continue
        try:
            if path.parent.name in {"server-output", "server-error"}:
                path.unlink()
            else:
                path.write_text("", encoding="utf-8")
        except OSError:
            try:
                path.write_text("", encoding="utf-8")
            except OSError:
                continue

def prune_text_log_file(path: Path, cutoff: float) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return
    filtered_lines = []
    for line in lines:
        timestamp = log_line_timestamp(line)
        if timestamp is None or timestamp >= cutoff:
            filtered_lines.append(line)
    if len(filtered_lines) == len(lines):
        return
    try:
        path.write_text("".join(filtered_lines), encoding="utf-8")
    except OSError:
        return

def prune_old_log_files(cutoff: float) -> None:
    prune_text_log_file(UNIFIED_LOG_FILE, cutoff)
    prune_text_log_file(LOG_DIR / "flask-error.log", cutoff)
    for path in iter_server_log_files():
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue

def save_logs() -> None:
    with projects_lock:
        data = []
        for project in projects.values():
            data.extend(project.get("logs", []))
    with news_lock:
        data.extend(news_settings.get("logs", []) if isinstance(news_settings.get("logs"), list) else [])
    write_logs_file(data)

def logs_signature() -> str:
    parts = []
    for path in iter_runtime_log_files():
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            relative_path = path.relative_to(BASE_DIR)
        except ValueError:
            relative_path = path
        parts.append(f"{relative_path}:{stat.st_mtime_ns}:{stat.st_size}")
    if not parts:
        return "empty"
    return hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()

def load_logs() -> None:
    for item in read_logs_file():
        project_id = item.get("project_id")
        project = projects.get(project_id)
        if project:
            project.setdefault("logs", []).append(item)

def load_news_logs_from_file() -> List[Dict[str, object]]:
    return [
        item
        for item in read_logs_file()
        if str(item.get("project_id") or "").startswith("news")
    ]

def load_news_settings() -> None:
    global LOG_AUTO_CLEANUP
    with news_lock:
        if news_settings:
            return
        settings = default_news_settings()
        with session_scope() as session:
            donor_rows = session.scalars(
                select(Donor)
                .join(Brand, Donor.brand_id == Brand.id)
                .order_by(Brand.group_name, Brand.name, Donor.id)
            ).all()
            app_setting = session.get(AppSetting, 1)
            if app_setting:
                settings["auto_cleanup"] = bool(app_setting.auto_cleanup)
                LOG_AUTO_CLEANUP = bool(app_setting.auto_cleanup)
                if isinstance(app_setting.smtp, dict):
                    settings["smtp"] = merge_smtp_settings(dict(settings["smtp"]), app_setting.smtp)
                if isinstance(app_setting.feed_storage, list):
                    settings["feed_storage"] = app_setting.feed_storage
            own_sites = session.scalars(select(OwnSite).order_by(OwnSite.id)).all()
            if own_sites:
                settings["own_sites"] = [
                    {
                        "name": site.name or feed_source_label(site.feed_url),
                        "feed_url": site.feed_url,
                        "feed_generate_url": site.feed_generate_url,
                    }
                    for site in own_sites
                ]
                feed_urls = [site.feed_url for site in own_sites]
                generate_urls = [site.feed_generate_url for site in own_sites]
                settings["feed_urls"] = feed_urls
                settings["feed_generate_urls"] = generate_urls
                settings["feed_url"] = feed_urls[0]
                settings["feed_generate_url"] = generate_urls[0] if generate_urls else DEFAULT_FEED_GENERATE_URL
            settings["monitors"] = [donor_model_to_monitor(row) for row in donor_rows]
            ensure_brand_primary_flags(settings["monitors"])
            settings["logs"] = load_news_logs_from_file()
        news_settings.update(settings)
        save_news_settings()

@app.get("/api/logs")
def api_logs():
    ensure_storage()
    global LOG_AUTO_CLEANUP
    auto_cleanup = get_log_auto_cleanup()
    LOG_AUTO_CLEANUP = auto_cleanup

    json_logs = read_logs_file()
    if auto_cleanup:
        cutoff = time.time() - 7 * 24 * 60 * 60
        filtered_logs = [
            item
            for item in json_logs
            if is_recent_log_entry(item, cutoff)
        ]
        if len(filtered_logs) != len(json_logs):
            json_logs = filtered_logs
            write_logs_file(json_logs)
        prune_old_log_files(cutoff)
        with projects_lock:
            for project in projects.values():
                logs = project.get("logs", [])
                project["logs"] = [
                    item
                    for item in logs
                    if is_recent_log_entry(item, cutoff)
                ]
        with news_lock:
            logs = news_settings.get("logs", [])
            news_settings["logs"] = [
                item
                for item in logs
                if is_recent_log_entry(item, cutoff)
            ]

    all_logs = combined_log_entries()
    all_logs.sort(key=lambda item: item.get("time", ""))
    return jsonify(
        {
            "logs": all_logs,
            "auto_cleanup": auto_cleanup,
            "logs_signature": logs_signature(),
        }
    )

@app.delete("/api/logs")
def api_clear_logs():
    ensure_storage()
    with projects_lock:
        for project in projects.values():
            project["logs"] = []
    with news_lock:
        news_settings["logs"] = []
        save_news_settings()
    clear_runtime_log_files()
    return jsonify({"ok": True})

@app.post("/api/logs/settings")
def api_logs_settings():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    auto_cleanup = set_log_auto_cleanup(bool(payload.get("auto_cleanup")))
    with news_lock:
        news_settings["auto_cleanup"] = auto_cleanup
    return jsonify({"auto_cleanup": auto_cleanup})
