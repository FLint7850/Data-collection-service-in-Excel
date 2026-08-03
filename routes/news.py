"""HTTP routes for this application area."""

from flask import Blueprint

from runtime.news_tasks import (
    start_news_scan,
    feed_snapshot_path,
    persist_news_monitor_state,
    request_news_stop,
)
import threading
from config import MSK_TZ
from database.session import session_scope
from datetime import datetime
from flask import request, send_file
from models import Brand
from query_utils import normalize_search_text
from runtime.state import news_lock, news_settings, news_stop_events
from services.application import ensure_storage
from services.connections import normalize_connection_method
from services.normalization import jsonify, normalize_extraction_rules, normalize_patterns, normalize_selector_settings, normalize_start_urls, output_text, parse_db_int
from sqlalchemy import select
from services.scraping import clean_text
from services.news import (
    add_news_log,
    delete_news_records,
    delete_news_csv_for_monitor,
    get_news_monitor,
    make_news_monitor,
    make_news_state,
    public_news_configuration,
    public_news_brand_monitors,
    public_news_monitor,
    public_news_workspace,
    resolve_export_file,
    save_news_monitor,
    sync_brand_runtime_fields,
    unique_news_brand_name,
)
from services.progress_service import public_news_monitor_progress, publish_news_progress_snapshot
from services.projects import parse_thread_count

bp = Blueprint("routes_news", __name__)


@bp.get("/api/news")
def api_news():
    ensure_storage()
    scope = str(request.args.get("scope") or "").strip().lower()
    if scope == "workspace":
        return jsonify(public_news_workspace())
    if scope == "settings":
        return jsonify(public_news_configuration())
    return jsonify({"error": "Укажите scope=workspace или scope=settings"}), 400


@bp.get("/api/news/brands")
def api_search_news_brands():
    ensure_storage()
    query = clean_text(str(request.args.get("q") or ""))[:255]
    normalized_query = normalize_search_text(query)
    if len(normalized_query) < 2:
        return jsonify({"brands": []})

    with session_scope() as session:
        rows = session.execute(
            select(Brand.id, Brand.name)
            .where(Brand.search_name.contains(normalized_query, autoescape=True))
            .order_by(Brand.name, Brand.id)
            .limit(20)
        ).all()

    return jsonify({
        "brands": [
            {"id": int(brand_id), "name": str(name)}
            for brand_id, name in rows
        ],
    })


@bp.get("/api/news/monitors/<monitor_id>")
def api_get_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    return jsonify({"monitors": public_news_brand_monitors(monitor)})


@bp.patch("/api/news/monitors/<monitor_id>")
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
        if "product_url_exclusions" in payload:
            monitor["product_url_exclusions"] = normalize_patterns(payload.get("product_url_exclusions"))
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
        save_news_monitor(monitor)
    response_monitor = public_news_monitor(monitor)
    if "primary_donor_id" in payload:
        response_monitor["primary_donor_id"] = str(payload.get("primary_donor_id") or "")
    return jsonify({"monitor": response_monitor})


@bp.post("/api/news/monitors/<monitor_id>/scan")
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
            "stage": "Запуск",
            "started_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
            "last_csv": str(monitor.get("state", {}).get("last_csv") or ""),
        }
        monitor["brand_state"] = dict(monitor["state"])
        sync_brand_runtime_fields(monitor)
        persist_news_monitor_state(monitor, force=True)
        response_monitor = public_news_monitor_progress(monitor)
    if not start_news_scan(monitor_id, manual=True):
        return jsonify({"error": "Сканирование уже выполняется"}), 409
    return jsonify({"monitor": response_monitor})


@bp.post("/api/news/monitors/<monitor_id>/stop")
def api_stop_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    request_news_stop(monitor_id, "stop")
    with news_lock:
        response_monitor = public_news_monitor_progress(monitor)
    threading.Thread(
        target=add_news_log,
        args=(monitor, "Запрошена остановка сканирования новинок", "warning"),
        daemon=True,
    ).start()
    return jsonify({"monitor": response_monitor})


@bp.post("/api/news/monitors/<monitor_id>/pause")
def api_pause_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    request_news_stop(monitor_id, "pause")
    with news_lock:
        response_monitor = public_news_monitor_progress(monitor)
    threading.Thread(
        target=add_news_log,
        args=(monitor, "Запрошена приостановка сканирования новинок с сохранением результата", "warning"),
        daemon=True,
    ).start()
    return jsonify({"monitor": response_monitor})


@bp.post("/api/news/monitors/<monitor_id>/resume")
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
        response_monitor = public_news_monitor_progress(monitor)
    if not start_news_scan(monitor_id, manual=True):
        return jsonify({"error": "Сканирование уже выполняется"}), 409
    add_news_log(monitor, "Продолжение сканирования новинок запущено", "info")
    return jsonify({"monitor": response_monitor})


