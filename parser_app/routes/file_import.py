"""File-import API endpoints."""



from parser_app.runtime import *  # noqa: F401,F403



@app.get("/api/file-import")
def api_file_import_state():
    ensure_storage()
    return jsonify(public_file_import_state())

@app.patch("/api/file-import")
def api_update_file_import():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    row = get_file_import_row()
    if "exclusions" in payload:
        row.exclusions = normalize_file_import_exclusions(payload.get("exclusions"))
    if "model_field" in payload:
        row.model_field = clean_text(str(payload.get("model_field") or ""))[:255]
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
                    "original_filename": output_text(str(file_payload.get("filename") or file_payload.get("original_filename") or path.name)),
                    "stored_filename": path.name,
                    "uploaded_at": str(file_payload.get("uploaded_at") or datetime.fromtimestamp(path.stat().st_mtime, MSK_TZ).isoformat(timespec="seconds")),
                }
    return jsonify(public_file_import_state())

@app.post("/api/file-import")
def api_upload_file_import():
    ensure_storage()
    uploads = request.files.getlist("file")
    if len(uploads) > 1:
        return jsonify({"error": "Можно загрузить только один файл"}), 400
    upload = uploads[0] if uploads else None
    if not upload or not upload.filename:
        return jsonify({"error": "Файл не выбран"}), 400
    original_filename = output_text(upload.filename)
    suffix = Path(original_filename).suffix.lower()
    if suffix not in FILE_IMPORT_ALLOWED_SUFFIXES:
        return jsonify({"error": "Можно загрузить только CSV или XLSX"}), 400

    row = get_file_import_row()
    remove_file_import_export(row)
    clear_file_import_storage()
    stored_filename = f"{datetime.now(MSK_TZ).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_filename(Path(original_filename).stem)}{suffix}"
    target = (FILE_IMPORT_DIR / stored_filename).resolve()
    if FILE_IMPORT_DIR.resolve() not in target.parents:
        return jsonify({"error": "Некорректное имя файла"}), 400
    upload.save(target)
    row.file = {
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "uploaded_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
    }
    row.export_path = ""
    return jsonify(public_file_import_state())

@app.delete("/api/file-import")
def api_delete_file_import():
    ensure_storage()
    row = get_file_import_row()
    remove_file_import_export(row)
    clear_file_import_storage()
    row.export_path = ""
    row.file = {}
    return jsonify(public_file_import_state())

@app.post("/api/file-import/compare")
def api_compare_file_import():
    ensure_storage()
    try:
        summary = compare_file_import_with_feeds()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Ошибка сравнения: {exc}"}), 500
    state = public_file_import_state()
    return jsonify({"summary": summary, **state})

@app.get("/api/file-import/download")
def api_download_file_import_result():
    ensure_storage()
    row = get_file_import_row()
    file_meta = row.file if isinstance(row.file, dict) else {}
    filename = str(row.export_path or file_meta.get("result_filename") or "")
    path = resolve_file_import_export_path(filename)
    if not path:
        return jsonify({"error": "CSV еще не готов"}), 404
    return send_file(path, as_attachment=True, download_name=output_text(path.name))
