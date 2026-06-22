"""News-monitor API endpoints."""



from parser_app.runtime import *  # noqa: F401,F403



@app.patch("/api/news/settings")
def api_update_news_settings():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    with news_lock:
        if "own_sites" in payload and isinstance(payload.get("own_sites"), list):
            own_sites_payload = [item for item in payload.get("own_sites", []) if isinstance(item, dict)]
            own_sites = []
            for index, item in enumerate(own_sites_payload, start=1):
                feed_url = normalize_feed_url(str(item.get("feed_url") or "").strip())
                if not feed_url:
                    continue
                feed_generate_url = normalize_feed_url(str(item.get("feed_generate_url") or "").strip())
                own_sites.append(
                    {
                        "name": clean_text(str(item.get("name") or "")) or f"Фид {index}",
                        "feed_url": feed_url,
                        "feed_generate_url": feed_generate_url,
                    }
                )
            feed_urls = [
                item["feed_url"]
                for item in own_sites
            ]
            feed_generate_urls = [
                item["feed_generate_url"]
                for item in own_sites
                if item.get("feed_generate_url")
            ]
            feed_urls = feed_urls or [DEFAULT_FEED_URL]
            feed_generate_urls = feed_generate_urls or [DEFAULT_FEED_GENERATE_URL]
            news_settings["own_sites"] = own_sites or [{"name": feed_source_label(DEFAULT_FEED_URL), "feed_url": DEFAULT_FEED_URL, "feed_generate_url": DEFAULT_FEED_GENERATE_URL}]
            news_settings["feed_urls"] = feed_urls
            news_settings["feed_url"] = feed_urls[0] if feed_urls else DEFAULT_FEED_URL
            news_settings["feed_generate_urls"] = feed_generate_urls
            news_settings["feed_generate_url"] = feed_generate_urls[0] if feed_generate_urls else DEFAULT_FEED_GENERATE_URL
        if "feed_url" in payload:
            news_settings["feed_url"] = str(payload.get("feed_url") or DEFAULT_FEED_URL).strip()
        if "feed_generate_url" in payload:
            news_settings["feed_generate_url"] = str(payload.get("feed_generate_url") or DEFAULT_FEED_GENERATE_URL).strip()
        if "feed_urls" in payload:
            feed_urls = normalize_feed_urls(payload.get("feed_urls") or DEFAULT_FEED_URL, DEFAULT_FEED_URL)
            news_settings["feed_urls"] = feed_urls
            news_settings["feed_url"] = feed_urls[0] if feed_urls else DEFAULT_FEED_URL
        if "feed_generate_urls" in payload:
            feed_generate_urls = normalize_feed_urls(payload.get("feed_generate_urls") or DEFAULT_FEED_GENERATE_URL, DEFAULT_FEED_GENERATE_URL)
            news_settings["feed_generate_urls"] = feed_generate_urls
            news_settings["feed_generate_url"] = feed_generate_urls[0] if feed_generate_urls else DEFAULT_FEED_GENERATE_URL
        if "auto_cleanup" in payload:
            news_settings["auto_cleanup"] = bool(payload.get("auto_cleanup"))
        if "smtp" in payload and isinstance(payload.get("smtp"), dict):
            smtp_payload = payload["smtp"]
            smtp = dict(news_settings.get("smtp", {}))
            smtp.pop("sender", None)
            for key in ("host", "security", "username"):
                if key in smtp_payload:
                    smtp[key] = str(smtp_payload.get(key) or "").strip()
            if "port" in smtp_payload:
                try:
                    smtp["port"] = int(smtp_payload.get("port") or 465)
                except (TypeError, ValueError):
                    smtp["port"] = 465
            if "password" in smtp_payload and str(smtp_payload.get("password") or "").strip():
                smtp["password"] = str(smtp_payload.get("password")).strip()
            if "recipients" in smtp_payload:
                smtp["recipients"] = normalize_emails(smtp_payload.get("recipients"))
            news_settings["smtp"] = smtp
        save_news_settings()
    return jsonify(public_news_settings())

@app.post("/api/news/email/test")
def api_test_news_email():
    ensure_storage()
    errors: List[str] = []
    if not send_news_email(None, 0, test=True, error_holder=errors):
        return jsonify({"error": errors[-1] if errors else "Email не отправлен. Проверьте SMTP-настройки и логи мониторинга."}), 500
    return jsonify({"ok": True})

