"""HTTP API for converting supplier price lists to normalized CSV files."""

import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, g, request, send_file

from config import (
    MSK_TZ,
    PRICE_CONVERTER_ALLOWED_SUFFIXES,
    PRICE_CONVERTER_DIR,
)
from runtime.state import price_converter_lock
from services.application import ensure_storage
from services.domain_revisions import bump_domain_revision
from services.normalization import jsonify, output_text, safe_filename
from services.price_converter_service import (
    clear_price_converter_storage,
    get_price_converter_row,
    make_price_converter_state,
    normalize_price_converter_state,
    normalize_promo_settings,
    normalize_sheet_number,
    public_price_converter_runtime,
    public_price_converter_settings,
    public_price_converter_state,
    remove_price_converter_export,
    resolve_price_converter_export_path,
    run_price_conversion,
)
from services.scraping import clean_text


bp = Blueprint("routes_price_converter", __name__)


def conversion_is_running(include_lock: bool = True) -> bool:
    if include_lock and price_converter_lock.locked():
        return True
    row = get_price_converter_row()
    state = normalize_price_converter_state(row.state)
    return state.get("status") == "running"


@bp.get("/api/price-converter")
def api_price_converter_state():
    ensure_storage()
    if request.args.get("compact") == "1":
        return jsonify(public_price_converter_runtime())
    return jsonify(public_price_converter_state())


@bp.patch("/api/price-converter")
def api_update_price_converter():
    ensure_storage()
    if conversion_is_running():
        return jsonify({"error": "Дождитесь окончания конвертации"}), 409
    payload = request.get_json(silent=True) or {}
    row = get_price_converter_row()
    if "model_field" in payload:
        row.model_field = clean_text(str(payload.get("model_field") or ""))[:255]
    if "price_field" in payload:
        row.price_field = clean_text(str(payload.get("price_field") or ""))[:255]
    if "promo_field" in payload or "promo_date" in payload:
        try:
            promo_field, promo_date = normalize_promo_settings(
                payload.get("promo_field", row.promo_field),
                payload.get("promo_date", row.promo_date),
            )
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        row.promo_field = promo_field
        row.promo_date = promo_date
    if "sheet_number" in payload:
        try:
            row.sheet_number = normalize_sheet_number(payload.get("sheet_number"))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
    g.db.commit()
    bump_domain_revision("price_converter")
    return jsonify(public_price_converter_settings())


@bp.post("/api/price-converter")
def api_upload_price_converter_file():
    ensure_storage()
    if conversion_is_running():
        return jsonify({"error": "Дождитесь окончания конвертации"}), 409
    uploads = request.files.getlist("file")
    if len(uploads) > 1:
        return jsonify({"error": "Можно загрузить только один файл"}), 400
    upload = uploads[0] if uploads else None
    if not upload or not upload.filename:
        return jsonify({"error": "Файл не выбран"}), 400

    original_filename = output_text(upload.filename)
    suffix = Path(original_filename).suffix.lower()
    if suffix not in PRICE_CONVERTER_ALLOWED_SUFFIXES:
        return jsonify({"error": "Можно загрузить только CSV, XLS или XLSX"}), 400

    row = get_price_converter_row()
    remove_price_converter_export(row)
    clear_price_converter_storage()
    stored_filename = (
        f"{datetime.now(MSK_TZ).strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:8]}_{safe_filename(Path(original_filename).stem)}{suffix}"
    )
    target = (PRICE_CONVERTER_DIR / stored_filename).resolve()
    if PRICE_CONVERTER_DIR.resolve() not in target.parents:
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
    row.state = make_price_converter_state()
    g.db.commit()
    bump_domain_revision("price_converter")
    return jsonify(public_price_converter_state())


@bp.delete("/api/price-converter")
def api_delete_price_converter_file():
    ensure_storage()
    if conversion_is_running():
        return jsonify({"error": "Дождитесь окончания конвертации"}), 409
    row = get_price_converter_row()
    remove_price_converter_export(row)
    clear_price_converter_storage()
    row.export_path = ""
    row.file = {}
    row.state = make_price_converter_state()
    g.db.commit()
    bump_domain_revision("price_converter")
    return jsonify(public_price_converter_state())


@bp.post("/api/price-converter/convert")
def api_convert_price_file():
    ensure_storage()
    if not price_converter_lock.acquire(blocking=False):
        return jsonify({"error": "Конвертация уже выполняется"}), 409
    try:
        if conversion_is_running(include_lock=False):
            return jsonify({"error": "Конвертация уже выполняется"}), 409
        try:
            return jsonify(run_price_conversion())
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except Exception as error:
            return jsonify({"error": f"Ошибка конвертации: {error}"}), 500
    finally:
        price_converter_lock.release()


@bp.get("/api/price-converter/download")
def api_download_price_converter_result():
    ensure_storage()
    row = get_price_converter_row()
    state = normalize_price_converter_state(row.state)
    if state.get("status") == "running":
        return jsonify({"error": "Файл будет доступен после окончания конвертации"}), 409
    filename = str(row.export_path or state.get("result_filename") or "")
    path = resolve_price_converter_export_path(filename)
    if not path:
        return jsonify({"error": "Файл еще не готов"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(path.name), mimetype="text/csv")
