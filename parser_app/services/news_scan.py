"""News-monitor scanning, enrichment, CSV and email delivery."""



from parser_app.runtime import *  # noqa: F401,F403



def update_news_monitor_state(monitor: Dict[str, object], persist: bool = True, **kwargs: object) -> None:
    with news_lock:
        state = dict(monitor.get("state", make_news_state()))
        state.update(kwargs)
        state = repair_mojibake(state)
        if state.get("started_at") and state.get("status") in {"running", "queued"}:
            try:
                started_at = datetime.fromisoformat(str(state.get("started_at")))
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=MSK_TZ)
                state["elapsed_seconds"] = int((datetime.now(MSK_TZ) - started_at).total_seconds())
            except ValueError:
                pass
        monitor["state"] = state
        monitor["brand_state"] = dict(state)
        group = clean_text(str(monitor.get("group") or ""))
        brand = clean_text(str(monitor.get("brand") or ""))
        for item in news_settings.get("monitors", []):
            if (
                isinstance(item, dict)
                and clean_text(str(item.get("group") or "")) == group
                and clean_text(str(item.get("brand") or "")) == brand
            ):
                item["state"] = dict(state)
                item["brand_state"] = dict(state)
    if persist:
        persist_news_monitor_state(monitor)

def persist_news_monitor_state(monitor: Dict[str, object], force: bool = False) -> None:
    monitor_id = str(monitor.get("id") or "").strip()
    if not monitor_id:
        return
    now = time.time()
    if not force and now - news_state_persisted_at.get(monitor_id, 0) < 1:
        return
    news_state_persisted_at[monitor_id] = now
    state = repair_mojibake({**make_news_state(), **(monitor.get("state") or {})})
    try:
        with session_scope() as session:
            donor = get_donor_row(session, monitor_id)
            if donor is None:
                return
            donor.updated_at = datetime.utcnow()
            if donor.brand:
                donor.brand.state = state
    except Exception as exc:
        print(f"Failed to persist news monitor state {monitor_id}: {exc}", flush=True)

def news_monitor_thread_alive(monitor_id: object) -> bool:
    thread = news_scan_threads.get(str(monitor_id))
    return isinstance(thread, threading.Thread) and thread.is_alive()

def _run_queued_news_scan(monitor_id: str, manual: bool) -> None:
    try:
        scan_news_monitor(monitor_id, manual)
    finally:
        with news_lock:
            news_active_scan_ids.discard(monitor_id)
        news_scan_dispatch_event.set()

def ensure_news_scan_dispatcher() -> None:
    global news_scan_dispatcher_thread
    with news_lock:
        if isinstance(news_scan_dispatcher_thread, threading.Thread) and news_scan_dispatcher_thread.is_alive():
            return

        def dispatcher_loop() -> None:
            while True:
                news_scan_dispatch_event.wait()
                news_scan_dispatch_event.clear()
                while True:
                    with news_lock:
                        if len(news_active_scan_ids) >= NEWS_MAX_CONCURRENT_SCANS:
                            break
                        try:
                            monitor_id, manual = news_scan_queue.get_nowait()
                        except Empty:
                            break
                        news_queued_scan_ids.discard(monitor_id)
                        monitor = get_news_monitor(monitor_id)
                        state = monitor.get("state", {}) if monitor else {}
                        if (
                            not monitor
                            or monitor_id in news_active_scan_ids
                            or state.get("status") != "queued"
                        ):
                            continue
                        news_active_scan_ids.add(monitor_id)
                        thread = threading.Thread(
                            target=_run_queued_news_scan,
                            args=(monitor_id, manual),
                            daemon=True,
                        )
                        news_scan_threads[monitor_id] = thread
                    thread.start()

        news_scan_dispatcher_thread = threading.Thread(target=dispatcher_loop, daemon=True)
        news_scan_dispatcher_thread.start()

def enqueue_news_scan(monitor_id: str, manual: bool) -> bool:
    """Put a monitor into the shared FIFO queue unless it is already scheduled."""
    monitor_id = str(monitor_id)
    ensure_news_scan_dispatcher()
    with news_lock:
        if monitor_id in news_queued_scan_ids or monitor_id in news_active_scan_ids:
            return False
        news_queued_scan_ids.add(monitor_id)
        news_scan_queue.put((monitor_id, manual))
    news_scan_dispatch_event.set()
    return True

