"""News-monitor settings, donors, brands and public DTOs."""



from parser_app.runtime import *  # noqa: F401,F403



def default_smtp_settings() -> Dict[str, object]:
    return {
        "host": env_str("SMTP_HOST", "smtp.yandex.ru"),
        "port": env_int("SMTP_PORT", 465, minimum=1, maximum=65535),
        "security": env_str("SMTP_SECURITY", "ssl"),
        "username": env_str("SMTP_USERNAME", ""),
        "password": env_str("SMTP_PASSWORD", env_str("YANDEX_SMTP_PASSWORD", "")),
        "recipients": env_list("SMTP_RECIPIENTS", []),
    }

def merge_smtp_settings(base: Dict[str, object], stored: Dict[str, object]) -> Dict[str, object]:
    smtp = dict(base)
    for key in ("host", "security", "username", "password"):
        value = str(stored.get(key) or "").strip()
        if value:
            smtp[key] = value
    if stored.get("port"):
        try:
            smtp["port"] = int(stored.get("port") or smtp.get("port") or 465)
        except (TypeError, ValueError):
            pass
    recipients = normalize_emails(stored.get("recipients", []))
    if recipients:
        smtp["recipients"] = recipients
    smtp.pop("sender", None)
    return smtp

def default_news_settings() -> Dict[str, object]:
    return {
        "feed_url": DEFAULT_FEED_URL,
        "feed_generate_url": DEFAULT_FEED_GENERATE_URL,
        "feed_urls": [DEFAULT_FEED_URL],
        "feed_generate_urls": [DEFAULT_FEED_GENERATE_URL],
        "auto_cleanup": False,
        "smtp": default_smtp_settings(),
        "monitors": [],
        "logs": [],
        "feed_storage": [],
    }

def make_news_monitor(group: str, brand: str, urls: List[str], site_url: str = "") -> Dict[str, object]:
    monitor_id = uuid.uuid4().hex[:10]
    site_url = str(site_url or "").strip()
    return {
        "id": monitor_id,
        "group": group,
        "brand": brand,
        "created_at": datetime.now().isoformat(timespec="milliseconds"),
        "site_url": site_url,
        "start_urls": list(urls),
        "enabled": True,
        "schedule_type": "daily",
        "scan_time": "01:00",
        "weekday": 0,
        "next_run_at": "",
        "thread_count": 4,
        "connection_method": normalize_connection_method(None),
        "auto_connection_fallback": True,
        "exclusions": DEFAULT_EXCLUSIONS.copy(),
        "product_url_filters": [],
        "extraction_rules": {},
        "selector_settings": {},
        "seen_models": [],
        "known_new_products": {},
        "state": make_news_state(),
        "collapsed": True,
    }

def make_news_state(status: str = "idle") -> Dict[str, object]:
    return {
        "status": status,
        "stage": "",
        "percent": 0,
        "currenturl": "",
        "processed": 0,
        "found_products": 0,
        "candidate_products": 0,
        "compared_products": 0,
        "queue_size": 0,
        "active_tasks": 0,
        "active_urls": [],
        "in_memory_products": 0,
        "availability_skipped": 0,
        "failed_pages": 0,
        "stall_seconds": 0,
        "last_event": "",
        "last_warning": "",
        "new_count": 0,
        "missing_by_feed": [],
        "skipped": 0,
        "last_scan_at": "",
        "last_csv": "",
        "error": "",
        "started_at": "",
        "finished_at": "",
        "elapsed_seconds": 0,
        "next_run_at": "",
    }

