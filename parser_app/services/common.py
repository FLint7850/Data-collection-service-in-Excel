"""Shared normalization, serialization and application-state helpers."""



from parser_app.runtime import *  # noqa: F401,F403



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
        "eta_seconds": None,
        "paused_with_result": False,
    }

_storage_init_lock = threading.RLock()
_storage_initialized = False


def ensure_storage(force_reload: bool = False) -> None:
    """Initialize persistent storage once per process.

    Previously every API call repeated schema checks and reloaded all projects and
    monitors from SQLite. The guarded initialization keeps the same startup logic
    while making repeated calls effectively free.
    """
    global _storage_initialized
    if _storage_initialized and not force_reload:
        return

    with _storage_init_lock:
        if _storage_initialized and not force_reload:
            return
        EXPORT_DIR.mkdir(exist_ok=True)
        LOG_DIR.mkdir(exist_ok=True)
        FEED_DIR.mkdir(exist_ok=True)
        FILE_IMPORT_DIR.mkdir(parents=True, exist_ok=True)
        init_db()
        ensure_default_user()
        load_projects()
        load_news_settings()
        start_news_scheduler()
        _storage_initialized = True

def normalize_start_urls(value: object, allow_empty: bool = False) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [] if allow_empty else [DEFAULT_START_URL]

    urls = []
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        normalized = normalize_url(item, item)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls or ([] if allow_empty else [DEFAULT_START_URL])

def normalize_feed_url(raw_url: str) -> str:
    raw_url = str(raw_url or "").strip()
    if not raw_url:
        return ""
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    absolute_url, _fragment = urldefrag(raw_url)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))

def normalize_feed_urls(value: object, fallback: str) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [fallback]

    urls = []
    for item in raw_items:
        normalized = normalize_feed_url(item)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls or [fallback]

