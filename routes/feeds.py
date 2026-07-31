"""HTTP routes for this application area."""

from flask import Blueprint

from services.core_service import (
    MSK_TZ,
    Optional,
    OwnSite,
    Response,
    SupplierFeed,
    datetime,
    ensure_storage,
    feed_comparison_lock,
    feed_comparison_stop_event,
    g,
    jsonify,
    output_text,
    request,
    select,
    send_file,
)
from services.feed_service import (
    feed_comparison_worker_alive,
    get_feed_comparison_row,
    is_feed_comparison_active_state,
    normalize_feed_comparison_state,
    public_feed_comparison_progress,
    public_feed_comparison_state,
    public_own_site,
    public_supplier_feed,
    resolve_feed_comparison_export_path,
    start_feed_comparison,
    sync_own_sites_runtime,
    validate_feed_comparison_site_payload,
)

bp = Blueprint("routes_feeds", __name__)


def ensure_feed_comparison_editable() -> Optional[tuple[Response, int]]:
    comparison = get_feed_comparison_row()
    if is_feed_comparison_active_state(comparison.state):
        return jsonify({"error": "Дождитесь окончания сравнения фидов"}), 409
    return None


@bp.get("/api/feed-comparison")
def api_feed_comparison_state():
    ensure_storage()
    if request.args.get("compact") == "1":
        return jsonify(public_feed_comparison_progress())
    return jsonify(public_feed_comparison_state())


@bp.post("/api/feed-comparison/own-sites")
def api_create_feed_comparison_own_site():
    ensure_storage()
    blocked = ensure_feed_comparison_editable()
    if blocked:
        return blocked
    try:
        data = validate_feed_comparison_site_payload(request.get_json(silent=True), supplier=False)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    duplicate = g.db.scalar(select(OwnSite).where(OwnSite.feed_url == data["feed_url"]))
    if duplicate:
        return jsonify({"error": "Фид вашего сайта с такой ссылкой уже добавлен"}), 409
    row = OwnSite(**data)
    g.db.add(row)
    g.db.flush()
    sync_own_sites_runtime(g.db)
    return jsonify({"own_site": public_own_site(row)}), 201


@bp.patch("/api/feed-comparison/own-sites/<int:site_id>")
def api_update_feed_comparison_own_site(site_id: int):
    ensure_storage()
    blocked = ensure_feed_comparison_editable()
    if blocked:
        return blocked
    row = g.db.get(OwnSite, site_id)
    if row is None:
        return jsonify({"error": "Фид вашего сайта не найден"}), 404
    try:
        data = validate_feed_comparison_site_payload(request.get_json(silent=True), supplier=False)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    duplicate = g.db.scalar(
        select(OwnSite).where(OwnSite.feed_url == data["feed_url"], OwnSite.id != site_id)
    )
    if duplicate:
        return jsonify({"error": "Фид вашего сайта с такой ссылкой уже добавлен"}), 409
    row.name = data["name"]
    row.feed_url = data["feed_url"]
    row.feed_generate_url = data["feed_generate_url"]
    g.db.flush()
    sync_own_sites_runtime(g.db)
    return jsonify({"own_site": public_own_site(row)})


@bp.delete("/api/feed-comparison/own-sites/<int:site_id>")
def api_delete_feed_comparison_own_site(site_id: int):
    ensure_storage()
    blocked = ensure_feed_comparison_editable()
    if blocked:
        return blocked
    row = g.db.get(OwnSite, site_id)
    if row is None:
        return jsonify({"error": "Фид вашего сайта не найден"}), 404
    g.db.delete(row)
    g.db.flush()
    sync_own_sites_runtime(g.db)
    return jsonify({"ok": True, "id": site_id})


@bp.post("/api/feed-comparison/suppliers")
def api_create_supplier_feed():
    ensure_storage()
    blocked = ensure_feed_comparison_editable()
    if blocked:
        return blocked
    try:
        data = validate_feed_comparison_site_payload(request.get_json(silent=True), supplier=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    duplicate = g.db.scalar(select(SupplierFeed).where(SupplierFeed.feed_url == data["feed_url"]))
    if duplicate:
        return jsonify({"error": "Фид поставщика с такой ссылкой уже добавлен"}), 409
    row = SupplierFeed(**data)
    g.db.add(row)
    g.db.flush()
    return jsonify({"supplier": public_supplier_feed(row)}), 201


@bp.patch("/api/feed-comparison/suppliers/<int:supplier_id>")
def api_update_supplier_feed(supplier_id: int):
    ensure_storage()
    blocked = ensure_feed_comparison_editable()
    if blocked:
        return blocked
    row = g.db.get(SupplierFeed, supplier_id)
    if row is None:
        return jsonify({"error": "Фид поставщика не найден"}), 404
    try:
        data = validate_feed_comparison_site_payload(request.get_json(silent=True), supplier=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    duplicate = g.db.scalar(
        select(SupplierFeed).where(
            SupplierFeed.feed_url == data["feed_url"],
            SupplierFeed.id != supplier_id,
        )
    )
    if duplicate:
        return jsonify({"error": "Фид поставщика с такой ссылкой уже добавлен"}), 409
    row.name = data["name"]
    row.feed_url = data["feed_url"]
    row.model_field = data["model_field"]
    row.exclusions = data["exclusions"]
    row.replace_rules = data["replace_rules"]
    g.db.flush()
    return jsonify({"supplier": public_supplier_feed(row)})


@bp.delete("/api/feed-comparison/suppliers/<int:supplier_id>")
def api_delete_supplier_feed(supplier_id: int):
    ensure_storage()
    blocked = ensure_feed_comparison_editable()
    if blocked:
        return blocked
    row = g.db.get(SupplierFeed, supplier_id)
    if row is None:
        return jsonify({"error": "Фид поставщика не найден"}), 404
    g.db.delete(row)
    g.db.flush()
    return jsonify({"ok": True, "id": supplier_id})


@bp.post("/api/feed-comparison/start")
def api_start_feed_comparison():
    ensure_storage()
    try:
        return jsonify(start_feed_comparison())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка запуска сравнения: {exc}"}), 500


@bp.post("/api/feed-comparison/stop")
def api_stop_feed_comparison():
    ensure_storage()
    with feed_comparison_lock:
        if feed_comparison_worker_alive():
            feed_comparison_stop_event.set()
    row = get_feed_comparison_row()
    state = normalize_feed_comparison_state(row.state)
    if is_feed_comparison_active_state(state):
        row.state = {
            **state,
            "status": "stopped",
            "stage": "Остановка",
            "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        }
    return jsonify(public_feed_comparison_progress())


@bp.get("/api/feed-comparison/download")
def api_download_feed_comparison():
    ensure_storage()
    row = get_feed_comparison_row()
    if is_feed_comparison_active_state(row.state):
        return jsonify({"error": "Файл будет доступен после окончания сравнения"}), 409
    path = resolve_feed_comparison_export_path(str(row.export_path or ""))
    if not path:
        return jsonify({"error": "Файл еще не готов"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(path.name))