def normalize_news_monitor(item: Dict[str, object]) -> Dict[str, object]:
    start_urls = normalize_start_urls(item.get("start_urls") or "", allow_empty=True)
    monitor = make_news_monitor(
        clean_text(str(item.get("group") or "Маржа")),
        clean_text(str(item.get("brand") or "Донор")),
        start_urls,
        str(item.get("site_url") or ""),
    )
    monitor["id"] = str(item.get("id") or monitor["id"])
    monitor["created_at"] = str(item.get("created_at") or monitor["created_at"])
    monitor["site_url"] = str(item.get("site_url") or "")
    monitor["enabled"] = bool(item.get("enabled", True))
    monitor["schedule_type"] = str(item.get("schedule_type") or "daily")
    monitor["scan_time"] = str(item.get("scan_time") or "01:00")[:5]
    monitor["weekday"] = max(0, min(int(item.get("weekday", 0) or 0), 6))
    monitor["next_run_at"] = str(item.get("next_run_at") or "")
    monitor["thread_count"] = parse_thread_count(item.get("thread_count", 4))
    monitor["connection_method"] = normalize_connection_method(item.get("connection_method"))
    monitor["auto_connection_fallback"] = bool(item.get("auto_connection_fallback", True))
    monitor["exclusions"] = normalize_patterns(item.get("exclusions", DEFAULT_EXCLUSIONS))
    monitor["product_url_filters"] = normalize_patterns(item.get("product_url_filters", []))
    monitor["extraction_rules"] = normalize_extraction_rules(item.get("extraction_rules", {}))
    monitor["selector_settings"] = normalize_selector_settings(item.get("selector_settings", {}))
    monitor["seen_models"] = [normalize_model_key(str(value)) for value in item.get("seen_models", []) if str(value).strip()]
    known = item.get("known_new_products", {})
    monitor["known_new_products"] = known if isinstance(known, dict) else {}
    state = item.get("state", {})
    monitor["state"] = {**make_news_state(), **state} if isinstance(state, dict) else make_news_state()
    monitor["state"].pop("last_feeds", None)
    if monitor["state"].get("status") in {"running", "queued", "pausing", "stopping"}:
        monitor["state"]["status"] = "error"
        monitor["state"]["stage"] = "Прервано"
        monitor["state"]["error"] = "Сканирование было прервано перезапуском сервера. Запустите его снова."
        monitor["state"]["currenturl"] = ""
    monitor["brand_state"] = dict(monitor["state"])
    monitor["collapsed"] = bool(item.get("collapsed", True))
    return monitor

def split_news_monitor_by_site(item: Dict[str, object]) -> List[Dict[str, object]]:
    urls = normalize_start_urls(item.get("start_urls") or "", allow_empty=True)
    monitors = []
    if not urls:
        return [normalize_news_monitor({**item, "site_url": "", "start_urls": []})]
    for index, url in enumerate(urls):
        copy_item = dict(item)
        copy_item["id"] = str(item.get("id") or uuid.uuid4().hex[:10]) if index == 0 else uuid.uuid4().hex[:10]
        copy_item["start_urls"] = [url]
        monitors.append(normalize_news_monitor(copy_item))
    return monitors

def unique_news_brand_name(group: str, base_name: str = "Новый бренд") -> str:
    base_name = clean_text(base_name) or "Новый бренд"
    group_name = clean_text(group)
    names = {
        clean_text(str(item.get("brand") or ""))
        for item in news_settings.get("monitors", [])
        if isinstance(item, dict) and clean_text(str(item.get("group") or "")) == group_name
    }
    if base_name not in names:
        return base_name
    index = 2
    while True:
        candidate = f"{base_name} {index}"
        if candidate not in names:
            return candidate
        index += 1

def donor_connection_code(row: Donor) -> str:
    method_row = getattr(row, "connection_method_row", None)
    return normalize_connection_method(getattr(method_row, "code", None))

def donor_model_to_monitor(row: Donor) -> Dict[str, object]:
    brand = row.brand
    brand_state = repair_mojibake({**make_news_state(), **(brand.state or {})}) if brand else make_news_state()
    site_url = str(row.site_url or "").strip()
    start_urls = normalize_start_urls(getattr(row, "start_urls", None) or "", allow_empty=True)
    monitor = {
        "id": str(row.id),
        "group": brand.group_name if brand else "",
        "brand": brand.name if brand else "Донор",
        "brand_id": brand.id if brand else None,
        "brand_created_at": brand.created_at.isoformat(timespec="milliseconds") if brand and brand.created_at else "",
        "primary_donor_id": brand.primary_donor_id if brand else None,
        "brand_state": brand_state,
        "created_at": row.created_at.isoformat(timespec="milliseconds") if row.created_at else "",
        "site_url": site_url,
        "start_urls": start_urls,
        "enabled": bool(brand.enabled) if brand else True,
        "schedule_type": brand.schedule_type if brand else "daily",
        "scan_time": brand.scan_time if brand else "01:00",
        "weekday": max(0, min(int((brand.weekday if brand else 0) or 0), 6)),
        "next_run_at": datetime_to_input_value(brand.next_run_at if brand else None),
        "thread_count": parse_thread_count(row.thread_count),
        "connection_method": donor_connection_code(row),
        "connection_id": row.connection_id,
        "auto_connection_fallback": bool(row.auto_connection_fallback),
        "exclusions": normalize_patterns(row.exclusions or DEFAULT_EXCLUSIONS),
        "product_url_filters": normalize_patterns(row.product_url_filters or []),
        "extraction_rules": normalize_extraction_rules(row.extraction_rules or {}),
        "selector_settings": normalize_selector_settings(row.selector_settings or {}),
        "seen_models": [normalize_model_key(str(value)) for value in (row.seen_models or []) if str(value).strip()],
        "known_new_products": row.known_new_products or {},
        "state": dict(brand_state),
    }
    if monitor["state"].get("status") in {"running", "queued", "pausing", "stopping"}:
        monitor["state"]["status"] = "error"
        monitor["state"]["stage"] = "Прервано"
        monitor["state"]["error"] = "Сканирование было прервано перезапуском сервера. Запустите его снова."
        monitor["state"]["currenturl"] = ""
        monitor["state"]["queue_size"] = 0
        monitor["state"]["active_tasks"] = 0
        monitor["state"]["active_urls"] = []
        monitor["state"]["in_memory_products"] = 0
        monitor["brand_state"] = dict(monitor["state"])
    return monitor