def normalize_patterns(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = []

    patterns = []
    for item in raw_items:
        item = item.strip()
        if item and item not in patterns:
            patterns.append(item)
    return patterns

def normalize_file_import_exclusions(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = value.splitlines()
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            raw_items.extend(str(item or "").splitlines())
    else:
        raw_items = []

    exclusions = []
    for item in raw_items:
        item = str(item or "").strip()
        if item and item not in exclusions:
            exclusions.append(item)
    return exclusions

def file_import_exclusions_text(value: object) -> str:
    return "\n".join(normalize_file_import_exclusions(value))

def normalize_file_import_rules_text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()

def normalize_emails(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,;]+", value)
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            raw_items.extend(re.split(r"[\n,;]+", str(item)))
    else:
        raw_items = []

    emails = []
    for item in raw_items:
        item = item.strip()
        if item and "@" in item and item not in emails:
            emails.append(item)
    return emails

def normalize_selector_settings(value: object) -> Dict[str, object]:
    if not isinstance(value, dict):
        value = {}
    allowed = {"name_selector", "availability_selector", "photo_selector"}
    settings: Dict[str, object] = {}
    for key in allowed:
        text = clean_text(str(value.get(key, "")))
        if text:
            settings[key] = text
    status_exclusions = normalize_patterns(value.get("availability_exclusions", []))
    if status_exclusions:
        settings["availability_exclusions"] = status_exclusions
    return settings

def normalize_model_key(value: str) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).upper()

def repair_mojibake_text(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    markers = (
        "\u0402",
        "\u0405",
        "\u0406",
        "\u040e",
        "\u0451",
        "\u0452",
        "\u0455",
        "\u045f",
        "\u20ac",
        "С",
        "П",
        "О",
        "М",
        "Н",
        "Д",
        "Г",
        "Ц",
        "Р",
        "С",
    )
    markers = markers + ("\u0420", "\u0421")
    text = value
    for _ in range(3):
        if not any(marker in text for marker in markers):
            break
        try:
            repaired = text.encode("cp1251").decode("utf-8")
        except UnicodeError:
            break
        if repaired == text:
            break
        text = repaired
    return text

def repair_mojibake(value: object) -> object:
    if isinstance(value, dict):
        return {key: repair_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_mojibake(item) for item in value]
    return repair_mojibake_text(value)

def jsonify(*args: object, **kwargs: object):
    repaired_args = tuple(repair_mojibake(item) for item in args)
    repaired_kwargs = repair_mojibake(kwargs) if kwargs else {}
    return flask_jsonify(*repaired_args, **repaired_kwargs)

def output_text(value: object) -> str:
    if value is None:
        return ""
    return str(repair_mojibake_text(str(value)) or "")

def parse_thread_count(value: object) -> int:
    try:
        return max(1, min(int(value or 4), 16))
    except (TypeError, ValueError):
        return 4

def get_connection_method_codes(force_refresh: bool = False) -> List[str]:
    """Возвращает коды способов подключения из БД в порядке их id."""
    now = time.time()
    with connection_method_cache_lock:
        cached_codes = list(connection_method_cache.get("codes") or [])
        loaded_at = float(connection_method_cache.get("loaded_at") or 0.0)
        if cached_codes and not force_refresh and now - loaded_at < CONNECTION_METHOD_CACHE_SECONDS:
            return cached_codes

    codes: List[str] = []
    try:
        with session_scope() as session:
            rows = session.execute(select(ConnectionMethod.code).order_by(ConnectionMethod.id)).scalars().all()
        for code in rows:
            code_text = str(code or "").strip()
            if code_text and code_text not in codes:
                codes.append(code_text)
    except Exception as error:
        append_unified_log({
            "project_id": "system",
            "project_name": "system",
            "level": "warning",
            "message": f"Не удалось прочитать способы подключения из БД: {error}",
        })

    if not codes:
        codes = ["requests"]

    with connection_method_cache_lock:
        connection_method_cache["codes"] = list(codes)
        connection_method_cache["loaded_at"] = now
    return codes

def public_connection_methods() -> List[Dict[str, object]]:
    try:
        with session_scope() as session:
            rows = session.execute(
                select(ConnectionMethod).order_by(ConnectionMethod.id)
            ).scalars().all()
        methods = [
            {
                "id": int(row.id),
                "code": str(row.code or "").strip(),
                "name": str(row.name or row.code or "").strip(),
            }
            for row in rows
            if str(row.code or "").strip()
        ]
    except Exception as error:
        append_unified_log({
            "project_id": "system",
            "project_name": "system",
            "level": "warning",
            "message": f"Не удалось прочитать способы подключения из БД: {error}",
        })
        methods = []
    if methods:
        return methods
    return [{"id": 0, "code": "requests", "name": "Requests"}]

def ordered_db_connection_methods(
    preferred: Optional[Iterable[str]] = None,
) -> List[str]:
    """Строит fallback-цепочку только из методов, которые есть в БД."""
    db_codes = get_connection_method_codes()
    ordered: List[str] = []

    if preferred:
        for method in preferred:
            if method in db_codes and method not in ordered:
                ordered.append(method)

    for method in db_codes:
        if method not in ordered:
            ordered.append(method)
    return ordered

def normalize_connection_method(value: object) -> str:
    method = str(value or "requests").strip()
    codes = get_connection_method_codes()
    if method in codes:
        return method
    return codes[0] if codes else "requests"

def parse_db_int(value: object) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None

def parse_datetime_value(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed

def datetime_to_input_value(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value or "")
    if parsed.tzinfo is None:
        return parsed.isoformat(timespec="minutes")
    return parsed.astimezone(MSK_TZ).replace(tzinfo=None).isoformat(timespec="minutes")

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

def get_donor_row(session, public_id: object) -> Optional[Donor]:
    db_id = parse_db_int(public_id)
    if db_id is not None:
        row = session.get(Donor, db_id)
        if row is not None:
            return row
    legacy_id = str(public_id or "").strip()
    if not legacy_id:
        return None
    return session.scalar(select(Donor).where(Donor.legacy_id == legacy_id))

def connection_method_id_for(session, code: object) -> Optional[int]:
    method = normalize_connection_method(code)
    row = session.scalar(select(ConnectionMethod).where(ConnectionMethod.code == method))
    return row.id if row else None

def normalize_extraction_rules(value: object) -> Dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    single_line_fields = {
        "product_card_selector",
        "product_url_selector",
        "model_selector",
        "price_selector",
        "model_start_marker",
        "model_end_marker",
    }
    multiline_fields = {"model_replace_rules"}
    rules = {}
    for key in single_line_fields:
        text = str(value.get(key, "")).strip()
        if text:
            rules[key] = text
    for key in multiline_fields:
        text = str(value.get(key, "")).strip()
        if text:
            rules[key] = text
    return rules

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