@app.patch("/api/news/monitors/<monitor_id>")
def api_update_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    payload = request.get_json(silent=True) or {}
    with news_lock:
        old_group = clean_text(str(monitor.get("group") or ""))
        old_brand = clean_text(str(monitor.get("brand") or ""))
        if "brand" in payload:
            new_brand = clean_text(str(payload.get("brand") or monitor.get("brand") or ""))
            if new_brand:
                for item in news_settings.get("monitors", []):
                    if (
                        isinstance(item, dict)
                        and clean_text(str(item.get("group") or "")) == old_group
                        and clean_text(str(item.get("brand") or "")) == old_brand
                    ):
                        item["brand"] = new_brand
                monitor["brand"] = new_brand
        if "start_urls" in payload:
            start_urls = normalize_start_urls(payload.get("start_urls"), allow_empty=True)
            if start_urls:
                monitor["start_urls"] = start_urls
        if "site_url" in payload:
            monitor["site_url"] = str(payload.get("site_url") or "").strip()
        if "enabled" in payload:
            monitor["enabled"] = bool(payload.get("enabled"))
        if "schedule_type" in payload:
            schedule_type = str(payload.get("schedule_type") or "daily")
            monitor["schedule_type"] = schedule_type if schedule_type in {"daily", "weekly", "once"} else "daily"
        if "scan_time" in payload:
            monitor["scan_time"] = str(payload.get("scan_time") or "01:00")[:5]
        if "weekday" in payload:
            try:
                monitor["weekday"] = max(0, min(int(payload.get("weekday") or 0), 6))
            except (TypeError, ValueError):
                monitor["weekday"] = 0
        if "next_run_at" in payload:
            monitor["next_run_at"] = str(payload.get("next_run_at") or "")
        if "thread_count" in payload:
            monitor["thread_count"] = parse_thread_count(payload.get("thread_count"))
        if "connection_method" in payload:
            monitor["connection_method"] = normalize_connection_method(payload.get("connection_method"))
        if "auto_connection_fallback" in payload:
            monitor["auto_connection_fallback"] = bool(payload.get("auto_connection_fallback"))
        if "exclusions" in payload:
            exclusions = normalize_patterns(payload.get("exclusions"))
            monitor["exclusions"] = exclusions
        if "product_url_filters" in payload:
            monitor["product_url_filters"] = normalize_patterns(payload.get("product_url_filters"))
        if "extraction_rules" in payload:
            monitor["extraction_rules"] = normalize_extraction_rules(payload.get("extraction_rules"))
        if "selector_settings" in payload:
            monitor["selector_settings"] = normalize_selector_settings(payload.get("selector_settings"))
        if "primary_donor_id" in payload:
            primary_donor_id = str(payload.get("primary_donor_id") or "").strip()
            primary_donor_pk = parse_db_int(primary_donor_id)
            if primary_donor_pk:
                with session_scope() as session:
                    brand = session.get(Brand, parse_db_int(monitor.get("brand_id")))
                    if brand and any(donor.id == primary_donor_pk for donor in brand.donors):
                        brand.primary_donor_id = primary_donor_pk
        sync_brand_runtime_fields(monitor)
        save_news_settings()
    response_monitor = dict(monitor)
    if "primary_donor_id" in payload:
        response_monitor["primary_donor_id"] = parse_db_int(payload.get("primary_donor_id"))
    return jsonify({"monitor": response_monitor})

@app.post("/api/news/monitors/<monitor_id>/scan")
def api_scan_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    if not normalize_start_urls(monitor.get("start_urls") or "", allow_empty=True):
        return jsonify({"error": "У выбранного донора не указаны стартовые URL. Заполните поле \"Стартовые URL\" и сохраните настройки."}), 400
    if monitor.get("state", {}).get("status") in {"running", "queued"}:
        return jsonify({"error": "Сканирование уже выполняется"}), 409
    with news_lock:
        monitor["state"] = {
            **make_news_state("queued"),
            "stage": "В очереди запуска",
            "started_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
            "last_csv": str(monitor.get("state", {}).get("last_csv") or ""),
        }
        monitor["brand_state"] = dict(monitor["state"])
        sync_brand_runtime_fields(monitor)
        persist_news_monitor_state(monitor, force=True)
        response_monitor = dict(monitor)
    enqueue_news_scan(monitor_id, manual=True)
    return jsonify({"monitor": response_monitor})