def get_or_create_brand(session, monitor: Dict[str, object]) -> Brand:
    name = clean_text(str(monitor.get("brand") or "Донор"))
    group_name = clean_text(str(monitor.get("group") or "Маржа"))
    row = session.scalar(select(Brand).where(Brand.name == name, Brand.group_name == group_name))
    if row is None:
        row = Brand(
            name=name,
            group_name=group_name,
            state={**make_news_state(), **(monitor.get("brand_state") or monitor.get("state") or {})},
            enabled=bool(monitor.get("enabled", True)),
            schedule_type=str(monitor.get("schedule_type") or "daily"),
            scan_time=str(monitor.get("scan_time") or "01:00")[:5],
            weekday=max(0, min(int(monitor.get("weekday", 0) or 0), 6)),
            next_run_at=parse_datetime_value(monitor.get("next_run_at")),
        )
        session.add(row)
        session.flush()
    else:
        row.group_name = group_name
        row.state = {**make_news_state(), **(monitor.get("brand_state") or monitor.get("state") or row.state or {})}
        row.enabled = bool(monitor.get("enabled", row.enabled))
        schedule_type = str(monitor.get("schedule_type") or row.schedule_type or "daily")
        row.schedule_type = schedule_type if schedule_type in {"daily", "weekly", "once"} else "daily"
        row.scan_time = str(monitor.get("scan_time") or row.scan_time or "01:00")[:5]
        row.weekday = max(0, min(int(monitor.get("weekday", row.weekday) or 0), 6))
        row.next_run_at = parse_datetime_value(monitor.get("next_run_at"))
    return row

def upsert_donor_model(session, monitor: Dict[str, object]) -> int:
    normalized = normalize_news_monitor(monitor)
    brand = get_or_create_brand(session, normalized)
    row = get_donor_row(session, normalized.get("id"))
    if row is None:
        legacy_id = str(normalized.get("id") or "").strip()
        row = Donor(
            legacy_id=legacy_id if legacy_id and parse_db_int(legacy_id) is None else "",
            brand_id=brand.id,
        )
        session.add(row)
    row.brand_id = brand.id
    start_urls = normalize_start_urls(normalized.get("start_urls") or "", allow_empty=True)
    site_url = str(normalized.get("site_url") or "").strip()
    row.site_url = site_url
    row.start_urls = start_urls
    row.thread_count = parse_thread_count(normalized.get("thread_count", 4))
    row.connection_id = connection_method_id_for(session, normalized.get("connection_method"))
    row.auto_connection_fallback = bool(normalized.get("auto_connection_fallback", True))
    row.exclusions = normalize_patterns(normalized.get("exclusions", DEFAULT_EXCLUSIONS))
    row.product_url_filters = normalize_patterns(normalized.get("product_url_filters", []))
    row.extraction_rules = normalize_extraction_rules(normalized.get("extraction_rules", {}))
    row.selector_settings = normalize_selector_settings(normalized.get("selector_settings", {}))
    row.seen_models = [normalize_model_key(str(value)) for value in normalized.get("seen_models", []) if str(value).strip()]
    row.known_new_products = normalized.get("known_new_products", {}) if isinstance(normalized.get("known_new_products"), dict) else {}
    session.flush()
    if not brand.primary_donor_id or not any(donor.id == brand.primary_donor_id for donor in brand.donors):
        brand.primary_donor_id = row.id
    session.flush()
    monitor["brand_id"] = brand.id
    monitor["brand_created_at"] = brand.created_at.isoformat(timespec="milliseconds") if brand.created_at else ""
    monitor["primary_donor_id"] = brand.primary_donor_id
    return int(row.id)