@bp.post("/api/news/monitors/<monitor_id>/reset-visual")
def api_reset_news_monitor_visual(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    group = clean_text(str(monitor.get("group") or ""))
    brand = clean_text(str(monitor.get("brand") or ""))
    active_statuses = {"running", "queued", "pausing", "stopping"}
    with news_lock:
        brand_monitors = [
            item
            for item in news_settings.get("monitors", [])
            if isinstance(item, dict)
            and clean_text(str(item.get("group") or "")) == group
            and clean_text(str(item.get("brand") or "")) == brand
        ]
        if any(str((item.get("state") or {}).get("status") or "") in active_statuses for item in brand_monitors):
            return jsonify({"error": "Нельзя сбрасывать статус, пока сканирование выполняется."}), 409
        previous_state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
        reset_state = make_news_state("idle")
        last_csv = str(previous_state.get("last_csv") or "")
        if last_csv:
            reset_state["last_csv"] = last_csv
        for item in brand_monitors:
            item["state"] = dict(reset_state)
            item["brand_state"] = dict(reset_state)
            item.pop("_last_progress_state", None)
        persist_news_monitor_state(monitor, force=True)
    state_patch = {
        "status": "idle",
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
        "last_event": "",
        "last_warning": "",
        "new_count": 0,
        "missing_by_feed": [],
        "last_scan_at": "",
        "error": "",
        "started_at": "",
        "finished_at": "",
        "elapsed_seconds": 0,
    }
    return jsonify({"monitor": {"id": str(monitor_id), "state": state_patch}})


@bp.post("/api/news/monitors")
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
        save_news_monitor(monitor)
    add_news_log(monitor, "Монитор новинок создан", "success")
    return jsonify({"monitor": public_news_monitor(monitor)})


@bp.delete("/api/news/monitors/<monitor_id>")
def api_delete_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    group = clean_text(str(monitor.get("group") or ""))
    brand = clean_text(str(monitor.get("brand") or ""))
    remove_brand = request.args.get("mode") == "brand"
    with news_lock:
        brand_monitors = [
            item
            for item in news_settings.get("monitors", [])
            if isinstance(item, dict)
            and clean_text(str(item.get("group") or "")) == group
            and clean_text(str(item.get("brand") or "")) == brand
        ]
    if not remove_brand and len(brand_monitors) < 2:
        return jsonify({"error": "Нельзя удалить единственного донора бренда"}), 409

    removed_monitors = (
        brand_monitors
        if remove_brand
        else [item for item in brand_monitors if str(item.get("id")) == monitor_id]
    )
    removed_ids = {str(item.get("id")) for item in removed_monitors}
    for removed_monitor in removed_monitors:
        request_news_stop(str(removed_monitor.get("id") or ""), "stop")
        delete_news_csv_for_monitor(removed_monitor)

    with news_lock:
        monitors = news_settings.get("monitors", [])
        news_settings["monitors"] = [
            item
            for item in monitors
            if isinstance(item, dict) and str(item.get("id")) not in removed_ids
        ]
        for item_id in removed_ids:
            news_stop_events.pop(item_id, None)
        delete_news_records(removed_ids, remove_brand=remove_brand)
        remaining_brand_monitors = [
            public_news_monitor(item)
            for item in news_settings.get("monitors", [])
            if isinstance(item, dict)
            and clean_text(str(item.get("group") or "")) == group
            and clean_text(str(item.get("brand") or "")) == brand
        ]
    publish_news_progress_snapshot()
    add_news_log(monitor, "Монитор новинок удален", "warning")
    return jsonify(
        {
            "ok": True,
            "removed_ids": sorted(removed_ids),
            "monitors": remaining_brand_monitors,
        }
    )


@bp.get("/api/news/monitors/<monitor_id>/download")
def api_download_news_csv(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "Монитор не найден"}), 404
    state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    state_data = state.get("data", {}) if isinstance(state.get("data"), dict) else {}
    filename = str(state.get("last_csv") or state_data.get("csv") or "")
    path = resolve_export_file(filename)
    if not path:
        return jsonify({"error": "Файл еще не готов"}), 404
    download_name = output_text(path.name)
    return send_file(path, as_attachment=True, download_name=download_name)


@bp.get("/api/news/feeds/<source>/<path:filename>")
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
    feed = next(
        (
            item for item in news_settings.get("feed_storage", [])
            if isinstance(item, dict)
            and str(item.get("source") or "") == source
            and str(item.get("filename") or "") == filename
        ),
        None,
    )
    path = feed_snapshot_path(feed) if isinstance(feed, dict) else None
    if path is None or not path.exists():
        return jsonify({"error": "Фид не найден"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(filename))