def transition_requested_at(monitor: Dict[str, object]) -> Optional[datetime]:
    state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    for key in ("stop_requested_at", "finished_at", "started_at"):
        parsed = parse_schedule_datetime(state.get(key))
        if parsed:
            return parsed
    return None

def is_stale_news_transition(monitor: Dict[str, object]) -> bool:
    state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    status = str(state.get("status") or "")
    if status not in {"pausing", "stopping"}:
        return False
    requested_at = transition_requested_at(monitor)
    timed_out = bool(requested_at and (datetime.now(MSK_TZ) - requested_at).total_seconds() >= NEWS_TRANSITION_TIMEOUT_SECONDS)
    return timed_out or not news_monitor_thread_alive(monitor.get("id"))

def finalize_stale_news_transition(monitor: Dict[str, object]) -> bool:
    if not is_stale_news_transition(monitor):
        return False
    state = dict(monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {})
    was_pausing = state.get("status") == "pausing"
    state.update(
        {
            "status": "partial" if was_pausing else "stopped",
            "stage": "Приостановлено" if was_pausing else "Остановлено",
            "error": "",
            "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
            "currenturl": "",
            "queue_size": 0,
            "active_tasks": 0,
            "active_urls": [],
        }
    )
    with news_lock:
        monitor["state"] = state
        monitor["brand_state"] = dict(state)
    return True

def cleanup_stale_news_transitions() -> None:
    changed: List[Dict[str, object]] = []
    with news_lock:
        monitors = [item for item in news_settings.get("monitors", []) if isinstance(item, dict)]
    for monitor in monitors:
        if finalize_stale_news_transition(monitor):
            changed.append(monitor)
    for monitor in changed:
        threading.Thread(target=persist_news_monitor_state, args=(monitor, True), daemon=True).start()

def update_brand_scan_state(
    target_type: str,
    target_id: str,
    status: str,
    started_at: float,
    found_products: int = 0,
    new_count: int = 0,
    data: Optional[Dict[str, object]] = None,
) -> None:
    if target_type not in {"news", "donor"}:
        return
    data = data or {}
    existing_state: Dict[str, object] = {}
    with news_lock:
        monitor = next((item for item in news_settings.get("monitors", []) if str(item.get("id")) == str(target_id)), None)
        if monitor and isinstance(monitor.get("state"), dict):
            existing_state = dict(monitor.get("state") or {})
    finished_at = datetime.now(MSK_TZ).isoformat(timespec="seconds")
    state = {
        **make_news_state(),
        **existing_state,
        "status": status or "idle",
        "started_at": existing_state.get("started_at") or datetime.fromtimestamp(started_at, MSK_TZ).isoformat(timespec="seconds"),
        "finished_at": finished_at,
        "last_scan_at": existing_state.get("last_scan_at") or finished_at,
        "found_products": found_products,
        "new_count": new_count,
        "data": data,
    }
    if data.get("csv"):
        state["last_csv"] = str(data.get("csv") or "")
    if data.get("missing_by_feed"):
        state["missing_by_feed"] = data.get("missing_by_feed")
    if data.get("error"):
        state["error"] = str(data.get("error") or "")
    state = repair_mojibake(state)
    with session_scope() as session:
        donor = get_donor_row(session, target_id)
        if donor and donor.brand:
            donor.brand.state = state
    with news_lock:
        if monitor:
            group = clean_text(str(monitor.get("group") or ""))
            brand = clean_text(str(monitor.get("brand") or ""))
            for item in news_settings.get("monitors", []):
                if (
                    isinstance(item, dict)
                    and clean_text(str(item.get("group") or "")) == group
                    and clean_text(str(item.get("brand") or "")) == brand
                ):
                    item["brand_state"] = dict(state)
                    item["state"] = dict(state)

class NewsScanStopped(Exception):
    pass