def aggregate_brand_state(monitors: List[Dict[str, object]]) -> Dict[str, object]:
    states = [{**make_news_state(), **(monitor.get("state") or {})} for monitor in monitors if isinstance(monitor, dict)]
    if not states:
        return make_news_state()
    priority = ["running", "queued", "pausing", "stopping", "error", "partial", "completed"]
    selected = next((state for status in priority for state in states if state.get("status") == status), states[0])
    result = {**make_news_state(), **selected}
    last_scan_at = max((str(state.get("last_scan_at") or state.get("finished_at") or "") for state in states), default="")
    if last_scan_at:
        result["last_scan_at"] = last_scan_at
    return result

def sync_brand_runtime_fields(source_monitor: Dict[str, object]) -> None:
    group = clean_text(str(source_monitor.get("group") or ""))
    brand = clean_text(str(source_monitor.get("brand") or ""))
    fields = ("enabled", "schedule_type", "scan_time", "weekday", "next_run_at", "state", "brand_state")
    for item in news_settings.get("monitors", []):
        if (
            isinstance(item, dict)
            and clean_text(str(item.get("group") or "")) == group
            and clean_text(str(item.get("brand") or "")) == brand
        ):
            for field in fields:
                if field in source_monitor:
                    item[field] = dict(source_monitor[field]) if isinstance(source_monitor[field], dict) else source_monitor[field]

def ensure_brand_primary_flags(monitors: List[Dict[str, object]]) -> None:
    grouped: Dict[tuple[str, str], List[Dict[str, object]]] = {}
    for item in monitors:
        if not isinstance(item, dict):
            continue
        key = (clean_text(str(item.get("group") or "")), clean_text(str(item.get("brand") or "")))
        grouped.setdefault(key, []).append(item)
    for items in grouped.values():
        primary_id = str(items[0].get("primary_donor_id") or items[0].get("id") or "")
        if not any(str(item.get("id")) == primary_id for item in items):
            primary_id = str(items[0].get("id") or "")
        for item in items:
            item["primary_donor_id"] = primary_id

def own_sites_from_settings(settings: Dict[str, object]) -> List[Dict[str, str]]:
    if isinstance(settings.get("own_sites"), list):
        sites = []
        for index, item in enumerate(settings.get("own_sites", []), start=1):
            if not isinstance(item, dict):
                continue
            feed_url = normalize_feed_url(str(item.get("feed_url") or "").strip())
            if not feed_url:
                continue
            sites.append(
                {
                    "name": clean_text(str(item.get("name") or "")) or f"Фид {index}",
                    "feed_url": feed_url,
                    "feed_generate_url": normalize_feed_url(str(item.get("feed_generate_url") or "").strip()),
                }
            )
        if sites:
            return sites
    feed_urls = normalize_feed_urls(settings.get("feed_urls") or settings.get("feed_url") or DEFAULT_FEED_URL, DEFAULT_FEED_URL)
    generate_urls = normalize_feed_urls(settings.get("feed_generate_urls") or settings.get("feed_generate_url") or DEFAULT_FEED_GENERATE_URL, DEFAULT_FEED_GENERATE_URL)
    sites = []
    for index, feed_url in enumerate(feed_urls):
        generate_url = generate_urls[index] if index < len(generate_urls) else (generate_urls[0] if generate_urls else "")
        sites.append({"name": feed_source_label(feed_url), "feed_url": feed_url, "feed_generate_url": generate_url})
    return sites

