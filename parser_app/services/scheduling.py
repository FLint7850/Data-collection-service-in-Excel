"""Monitor scheduling and scheduler loop."""



from parser_app.runtime import *  # noqa: F401,F403



def parse_scan_time(value: object) -> datetime_time:
    text = str(value or "01:00")
    try:
        hour, minute = [int(part) for part in text[:5].split(":", 1)]
        return datetime_time(max(0, min(hour, 23)), max(0, min(minute, 59)), tzinfo=MSK_TZ)
    except Exception:
        return datetime_time(1, 0, tzinfo=MSK_TZ)

def parse_schedule_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(MSK_TZ) if value.tzinfo else value.replace(tzinfo=MSK_TZ)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(MSK_TZ) if parsed.tzinfo else parsed.replace(tzinfo=MSK_TZ)

def normalize_schedule_type(value: object) -> str:
    schedule_type = str(value or "daily")
    return schedule_type if schedule_type in {"daily", "weekly", "once"} else "daily"

def normalize_weekday(value: object) -> int:
    try:
        return max(0, min(int(value or 0), 6))
    except (TypeError, ValueError):
        return 0

def compute_schedule_run_at(
    schedule_type: object,
    scan_time: object,
    weekday: object = 0,
    once_at: object = None,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    now = now or datetime.now(MSK_TZ)
    schedule = normalize_schedule_type(schedule_type)
    if schedule == "once":
        return parse_schedule_datetime(once_at)
    run_time = parse_scan_time(scan_time)
    candidate = now.replace(hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)
    if schedule == "weekly":
        candidate += timedelta(days=normalize_weekday(weekday) - now.weekday())
    return candidate

def compute_next_schedule_at(
    schedule_type: object,
    scan_time: object,
    weekday: object = 0,
    once_at: object = None,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    now = now or datetime.now(MSK_TZ)
    schedule = normalize_schedule_type(schedule_type)
    if schedule == "once":
        return parse_schedule_datetime(once_at)
    candidate = compute_schedule_run_at(schedule, scan_time, weekday, now=now)
    if candidate is None:
        return None
    if schedule == "weekly":
        if candidate <= now:
            candidate += timedelta(days=7)
    elif candidate <= now:
        candidate += timedelta(days=1)
    return candidate

def compute_next_run_at(monitor: Dict[str, object]) -> str:
    candidate = compute_next_schedule_at(
        monitor.get("schedule_type"),
        monitor.get("scan_time"),
        monitor.get("weekday"),
        monitor.get("next_run_at"),
    )
    return candidate.isoformat(timespec="minutes") if candidate else ""

def brand_schedule_fields(brand: Brand) -> Dict[str, object]:
    return {
        "enabled": bool(brand.enabled),
        "schedule_type": normalize_schedule_type(brand.schedule_type),
        "scan_time": str(brand.scan_time or "01:00")[:5],
        "weekday": normalize_weekday(brand.weekday),
        "next_run_at": datetime_to_input_value(brand.next_run_at),
        "primary_donor_id": brand.primary_donor_id,
    }

def is_brand_due(brand: Brand, now: Optional[datetime] = None) -> bool:
    if not bool(brand.enabled):
        return False
    state = brand.state if isinstance(brand.state, dict) else {}
    if state.get("status") in {"running", "queued", "pausing", "stopping"}:
        return False
    now = now or datetime.now(MSK_TZ)
    schedule_type = normalize_schedule_type(brand.schedule_type)
    due_at = compute_schedule_run_at(schedule_type, brand.scan_time, brand.weekday, brand.next_run_at, now)
    if not due_at:
        return False
    if schedule_type in {"daily", "weekly"}:
        seconds_after_due = (now - due_at).total_seconds()
        if seconds_after_due < 0 or seconds_after_due >= SCHEDULE_DUE_GRACE_SECONDS:
            return False
    elif now < due_at:
        return False
    last_scan = str(state.get("last_scan_at") or "")
    if last_scan:
        last_scan_at = parse_schedule_datetime(last_scan)
        if last_scan_at and last_scan_at >= due_at:
            return False
    return True

def update_brand_next_run_at(brand_id: object) -> str:
    with session_scope() as session:
        brand = session.get(Brand, parse_db_int(brand_id))
        if not brand:
            return ""
        next_at = compute_next_schedule_at(brand.schedule_type, brand.scan_time, brand.weekday, brand.next_run_at)
        if normalize_schedule_type(brand.schedule_type) != "once":
            brand.next_run_at = next_at.replace(tzinfo=None) if next_at else None
        return datetime_to_input_value(brand.next_run_at)

def refresh_monitor_schedule_from_brand(monitor: Dict[str, object]) -> None:
    brand_id = parse_db_int(monitor.get("brand_id"))
    if not brand_id:
        return
    with session_scope() as session:
        brand = session.get(Brand, brand_id)
        if not brand:
            return
        monitor.update(brand_schedule_fields(brand))

def safe_next_path(value: object) -> str:
    text = str(value or "").strip()
    if not text.startswith("/") or text.startswith("//"):
        return url_for("index")
    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc:
        return url_for("index")
    return urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))

def start_news_scheduler() -> None:
    global news_scheduler_thread
    if isinstance(news_scheduler_thread, threading.Thread) and news_scheduler_thread.is_alive():
        return

    def scheduler_loop() -> None:
        while True:
            try:
                reload_news_monitors_from_db()
                due_ids: List[str] = []
                with news_lock:
                    monitor_by_id = {
                        str(monitor.get("id")): monitor
                        for monitor in news_settings.get("monitors", [])
                        if isinstance(monitor, dict)
                    }
                    with session_scope() as session:
                        brand_rows = session.scalars(select(Brand).order_by(Brand.id)).all()
                        due_brands = [brand for brand in brand_rows if is_brand_due(brand)]
                        due_brand_data = [
                            {
                                "brand_id": brand.id,
                                "brand_name": brand.name,
                                "primary_id": brand.primary_donor_id,
                                "schedule": brand_schedule_fields(brand),
                                "donor_ids": [donor.id for donor in brand.donors],
                            }
                            for brand in due_brands
                        ]
                    for brand_data in due_brand_data:
                        primary_id = str(brand_data.get("primary_id") or "")
                        selected = monitor_by_id.get(primary_id)
                        if selected is None:
                            fallback_id = next((str(donor_id) for donor_id in brand_data.get("donor_ids", []) if str(donor_id) in monitor_by_id), "")
                            selected = monitor_by_id.get(fallback_id)
                        if selected is None:
                            add_news_log(
                                None,
                                f"Плановый запуск пропущен: основной донор бренда {brand_data.get('brand_name')} не найден.",
                                "warning",
                            )
                            continue
                        selected.update(brand_data["schedule"])
                        selected["state"] = {**selected.get("state", {}), "status": "queued"}
                        selected["brand_state"] = dict(selected["state"])
                        sync_brand_runtime_fields(selected)
                        due_ids.append(str(selected.get("id")))
                    if due_ids:
                        save_news_settings()
                for monitor_id in due_ids:
                    enqueue_news_scan(monitor_id, manual=False)
            except Exception:
                pass
            time.sleep(30)

    news_scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    news_scheduler_thread.start()