def get_news_stop_event(monitor_id: str) -> threading.Event:
    with news_lock:
        event = news_stop_events.get(monitor_id)
        if not event:
            event = threading.Event()
            news_stop_events[monitor_id] = event
        return event

def request_news_stop(monitor_id: str, mode: str) -> threading.Event:
    event = get_news_stop_event(monitor_id)
    monitor: Optional[Dict[str, object]] = None
    with news_lock:
        queued_not_started = monitor_id in news_queued_scan_ids and monitor_id not in news_active_scan_ids
        if queued_not_started:
            # The dispatcher skips entries whose id is no longer queued.
            news_queued_scan_ids.discard(monitor_id)
        news_stop_modes[monitor_id] = mode
    monitor = get_news_monitor(monitor_id)
    if monitor:
        update_news_monitor_state(
            monitor,
            persist=False,
            status=("partial" if mode == "pause" else "idle") if queued_not_started else ("pausing" if mode == "pause" else "stopping"),
            stage=("Приостановлено" if mode == "pause" else "Ожидание") if queued_not_started else ("Приостановка" if mode == "pause" else "Остановка"),
            currenturl="",
            stop_requested_at=datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        )
    if queued_not_started:
        with news_lock:
            news_stop_modes.pop(monitor_id, None)
        event.clear()
        news_scan_dispatch_event.set()
    else:
        event.set()
    if monitor:
        threading.Thread(target=persist_news_monitor_state, args=(monitor, True), daemon=True).start()
    return event

def collect_products_for_monitor(monitor: Dict[str, object], stop_signal: threading.Event) -> List[Dict[str, str]]:
    finish_signal = threading.Event()
    start_urls = normalize_start_urls(monitor.get("start_urls") or "", allow_empty=True)
    if not start_urls:
        raise RuntimeError("У донора не указаны стартовые URL для сканирования.")

    def progress_callback(payload: Dict[str, object]) -> None:
        log_message = str(payload.get("log_message") or "").strip()
        log_level = str(payload.get("log_level") or "info").strip() or "info"
        if log_message:
            add_news_log(monitor, log_message, log_level)
            event_state = {"last_event": log_message}
            if log_level == "warning":
                event_state["last_warning"] = log_message
            elif log_level == "error":
                event_state["error"] = log_message
            update_news_monitor_state(monitor, **event_state)
            if not any(key in payload for key in ("percent", "currenturl", "totalprocessed", "found_products")):
                return
        if stop_signal.is_set():
            return
        update_news_monitor_state(
            monitor,
            status="running",
            stage="Сканирование сайта-донора",
            percent=min(85, int(payload.get("percent", 0) or 0)),
            currenturl=str(payload.get("currenturl", "")),
            processed=int(payload.get("totalprocessed", 0) or 0),
            found_products=int(payload.get("found_products", 0) or 0),
            in_memory_products=int(payload.get("in_memory_products", payload.get("found_products", 0)) or 0),
            queue_size=int(payload.get("queue_size", 0) or 0),
            active_tasks=int(payload.get("active_tasks", 0) or 0),
            active_urls=list(payload.get("active_urls", []) or [])[:8],
            failed_pages=int(payload.get("failed_pages", 0) or 0),
            stall_seconds=int(payload.get("stall_seconds", 0) or 0),
            skipped=int(payload.get("skipped", 0) or 0),
            error=str(payload.get("error", "") or ""),
        )

    crawler = CollectOnlyCrawler(
        start_urls,
        int(time.time()),
        stop_signal,
        finish_signal,
        parse_thread_count(monitor.get("thread_count", 4)),
        project=None,
        exclusions=list(monitor.get("exclusions", DEFAULT_EXCLUSIONS)),
        product_url_filters=list(monitor.get("product_url_filters", [])),
        extraction_rules=normalize_extraction_rules(monitor.get("extraction_rules", {})),
        connection_method=normalize_connection_method(monitor.get("connection_method")),
        auto_connection_fallback=bool(monitor.get("auto_connection_fallback", True)),
        allow_empty_price=True,
        progress_callback=progress_callback,
    )
    crawler.run()
    products = crawler.snapshot_results()
    if crawler.fatal_error:
        message = f"{crawler.fatal_error}. Промежуточно хранится в памяти товаров: {len(products)}."
        update_news_monitor_state(
            monitor,
            status="error",
            error=message,
            found_products=len(products),
            in_memory_products=len(products),
            currenturl="",
        )
        raise RuntimeError(message)
    return products