def save_news_settings() -> None:
    with news_lock:
        with session_scope() as session:
            smtp = dict(news_settings.get("smtp", {}))
            smtp.pop("sender", None)
            app_setting = session.get(AppSetting, 1)
            if app_setting is None:
                app_setting = AppSetting(id=1)
                session.add(app_setting)
            app_setting.auto_cleanup = bool(news_settings.get("auto_cleanup", False))
            app_setting.smtp = smtp
            app_setting.feed_storage = list(news_settings.get("feed_storage", [])) if isinstance(news_settings.get("feed_storage"), list) else []

            current_donor_ids = set()
            for monitor in news_settings.get("monitors", []):
                if not isinstance(monitor, dict):
                    continue
                db_id = upsert_donor_model(session, monitor)
                current_donor_ids.add(db_id)
                if str(monitor.get("id")) != str(db_id):
                    monitor["id"] = str(db_id)
            grouped_monitors: Dict[tuple[str, str], List[Dict[str, object]]] = {}
            for monitor in news_settings.get("monitors", []):
                if not isinstance(monitor, dict):
                    continue
                group_name = clean_text(str(monitor.get("group") or "Маржа"))
                brand_name = clean_text(str(monitor.get("brand") or "Донор"))
                grouped_monitors.setdefault((brand_name, group_name), []).append(monitor)
            for (brand_name, group_name), brand_monitors in grouped_monitors.items():
                brand_row = session.scalar(select(Brand).where(Brand.name == brand_name, Brand.group_name == group_name))
                if brand_row:
                    brand_row.state = aggregate_brand_state(brand_monitors)
            if current_donor_ids:
                session.execute(delete(Donor).where(Donor.id.not_in(current_donor_ids)))
            else:
                session.execute(delete(Donor))
            session.flush()
            for brand_row in session.scalars(select(Brand)).all():
                donor_ids = [donor.id for donor in brand_row.donors]
                if donor_ids and brand_row.primary_donor_id not in donor_ids:
                    brand_row.primary_donor_id = donor_ids[0]
            session.execute(delete(Brand).where(~Brand.donors.any()))

            current_feed_urls = set()
            for site in own_sites_from_settings(news_settings):
                current_feed_urls.add(site["feed_url"])
                row = session.scalar(select(OwnSite).where(OwnSite.feed_url == site["feed_url"]))
                if row is None:
                    row = OwnSite(name=site["name"], feed_url=site["feed_url"], feed_generate_url=site["feed_generate_url"])
                    session.add(row)
                else:
                    row.name = site["name"]
                    row.feed_generate_url = site["feed_generate_url"]
            if current_feed_urls:
                session.execute(delete(OwnSite).where(OwnSite.feed_url.not_in(current_feed_urls)))

def reload_news_monitors_from_db() -> None:
    load_news_settings()
    cleanup_stale_news_transitions()
    with news_lock:
        active_by_id = {
            str(monitor.get("id")): monitor
            for monitor in news_settings.get("monitors", [])
            if isinstance(monitor, dict)
            and monitor.get("state", {}).get("status") in {"running", "queued", "pausing", "stopping"}
            and not is_stale_news_transition(monitor)
        }
    with session_scope() as session:
        donor_rows = session.scalars(
            select(Donor)
            .join(Brand, Donor.brand_id == Brand.id)
            .order_by(Brand.group_name, Brand.name, Donor.id)
        ).all()
        monitors = [donor_model_to_monitor(row) for row in donor_rows]
        ensure_brand_primary_flags(monitors)
    with news_lock:
        news_settings["monitors"] = [
            active_by_id.get(str(monitor.get("id")), monitor)
            for monitor in monitors
        ]

def add_news_log(monitor: Optional[Dict[str, object]], message: str, level: str = "info") -> None:
    with news_lock:
        logs = news_settings.setdefault("logs", [])
        logs.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "project_id": f"news:{monitor.get('id')}" if monitor else "news",
                "project_name": repair_mojibake_text(f"Новинки: {monitor.get('brand')}") if monitor else "Новинки",
                "level": level,
                "message": repair_mojibake_text(message),
            }
        )
        append_unified_log(logs[-1])
        if news_settings.get("auto_cleanup"):
            cutoff = time.time() - 7 * 24 * 60 * 60
            logs[:] = [
                item
                for item in logs
                if datetime.fromisoformat(item["time"]).timestamp() >= cutoff
            ]
    save_logs()

def get_news_monitor(monitor_id: str) -> Optional[Dict[str, object]]:
    ensure_storage()
    with news_lock:
        for monitor in news_settings.get("monitors", []):
            if str(monitor.get("id")) == str(monitor_id):
                return monitor
    return None

def resolve_export_file(filename: str) -> Optional[Path]:
    if not filename:
        return None
    candidates = [filename]
    repaired = repair_mojibake_text(filename)
    if isinstance(repaired, str) and repaired and repaired not in candidates:
        candidates.append(repaired)
    for candidate in candidates:
        path = (EXPORT_DIR / candidate).resolve()
        if EXPORT_DIR.resolve() in path.parents and path.exists():
            return path
    return None

