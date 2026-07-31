"""Extracted application service module."""

from services.core_service import (
    AppSetting,
    BASE_DIR,
    Dict,
    FETCH_DEBUG_HTML,
    FETCH_DEBUG_HTML_DIR,
    Iterable,
    LOGS_FILE,
    LOG_DIR,
    LOG_TAIL_LINES,
    List,
    MSK_TZ,
    Optional,
    Path,
    Set,
    UNIFIED_LOG_FILE,
    UNIFIED_LOG_LOCK,
    UNIFIED_LOG_RE,
    datetime,
    hashlib,
    html_lib,
    json,
    news_lock,
    news_settings,
    projects,
    projects_lock,
    re,
    repair_mojibake,
    repair_mojibake_text,
    session_scope,
    urlparse,
)
from services.scraping_service import clean_text, looks_blocked_or_empty


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


def fetch_debug_log(message: str, level: str = "info") -> None:
    append_unified_log(
        {
            "project_id": "fetch-debug",
            "project_name": "fetch-debug",
            "level": level,
            "message": message,
        }
    )


def html_title_for_debug(html: str) -> str:
    if not html:
        return ""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", html_lib.unescape(match.group(1))))[:180]


def debug_html_filename(url: str, method: str) -> str:
    parsed = urlparse(url)
    host = re.sub(r"[^A-Za-z0-9_-]+", "_", (parsed.hostname or "unknown").lower()).strip("_") or "unknown"
    method_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(method or "method")).strip("_") or "method"
    digest = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:10]
    return f"{host}_{method_name}_{digest}.html"


def save_fetch_debug_html(url: str, method: str, html: str) -> None:
    if not FETCH_DEBUG_HTML or not html:
        return
    try:
        FETCH_DEBUG_HTML_DIR.mkdir(parents=True, exist_ok=True)
        path = FETCH_DEBUG_HTML_DIR / debug_html_filename(url, method)
        path.write_text(html, encoding="utf-8", errors="replace")
    except OSError as error:
        fetch_debug_log(f"Не удалось сохранить debug HTML для {method} {url}: {error}", "warning")


def log_fetch_result(method: str, url: str, html: Optional[str], elapsed: float = 0.0, extra: str = "") -> None:
    html_text = html or ""
    title = html_title_for_debug(html_text)
    blocked = looks_blocked_or_empty(html_text) if html_text else True
    suffix = f"; {extra}" if extra else ""
    fetch_debug_log(
        f"method={method}; url={url}; html_len={len(html_text)}; blocked={blocked}; "
        f"elapsed={elapsed:.2f}s; title={title}{suffix}",
        "info" if html_text and not blocked else "warning",
    )
    if html_text:
        save_fetch_debug_html(url, method, html_text)


def log_fetch_exception(method: str, url: str, error: BaseException) -> None:
    fetch_debug_log(f"method={method}; url={url}; error={type(error).__name__}: {error}", "warning")


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
    auto_cleanup = bool(value)
    with session_scope() as db_session:
        app_setting = db_session.get(AppSetting, 1)
        if app_setting is None:
            app_setting = AppSetting(id=1)
            db_session.add(app_setting)
        app_setting.auto_cleanup = auto_cleanup
    return auto_cleanup


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
    return entries


def read_plain_log_file(path: Path, project_name: str, level: str) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    timestamp = log_time_from_path(path)
    for line in read_tail_lines(path):
        line = line.strip()
        if not line:
            continue
        if "PermissionError" in line and "app.log" in line:
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


__all__ = ['write_logs_file', 'append_unified_log', 'fetch_debug_log', 'html_title_for_debug', 'debug_html_filename', 'save_fetch_debug_html', 'log_fetch_result', 'log_fetch_exception', 'read_logs_file', 'get_log_auto_cleanup', 'set_log_auto_cleanup', 'log_time_from_path', 'read_tail_lines', 'read_unified_log_file', 'read_plain_log_file', 'iter_server_log_files', 'combined_log_entries', 'is_recent_log_entry', 'log_line_timestamp', 'iter_runtime_log_files', 'clear_runtime_log_files', 'prune_text_log_file', 'prune_old_log_files', 'save_logs', 'logs_signature', 'load_logs', 'load_news_logs_from_file']