def enrich_news_product(
    product: Dict[str, str],
    monitor: Dict[str, object],
    connection_method_state: Optional[Dict[str, object]] = None,
) -> Dict[str, str]:
    url = product.get("url", "")
    selector_settings = monitor.get("selector_settings", {}) if isinstance(monitor.get("selector_settings"), dict) else {}
    extraction_rules = normalize_extraction_rules(monitor.get("extraction_rules", {}))
    details = {
        "date_found": datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S"),
        "group": str(monitor.get("group") or ""),
        "brand": str(monitor.get("brand") or ""),
        "name": product.get("model", ""),
        "model": product.get("model", ""),
        "price": product.get("price", ""),
        "availability": "",
        "photo_url": "",
        "url": url,
    }
    fetcher = CollectOnlyCrawler(
        [url],
        int(time.time()),
        threading.Event(),
        threading.Event(),
        1,
        connection_method=normalize_connection_method(monitor.get("connection_method")),
        auto_connection_fallback=bool(monitor.get("auto_connection_fallback", True)),
        connection_method_state=connection_method_state,
        allow_empty_price=True,
    )
    html = fetcher.fetch(url) if url else ""
    if not html:
        return details
    soup = BeautifulSoup(html, "html.parser")
    name = extract_product_name(soup, str(selector_settings.get("name_selector", "")))
    product_data = extract_product_data(
        url,
        html,
        product.get("price", ""),
        extraction_rules,
        allow_empty_price=True,
    )
    if product_data:
        details["model"] = product_data.get("model", details["model"])
        details["price"] = product_data.get("price", details["price"])
    else:
        model_candidate = extract_model_by_markers(html, extraction_rules) or details["model"] or name
        prepared_model = prepare_rule_model(model_candidate, extraction_rules)
        if prepared_model:
            details["model"] = normalize_model(prepared_model, url)
    details["name"] = name or details["name"]
    details["availability"] = extract_availability(soup, str(selector_settings.get("availability_selector", "")))
    details["photo_url"] = extract_photo_url(soup, url, str(selector_settings.get("photo_selector", "")))
    return details

def create_news_csv(rows: List[Dict[str, str]], monitor: Dict[str, object], filename: str = "") -> Path:
    if not filename:
        filename = news_csv_filename(monitor)
    filename = output_text(filename)
    path = EXPORT_DIR / filename
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";")
        writer.writerow(
            [
                "Дата появления",
                "Группа",
                "Сайт/бренд",
                "Наименование",
                "Модель",
                "Цена",
                "Наличие",
                "Нет на сайтах",
                "URL товара",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    output_text(row.get("date_found", "")),
                    output_text(row.get("group", "")),
                    output_text(row.get("brand", "")),
                    output_text(row.get("name", "")),
                    output_text(row.get("model", "")),
                    output_text(row.get("price", "")),
                    output_text(row.get("availability", "")),
                    output_text(row.get("missing_on", "")),
                    output_text(row.get("url", "")),
                ]
            )
    return path