def news_csv_prefix(monitor: Dict[str, object]) -> str:
    brand = clean_text(str(monitor.get("brand") or "")).strip()
    source = safe_filename(brand or "unknown_site")
    return f"Новинки_{source}_"

def news_csv_filename(monitor: Dict[str, object], created_at: Optional[datetime] = None) -> str:
    created_at = created_at or datetime.now(MSK_TZ)
    return f"{news_csv_prefix(monitor)}{created_at.strftime('%d-%m-%Y_%H-%M-%S')}.csv"

def delete_news_csv_for_monitor(monitor: Dict[str, object], keep_filename: str = "") -> None:
    keep_filename = str(keep_filename or "").strip()
    filenames = {
        keep_filename,
        str((monitor.get("state") or {}).get("last_csv") or ""),
    }
    state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    state_data = state.get("data", {}) if isinstance(state.get("data"), dict) else {}
    filenames.add(str(state_data.get("csv") or ""))
    prefix = news_csv_prefix(monitor)
    try:
        for path in EXPORT_DIR.glob(f"{prefix}*.csv"):
            if path.is_file() and path.name not in filenames:
                path.unlink(missing_ok=True)
    except OSError:
        pass
    for filename in filenames:
        if not filename:
            continue
        if filename == keep_filename:
            continue
        path = resolve_export_file(filename)
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

def public_news_monitor(monitor: Dict[str, object]) -> Dict[str, object]:
    public_monitor = repair_mojibake(dict(monitor))
    state = dict(public_monitor.get("state") or make_news_state())
    original_state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    original_data = original_state.get("data", {}) if isinstance(original_state.get("data"), dict) else {}
    public_data = state.get("data", {}) if isinstance(state.get("data"), dict) else {}
    filename = str(
        original_state.get("last_csv")
        or state.get("last_csv")
        or original_data.get("csv")
        or public_data.get("csv")
        or ""
    )
    if filename and not state.get("last_csv"):
        state["last_csv"] = str(repair_mojibake_text(filename) or filename)
    state["csv_ready"] = bool(resolve_export_file(filename))
    if state.get("last_csv"):
        state["last_csv"] = str(repair_mojibake_text(state["last_csv"]) or state["last_csv"])
    public_monitor["state"] = state
    if isinstance(public_monitor.get("brand_state"), dict):
        brand_state = dict(public_monitor["brand_state"])
        brand_data = brand_state.get("data", {}) if isinstance(brand_state.get("data"), dict) else {}
        brand_filename = str(brand_state.get("last_csv") or brand_data.get("csv") or filename)
        if brand_filename and not brand_state.get("last_csv"):
            brand_state["last_csv"] = str(repair_mojibake_text(brand_filename) or brand_filename)
        brand_state["csv_ready"] = bool(resolve_export_file(brand_filename))
        if brand_state.get("last_csv"):
            brand_state["last_csv"] = str(repair_mojibake_text(brand_state["last_csv"]) or brand_state["last_csv"])
        public_monitor["brand_state"] = brand_state
    return public_monitor

def public_news_settings() -> Dict[str, object]:
    cleanup_stale_news_transitions()
    with news_lock:
        smtp = dict(news_settings.get("smtp", {}))
        smtp.pop("sender", None)
        smtp["password_set"] = bool(news_settings.get("smtp", {}).get("password"))
        own_sites = own_sites_from_settings(news_settings)
        feed_urls = [site["feed_url"] for site in own_sites]
        feed_generate_urls = [site["feed_generate_url"] for site in own_sites]
        return {
            "feed_url": feed_urls[0] if feed_urls else DEFAULT_FEED_URL,
            "feed_generate_url": feed_generate_urls[0] if feed_generate_urls else DEFAULT_FEED_GENERATE_URL,
            "feed_urls": feed_urls,
            "feed_generate_urls": feed_generate_urls,
            "own_sites": own_sites,
            "auto_cleanup": bool(news_settings.get("auto_cleanup", False)),
            "smtp": smtp,
            "feed_storage": list(news_settings.get("feed_storage", [])) if isinstance(news_settings.get("feed_storage"), list) else [],
            "connection_methods": public_connection_methods(),
            "monitors": [public_news_monitor(monitor) for monitor in news_settings.get("monitors", [])],
        }