@app.post("/api/news/monitors/<monitor_id>/stop")
def api_stop_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    request_news_stop(monitor_id, "stop")
    with news_lock:
        response_monitor = dict(monitor)
    threading.Thread(
        target=add_news_log,
        args=(monitor, "Запрошена остановка сканирования новинок", "warning"),
        daemon=True,
    ).start()
    return jsonify({"monitor": response_monitor})

@app.post("/api/news/monitors/<monitor_id>/pause")
def api_pause_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    request_news_stop(monitor_id, "pause")
    with news_lock:
        response_monitor = dict(monitor)
    threading.Thread(
        target=add_news_log,
        args=(monitor, "Запрошена приостановка сканирования новинок с сохранением результата", "warning"),
        daemon=True,
    ).start()
    return jsonify({"monitor": response_monitor})

@app.post("/api/news/monitors/<monitor_id>/resume")
def api_resume_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    if monitor.get("state", {}).get("status") in {"running", "queued", "pausing", "stopping"}:
        return jsonify({"error": "Сканирование уже выполняется"}), 409
    with news_lock:
        monitor["state"] = {**monitor.get("state", {}), "status": "queued", "stage": "Продолжение"}
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
        response_monitor = dict(monitor)
    enqueue_news_scan(monitor_id, manual=True)
    add_news_log(monitor, "Продолжение сканирования новинок поставлено в очередь", "info")
    return jsonify({"monitor": response_monitor})

@app.post("/api/news/monitors")
def api_create_news_monitor():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    urls = normalize_start_urls(payload.get("start_urls") or "", allow_empty=True)
    site_url = str(payload.get("site_url") or "").strip()
    group = clean_text(str(payload.get("group") or "Маржа"))
    brand = clean_text(str(payload.get("brand") or "Новый донор"))
    if payload.get("create_new_brand"):
        with news_lock:
            brand = unique_news_brand_name(group, brand if brand and brand != "Новый донор" else "Новый бренд")
    monitor = make_news_monitor(
        group,
        brand,
        urls,
        site_url,
    )
    with news_lock:
        news_settings.setdefault("monitors", []).append(monitor)
        save_news_settings()
    add_news_log(monitor, "Монитор новинок создан", "success")
    return jsonify({"monitor": dict(monitor)})

@app.delete("/api/news/monitors/<monitor_id>")
def api_delete_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    if request.args.get("mode") != "brand":
        group = clean_text(str(monitor.get("group") or ""))
        brand = clean_text(str(monitor.get("brand") or ""))
        with news_lock:
            brand_monitors = [
                item
                for item in news_settings.get("monitors", [])
                if isinstance(item, dict)
                and clean_text(str(item.get("group") or "")) == group
                and clean_text(str(item.get("brand") or "")) == brand
            ]
        if len(brand_monitors) < 2:
            return jsonify({"error": "Нельзя удалить единственного донора бренда"}), 409
    request_news_stop(monitor_id, "stop")
    delete_news_csv_for_monitor(monitor)
    with news_lock:
        monitors = news_settings.get("monitors", [])
        news_settings["monitors"] = [
            item
            for item in monitors
            if isinstance(item, dict) and str(item.get("id")) != monitor_id
        ]
        news_stop_events.pop(monitor_id, None)
        save_news_settings()
    add_news_log(monitor, "Монитор новинок удален", "warning")
    return jsonify({"ok": True, "monitors": [dict(item) for item in news_settings.get("monitors", []) if isinstance(item, dict)]})

@app.get("/api/news/monitors/<monitor_id>/download")
def api_download_news_csv(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    state_data = state.get("data", {}) if isinstance(state.get("data"), dict) else {}
    filename = str(state.get("last_csv") or state_data.get("csv") or "")
    path = resolve_export_file(filename)
    if not path:
        return jsonify({"error": "CSV еще не готов"}), 404
    download_name = output_text(path.name)
    return send_file(path, as_attachment=True, download_name=download_name)

@app.get("/api/news/feeds/<source>/<path:filename>")
def api_download_news_feed(source: str, filename: str):
    ensure_storage()
    allowed_names = {
        str(feed.get("filename") or "")
        for feed in news_settings.get("feed_storage", [])
        if isinstance(feed, dict)
        and str(feed.get("source") or "") == source
    }
    if filename not in allowed_names:
        return jsonify({"error": "Фид не найден"}), 404
    feed_dir = source_feed_dir(source).resolve()
    path = (feed_dir / filename).resolve()
    if feed_dir not in path.parents or not path.exists():
        return jsonify({"error": "Фид не найден"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(filename))