def build_email_message(
    sender_email: str,
    recipient: str,
    subject: str,
    body: str,
    csv_path: Optional[Path] = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient
    message.set_content(body)
    if csv_path:
        message.add_attachment(
            csv_path.read_bytes(),
            maintype="text",
            subtype="csv",
            filename=str(repair_mojibake_text(csv_path.name) or csv_path.name),
        )
    return message

def send_messages_to_recipients(
    host: str,
    port: int,
    security_mode: str,
    username: str,
    password: str,
    sender_email: str,
    recipients: List[str],
    subject: str,
    body: str,
    csv_path: Optional[Path] = None,
) -> None:
    context = ssl.create_default_context()
    failures: List[str] = []
    if security_mode == "tls":
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(username, password)
            for recipient in recipients:
                try:
                    server.send_message(
                        build_email_message(sender_email, recipient, subject, body, csv_path),
                        from_addr=sender_email,
                        to_addrs=[recipient],
                    )
                except Exception as exc:
                    failures.append(f"{recipient}: {exc}")
    else:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(username, password)
            for recipient in recipients:
                try:
                    server.send_message(
                        build_email_message(sender_email, recipient, subject, body, csv_path),
                        from_addr=sender_email,
                        to_addrs=[recipient],
                    )
                except Exception as exc:
                    failures.append(f"{recipient}: {exc}")
    if failures:
        raise RuntimeError("Не удалось отправить на: " + "; ".join(failures))

def feed_missing_labels(keys: Set[str], feed_code_sets: List[Dict[str, object]]) -> List[str]:
    if not keys:
        return []
    missing_feeds = []
    for feed in feed_code_sets:
        feed_codes = feed.get("codes", set())
        if not isinstance(feed_codes, set):
            feed_codes = set(feed_codes) if isinstance(feed_codes, list) else set()
        if not (keys & feed_codes):
            missing_feeds.append(str(feed.get("source_label") or feed.get("url") or "Фид"))
    return missing_feeds

def enrich_news_candidates(
    products: List[Dict[str, str]],
    monitor: Dict[str, object],
    feed_code_sets: List[Dict[str, object]],
    stop_signal: threading.Event,
    progress_callback,
) -> List[Dict[str, str]]:
    candidates: List[tuple[int, Dict[str, str]]] = []
    resolved: List[Optional[Dict[str, str]]] = [None] * len(products)

    for index, product in enumerate(products):
        keys = product_compare_keys(product)
        if not keys:
            candidates.append((index, product))
            continue
        missing_feeds = feed_missing_labels(keys, feed_code_sets)
        if not missing_feeds:
            details = {
                "date_found": datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S"),
                "group": str(monitor.get("group") or ""),
                "brand": str(monitor.get("brand") or ""),
                "name": product.get("model", ""),
                "model": product.get("model", ""),
                "price": product.get("price", ""),
                "availability": "",
                "photo_url": "",
                "url": product.get("url", ""),
            }
            resolved[index] = details
            progress_callback(index + 1, details.get("url", ""))
        else:
            candidates.append((index, product))

    if candidates and not stop_signal.is_set():
        max_workers = min(NEWS_ENRICH_WORKER_COUNT, max(1, parse_thread_count(monitor.get("thread_count", 4))), len(candidates))
        connection_method_state = {
            "active_method": normalize_connection_method(monitor.get("connection_method")),
            "lock": threading.Lock(),
        }
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(enrich_news_product, product, monitor, connection_method_state): (index, product)
                for index, product in candidates
            }
            completed = len(products) - len(candidates)
            for future in as_completed(future_to_index):
                if stop_signal.is_set():
                    raise NewsScanStopped()
                index, product = future_to_index[future]
                details = future.result()
                details["model"] = details.get("model") or product.get("model", "")
                resolved[index] = details
                completed += 1
                progress_callback(completed, details.get("url", product.get("url", "")))

    return [item for item in resolved if item]

