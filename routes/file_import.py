"""HTTP routes for this application area."""

from flask import Blueprint

import uuid
from config import FILE_IMPORT_ALLOWED_SUFFIXES, FILE_IMPORT_DIR, MSK_TZ
from datetime import datetime
from flask import g, request, send_file
from pathlib import Path
from runtime.state import file_import_lock, file_import_stop_event
from services.application import ensure_storage
from services.normalization import (
    jsonify,
    normalize_file_import_exclusions,
    normalize_file_import_rules_text,
    output_text,
    safe_filename,
)
from services.scraping import clean_text
from services.domain_revisions import bump_domain_revision
from services.file_import_service import (
    clear_file_import_storage,
    file_import_worker_alive,
    get_file_import_row,
    is_file_import_active_state,
    make_file_import_state,
    normalize_file_import_state,
    public_file_import_progress,
    public_file_import_settings,
    public_file_import_state,
    remove_file_import_export,
    resolve_file_import_export_path,
    start_file_import_compare,
)

bp = Blueprint("routes_file_import", __name__)


@bp.patch("/api/file-import")
def api_update_file_import():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    row = get_file_import_row()
    if "exclusions" in payload:
        row.exclusions = normalize_file_import_exclusions(payload.get("exclusions"))
    if "model_field" in payload:
        row.model_field = clean_text(str(payload.get("model_field") or ""))[:255]
    if "price_field" in payload:
        row.price_field = clean_text(str(payload.get("price_field") or ""))[:255]
    if "replace_rules" in payload:
        row.replace_rules = normalize_file_import_rules_text(payload.get("replace_rules"))
    if "file" in payload:
        file_payload = payload.get("file")
        if not file_payload:
            row.file = {}
        elif isinstance(file_payload, dict):
            stored_filename = str(file_payload.get("stored_filename") or "").strip()
            base_dir = FILE_IMPORT_DIR.resolve()
            path = (FILE_IMPORT_DIR / stored_filename).resolve()
            if stored_filename and base_dir in path.parents and path.exists() and path.is_file():
                row.file = {
                    "original_filename": output_text(
                        str(file_payload.get("filename") or file_payload.get("original_filename") or path.name)
                    ),
                    "stored_filename": path.name,
                    "uploaded_at": str(
                        file_payload.get("uploaded_at")
                        or datetime.fromtimestamp(path.stat().st_mtime, MSK_TZ).isoformat(timespec="seconds")
                    ),
                }
    g.db.commit()
    bump_domain_revision("file_import")
    return jsonify(public_file_import_settings())


@bp.get("/api/file-import")
def api_file_import_state():
    ensure_storage()
    if request.args.get("compact") == "1":
        return jsonify(public_file_import_progress())
    return jsonify(public_file_import_state())


@bp.post("/api/file-import")
def api_upload_file_import():
    ensure_storage()
    if is_file_import_active_state(public_file_import_state().get("state")):
        return jsonify({"error": "Дождитесь окончания сравнения файла"}), 409
    uploads = request.files.getlist("file")
    if len(uploads) > 1:
        return jsonify({"error": "Можно загрузить только один файл"}), 400
    upload = uploads[0] if uploads else None
    if not upload or not upload.filename:
        return jsonify({"error": "Файл не выбран"}), 400
    original_filename = output_text(upload.filename)
    suffix = Path(original_filename).suffix.lower()
    if suffix not in FILE_IMPORT_ALLOWED_SUFFIXES:
        return jsonify({"error": "Можно загрузить только CSV, XLS или XLSX"}), 400

    row = get_file_import_row()
    remove_file_import_export(row)
    clear_file_import_storage()
    stored_filename = f"{datetime.now(MSK_TZ).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_filename(Path(original_filename).stem)}{suffix}"
    target = (FILE_IMPORT_DIR / stored_filename).resolve()
    if FILE_IMPORT_DIR.resolve() not in target.parents:
        return jsonify({"error": "Некорректное имя файла"}), 400
    upload.save(target)
    if suffix == ".xlsx":
        from services.file_validation import validate_xlsx_archive
        try:
            validate_xlsx_archive(target)
        except ValueError as error:
            target.unlink(missing_ok=True)
            return jsonify({"error": str(error)}), 400
    row.file = {
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "uploaded_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
    }
    row.export_path = ""
    row.state = make_file_import_state()
    g.db.commit()
    bump_domain_revision("file_import")
    return jsonify(public_file_import_state())


@bp.delete("/api/file-import")
def api_delete_file_import():
    ensure_storage()
    if is_file_import_active_state(public_file_import_state().get("state")):
        return jsonify({"error": "Дождитесь окончания сравнения файла"}), 409
    row = get_file_import_row()
    remove_file_import_export(row)
    clear_file_import_storage()
    row.export_path = ""
    row.file = {}
    row.state = make_file_import_state()
    g.db.commit()
    bump_domain_revision("file_import")
    return jsonify(public_file_import_state())


@bp.post("/api/file-import/compare")
def api_compare_file_import():
    ensure_storage()
    try:
        state = start_file_import_compare()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка запуска сравнения: {exc}"}), 500
    return jsonify(state)


@bp.post("/api/file-import/stop")
def api_stop_file_import():
    ensure_storage()
    with file_import_lock:
        active_thread = file_import_worker_alive()
        if active_thread:
            file_import_stop_event.set()
    row = get_file_import_row()
    state = normalize_file_import_state(getattr(row, "state", {}) or {})
    if is_file_import_active_state(state):
        row.state = {
            **state,
            "status": "stopped",
            "stage": "Остановлено",
            "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        }
    return jsonify(public_file_import_progress())


@bp.get("/api/file-import/download")
def api_download_file_import_result():
    ensure_storage()
    row = get_file_import_row()
    if is_file_import_active_state(getattr(row, "state", {}) or {}):
        return jsonify({"error": "Файл будет доступен после окончания сравнения"}), 409
    file_meta = row.file if isinstance(row.file, dict) else {}
    filename = str(row.export_path or file_meta.get("result_filename") or "")
    path = resolve_file_import_export_path(filename)
    if not path:
        return jsonify({"error": "Файл еще не готов"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(path.name))