def send_news_email_legacy(
    monitor: Optional[Dict[str, object]],
    new_count: int,
    test: bool = False,
    error_holder: Optional[List[str]] = None,
    missing_summary: Optional[List[Dict[str, object]]] = None,
) -> bool:
    with news_lock:
        smtp_config = dict(news_settings.get("smtp", {}))
    recipients = normalize_emails(smtp_config.get("recipients", []))
    username = str(smtp_config.get("username") or "").strip()
    password = str(smtp_config.get("password") or "").strip()
    sender_emails = normalize_emails(username)
    if not username or not password or not recipients:
        error_message = "Email не отправлен: заполните email-логин, пароль приложения и получателей SMTP"
        error_message = str(repair_mojibake_text(error_message))
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False
    if not sender_emails:
        error_message = "Email не отправлен: email-логин должен быть адресом почты"
        error_message = str(repair_mojibake_text(error_message))
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False
    sender_email = sender_emails[0]

    if test:
        subject = "Тест email-уведомлений"
        body = "Тестовое письмо отправлено из мониторинга новинок. SMTP-настройки работают."
    else:
        brand = str((monitor or {}).get("brand") or "донор")
        site_url = str((monitor or {}).get("site_url") or "")
        subject = f"Уведомление о новинках на сайте {brand}"
        lines = [f"На {site_url or brand} найдено всего: {new_count}"]
        for item in missing_summary or []:
            count = int(item.get("count") or 0)
            label = str(item.get("source_label") or item.get("url") or "сайт")
            lines.append(f"На сайте {label} не было найдено {count} новинок.")
        body = "\n".join(lines)
    subject = str(repair_mojibake_text(subject))
    body = str(repair_mojibake_text(body))

    smtp_defaults = default_smtp_settings()
    host = str(smtp_config.get("host") or smtp_defaults["host"])
    port = int(smtp_config.get("port") or smtp_defaults["port"])
    security_mode = str(smtp_config.get("security") or smtp_defaults["security"]).lower()
    try:
        send_messages_to_recipients(host, port, security_mode, username, password, sender_email, recipients, subject, body)
    except Exception as exc:
        error_message = f"Ошибка отправки email: {exc}"
        error_message = str(repair_mojibake_text(error_message))
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "error")
        return False
    add_news_log(monitor, "Тестовое email-сообщение отправлено" if test else f"Email-уведомление отправлено. Новинок: {new_count}", "success")
    return True

def send_news_email(
    monitor: Optional[Dict[str, object]],
    new_count: int,
    test: bool = False,
    error_holder: Optional[List[str]] = None,
    missing_summary: Optional[List[Dict[str, object]]] = None,
) -> bool:
    with news_lock:
        smtp_config = dict(news_settings.get("smtp", {}))
    recipients = normalize_emails(smtp_config.get("recipients", []))
    username = str(smtp_config.get("username") or "").strip()
    password = str(smtp_config.get("password") or "").strip()
    sender_emails = normalize_emails(username)
    if not username or not password or not recipients:
        error_message = "Email не отправлен: заполните email-логин, пароль приложения и получателей SMTP"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False
    if not sender_emails:
        error_message = "Email не отправлен: email-логин должен быть адресом почты"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False

    sender_email = sender_emails[0]
    csv_path: Optional[Path] = None
    if test:
        subject = "Тест email-уведомления"
        body = "Тестовое письмо отправлено из мониторинга новинок. SMTP-настройки работают."
    else:
        brand = str(repair_mojibake_text((monitor or {}).get("brand") or "донор"))
        site_url = str((monitor or {}).get("site_url") or "")
        subject = f"Уведомление о новинках на сайте {brand}"
        lines = [f"На {site_url or brand} найдено всего: {new_count}"]
        for item in missing_summary or []:
            count = int(item.get("count") or 0)
            label = str(repair_mojibake_text(item.get("source_label") or item.get("url") or "сайт"))
            lines.append(f"На сайте {label} не было найдено {count} новинок.")
        body = "\n".join(lines)

        state = (monitor or {}).get("state", {}) if isinstance((monitor or {}).get("state"), dict) else {}
        state_data = state.get("data", {}) if isinstance(state.get("data"), dict) else {}
        csv_filename = str(state.get("last_csv") or state_data.get("csv") or "")
        csv_path = resolve_export_file(csv_filename)

    smtp_defaults = default_smtp_settings()
    host = str(smtp_config.get("host") or smtp_defaults["host"])
    port = int(smtp_config.get("port") or smtp_defaults["port"])
    security_mode = str(smtp_config.get("security") or smtp_defaults["security"]).lower()
    try:
        send_messages_to_recipients(host, port, security_mode, username, password, sender_email, recipients, subject, body, csv_path)
    except Exception as exc:
        error_message = f"Ошибка отправки email: {exc}"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "error")
        return False

    add_news_log(
        monitor,
        "Тестовое email-сообщение отправлено" if test else f"Email-уведомление отправлено. Новинок: {new_count}",
        "success",
    )
    return True

def scan_news_monitor(monitor_id: str, manual: bool = False) -> None:
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return
    refresh_monitor_schedule_from_brand(monitor)
    started = time.time()
    stop_event = get_news_stop_event(monitor_id)
    stop_event.clear()
    with news_lock:
        news_stop_modes.pop(monitor_id, None)
    new_items: List[Dict[str, str]] = []
    products: List[Dict[str, str]] = []
    local_feeds: List[Dict[str, object]] = []
    feed_code_sets: List[Dict[str, object]] = []
    missing_summary: List[Dict[str, object]] = []
    availability_skipped = 0

    def check_stop_requested() -> None:
        if stop_event.is_set():
            raise NewsScanStopped()

    with news_lock:
        monitor["state"] = {
            **make_news_state("running"),
            "stage": "Подготовка",
            "started_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        }
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
    add_news_log(monitor, "Ручное сканирование новинок запущено" if manual else "Плановое сканирование новинок запущено", "info")
    add_news_log(monitor, "Начал сбор", "info")

    try:
        update_news_monitor_state(monitor, stage="Подготовка", percent=2)
        validate_monitor_selectors(monitor)
        add_news_log(
            monitor,
            f"Scan settings: URL={', '.join(monitor.get('start_urls', []))}; "
            f"method={monitor.get('connection_method')}; threads={monitor.get('thread_count')}",
            "info",
        )
        update_news_monitor_state(monitor, stage="Сканирование сайта-донора", percent=5)
        products = collect_products_for_monitor(monitor, stop_event)
        check_stop_requested()
        add_news_log(monitor, "Сбор закончил", "info")
        add_news_log(monitor, f"Сканирование сайта завершено. Найдено товаров: {len(products)}", "info")
        update_news_monitor_state(monitor, stage="Генерация и загрузка фидов ваших сайтов", percent=84, currenturl="")
        add_news_log(monitor, "Скачивание фида", "info")
        all_existing_codes, local_feeds, feed_code_sets = fetch_existing_vendor_code_sets()
        check_stop_requested()
        add_news_log(monitor, "Фид скачался", "info")
        add_news_log(
            monitor,
            f"Фиды обновлены после сбора донора: {len(local_feeds)}. Моделей всего: {len(all_existing_codes)}",
            "info",
        )
        update_news_monitor_state(
            monitor,
            stage="Сравнение с фидами",
            percent=86,
            candidate_products=len(products),
            found_products=len(products),
            compared_products=0,
            currenturl="",
        )
        add_news_log(monitor, "Началось сравнение", "info")
        known = monitor.get("known_new_products", {}) if isinstance(monitor.get("known_new_products"), dict) else {}
        def update_compare_progress(index: int, current_url: str = "") -> None:
            check_stop_requested()
            update_news_monitor_state(
                monitor,
                stage="Сравнение с фидами",
                percent=86 + int((index / max(1, len(products))) * 12),
                compared_products=index,
                currenturl=current_url,
            )

        enriched_products = enrich_news_candidates(products, monitor, feed_code_sets, stop_event, update_compare_progress)
        availability_exclusions = normalize_patterns((monitor.get("selector_settings") or {}).get("availability_exclusions", []))
        for details, product in zip(enriched_products, products):
            check_stop_requested()
            details["model"] = details.get("model") or product.get("model", "")
            if availability_is_excluded(details.get("availability", ""), availability_exclusions):
                availability_skipped += 1
                continue
            detail_keys = product_compare_keys(details) | product_compare_keys(product)
            if not detail_keys:
                continue
            missing_feeds = feed_missing_labels(detail_keys, feed_code_sets)
            if not missing_feeds:
                continue
            model_key = sorted(detail_keys)[0]
            details["missing_on"] = ", ".join(missing_feeds)
            details["missing_on_count"] = len(missing_feeds)
            new_items.append(details)
            known[model_key] = details
        missing_summary = build_missing_summary(new_items, feed_code_sets)
        add_news_log(monitor, "Сравнение закончилось", "info")
        if availability_skipped:
            add_news_log(monitor, f"Исключено по статусу наличия: {availability_skipped}", "info")
        for item in missing_summary:
            add_news_log(
                monitor,
                f"Нет на {item.get('source_label')}: {int(item.get('count') or 0)}",
                "info",
            )

        update_news_monitor_state(monitor, stage="Формирование CSV", percent=99, currenturl="")
        csv_path = create_news_csv(new_items, monitor)
        delete_news_csv_for_monitor(monitor, keep_filename=csv_path.name)
        elapsed = int(time.time() - started)
        with news_lock:
            monitor["known_new_products"] = known
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "completed",
                "stage": "Завершено",
                "percent": 100,
                "processed": len(products),
                "found_products": len(products),
                "candidate_products": len(products),
                "compared_products": len(products),
                "in_memory_products": len(products),
                "availability_skipped": availability_skipped,
                "queue_size": 0,
                "active_tasks": 0,
                "active_urls": [],
                "new_count": len(new_items),
                "missing_by_feed": missing_summary,
                "last_scan_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "last_csv": csv_path.name,
                "error": "",
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "currenturl": "",
            }
            monitor["brand_state"] = dict(monitor["state"])
            if normalize_schedule_type(monitor.get("schedule_type")) != "once":
                monitor["next_run_at"] = update_brand_next_run_at(monitor.get("brand_id"))
            save_news_settings()
        add_news_log(monitor, f"Сканирование завершено. Найдено новинок: {len(new_items)}. CSV: {csv_path.name}", "success")
        update_brand_scan_state(
            "donor",
            monitor_id,
            "completed",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={
                "csv": csv_path.name,
                "feeds": local_feeds,
                "missing_by_feed": missing_summary,
                "availability_skipped": availability_skipped,
            },
        )
        if new_items:
            send_news_email(monitor, len(new_items), missing_summary=missing_summary)
    except NewsScanStopped:
        elapsed = int(time.time() - started)
        with news_lock:
            stop_mode = news_stop_modes.get(monitor_id, "stop")
        partial_csv = ""
        if stop_mode == "pause" and new_items:
            partial_path = create_news_csv(new_items, monitor)
            partial_csv = partial_path.name
            delete_news_csv_for_monitor(monitor, keep_filename=partial_csv)
        missing_summary = build_missing_summary(new_items, feed_code_sets) if feed_code_sets else []
        with news_lock:
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "partial" if stop_mode == "pause" else "idle",
                "stage": "Приостановлено" if stop_mode == "pause" else "Ожидание",
                "error": "",
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "currenturl": "",
                "last_csv": partial_csv or monitor.get("state", {}).get("last_csv", ""),
                "new_count": len(new_items),
                "missing_by_feed": missing_summary,
                "processed": len(products),
                "found_products": len(products),
                "in_memory_products": len(products),
                "availability_skipped": availability_skipped,
                "queue_size": int(monitor.get("state", {}).get("queue_size", 0) or 0),
                "active_tasks": 0,
                "active_urls": [],
            }
            monitor["brand_state"] = dict(monitor["state"])
            save_news_settings()
        add_news_log(
            monitor,
            f"Сканирование новинок приостановлено. CSV: {partial_csv}" if stop_mode == "pause" else "Сканирование новинок остановлено",
            "warning",
        )
        update_brand_scan_state(
            "donor",
            monitor_id,
            "partial" if stop_mode == "pause" else "idle",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={"csv": partial_csv, "availability_skipped": availability_skipped},
        )
    except Exception as exc:
        elapsed = int(time.time() - started)
        with news_lock:
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "error",
                "stage": "Ошибка",
                "error": str(exc),
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "found_products": len(products),
                "in_memory_products": len(products),
                "availability_skipped": availability_skipped,
                "active_tasks": 0,
                "active_urls": [],
            }
            monitor["brand_state"] = dict(monitor["state"])
            save_news_settings()
        add_news_log(monitor, f"Ошибка сканирования новинок: {exc}", "error")
        update_brand_scan_state(
            "donor",
            monitor_id,
            "error",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={"error": str(exc)},
        )
    finally:
        with news_lock:
            news_stop_modes.pop(monitor_id, None)
            thread = news_scan_threads.get(monitor_id)
            if thread is threading.current_thread():
                news_scan_threads.pop(monitor_id, None)
        stop_event.clear()
