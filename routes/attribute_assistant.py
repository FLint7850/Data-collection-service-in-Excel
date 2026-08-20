"""HTTP API for the isolated Attribute Assistant workspace."""

from pathlib import Path

from flask import Blueprint, g, request, send_file

from models import (
    AttributeBatch,
    AttributeProduct,
    AttributeProductValue,
    AttributeTemplate,
    AttributeTemplateField,
)
from services.application import ensure_storage
from services.attribute_assistant import (
    add_allowed_value,
    apply_similar_products,
    bulk_action,
    clean_text,
    create_batch_from_csv,
    create_batch_from_urls,
    delete_batch_files,
    export_batch_csv,
    import_template_csv,
    process_product_donors,
    resolve_export_path,
    save_mapping_rule,
    serialize_batch,
    serialize_product,
    serialize_template,
    serialize_value,
    update_product_value,
    workspace,
)
from services.normalization import jsonify


bp = Blueprint("routes_attribute_assistant", __name__)


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


def _template(template_id: int) -> AttributeTemplate:
    row = g.db.get(AttributeTemplate, template_id)
    if not row:
        raise ValueError("Шаблон не найден")
    return row


def _batch(batch_id: int) -> AttributeBatch:
    row = g.db.get(AttributeBatch, batch_id)
    if not row:
        raise ValueError("Пакет не найден")
    return row


def _product(product_id: int) -> AttributeProduct:
    row = g.db.get(AttributeProduct, product_id)
    if not row:
        raise ValueError("Товар не найден")
    return row


@bp.get("/api/attribute-assistant")
def api_attribute_workspace():
    ensure_storage()
    return jsonify(workspace(g.db))


@bp.get("/api/attribute-assistant/templates/<int:template_id>")
def api_attribute_template(template_id: int):
    ensure_storage()
    try:
        return jsonify(serialize_template(_template(template_id), include_values=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.post("/api/attribute-assistant/templates/import")
def api_attribute_template_import():
    ensure_storage()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Выберите CSV-файл шаблона"}), 400
    if Path(upload.filename).suffix.lower() != ".csv":
        return jsonify({"error": "Шаблон должен быть в CSV"}), 400
    try:
        template = import_template_csv(
            g.db,
            upload.read(),
            name=request.form.get("name", ""),
            category=request.form.get("category", ""),
            product_type=request.form.get("product_type", ""),
            description=request.form.get("description", ""),
        )
        g.db.flush()
        return jsonify(serialize_template(template, include_values=True)), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/fields/<int:field_id>/allowed-values")
def api_attribute_allowed_value(field_id: int):
    ensure_storage()
    field = g.db.get(AttributeTemplateField, field_id)
    if not field:
        return jsonify({"error": "Атрибут не найден"}), 404
    payload = _json_body()
    try:
        allowed = add_allowed_value(g.db, field, payload.get("value", ""), payload.get("synonym", ""))
        g.db.flush()
        return jsonify({
            "id": allowed.id,
            "value": allowed.value,
            "synonyms": [item.synonym for item in allowed.synonyms],
        }), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/batches/import")
def api_attribute_batch_import():
    ensure_storage()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Выберите CSV-файл товаров"}), 400
    try:
        template = _template(int(request.form.get("template_id", "0")))
        batch = create_batch_from_csv(
            g.db,
            template,
            upload.read(),
            filename=upload.filename,
            name=request.form.get("name", ""),
            processing_mode=request.form.get("processing_mode", "suggest"),
        )
        g.db.flush()
        return jsonify(serialize_batch(batch, detailed=True)), 201
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/batches/urls")
def api_attribute_batch_urls():
    ensure_storage()
    payload = _json_body()
    try:
        template_id = int(payload.get("template_id") or 0)
        template = _template(template_id) if template_id else None
        urls = payload.get("urls") or []
        if isinstance(urls, str):
            urls = urls.splitlines()
        batch = create_batch_from_urls(
            g.db,
            urls,
            template=template,
            name=payload.get("name", ""),
            processing_mode=payload.get("processing_mode", "suggest"),
        )
        g.db.flush()
        return jsonify(serialize_batch(batch, detailed=True)), 201
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@bp.get("/api/attribute-assistant/batches/<int:batch_id>")
def api_attribute_batch(batch_id: int):
    ensure_storage()
    try:
        return jsonify(serialize_batch(_batch(batch_id), detailed=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.delete("/api/attribute-assistant/batches/<int:batch_id>")
def api_attribute_batch_delete(batch_id: int):
    ensure_storage()
    try:
        batch = _batch(batch_id)
        delete_batch_files(batch)
        g.db.delete(batch)
        return jsonify({"ok": True})
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.get("/api/attribute-assistant/products/<int:product_id>")
def api_attribute_product(product_id: int):
    ensure_storage()
    try:
        return jsonify(serialize_product(_product(product_id), detailed=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.post("/api/attribute-assistant/products/<int:product_id>/process")
def api_attribute_product_process(product_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        product = _product(product_id)
        report = process_product_donors(g.db, product, payload.get("donor_ids") or [])
        g.db.flush()
        return jsonify({"report": report, "product": serialize_product(product, detailed=True)})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/products/<int:product_id>/similar")
def api_attribute_product_similar(product_id: int):
    ensure_storage()
    try:
        product = _product(product_id)
        changed = apply_similar_products(g.db, product)
        return jsonify({"changed": changed, "product": serialize_product(product, detailed=True)})
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.patch("/api/attribute-assistant/values/<int:value_id>")
def api_attribute_value_update(value_id: int):
    ensure_storage()
    value = g.db.get(AttributeProductValue, value_id)
    if not value:
        return jsonify({"error": "Значение не найдено"}), 404
    payload = _json_body()
    try:
        update_product_value(
            value,
            action=clean_text(payload.get("action")),
            manual_value=payload.get("value", ""),
            dash_reason=payload.get("dash_reason", ""),
        )
        return jsonify(serialize_value(value))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/batches/<int:batch_id>/bulk")
def api_attribute_batch_bulk(batch_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        batch = _batch(batch_id)
        changed = bulk_action(
            batch,
            clean_text(payload.get("action")),
            int(payload.get("minimum_confidence") or 90),
            payload.get("dash_reason", ""),
        )
        return jsonify({"changed": changed, "batch": serialize_batch(batch, detailed=True)})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/mapping-rules")
def api_attribute_mapping_rule():
    ensure_storage()
    payload = _json_body()
    try:
        template = _template(int(payload.get("template_id") or 0))
        field = g.db.get(AttributeTemplateField, int(payload.get("field_id") or 0))
        if not field or field.template_id != template.id:
            raise ValueError("Атрибут шаблона не найден")
        rule = save_mapping_rule(
            g.db,
            donor_id=int(payload.get("donor_id") or 0),
            template=template,
            field=field,
            donor_attribute_name=payload.get("donor_attribute_name", ""),
        )
        g.db.flush()
        return jsonify({"id": rule.id, "ok": True}), 201
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/batches/<int:batch_id>/export")
def api_attribute_export(batch_id: int):
    ensure_storage()
    try:
        batch = _batch(batch_id)
        path = export_batch_csv(batch)
        return jsonify({"ok": True, "filename": path.name})
    except ValueError as error:
        return jsonify({"error": str(error)}), 409


@bp.get("/api/attribute-assistant/batches/<int:batch_id>/download")
def api_attribute_download(batch_id: int):
    ensure_storage()
    try:
        batch = _batch(batch_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    path = resolve_export_path(batch)
    if not path:
        return jsonify({"error": "Экспорт ещё не сформирован"}), 404
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="text/csv")



@bp.get("/api/attribute-assistant/chatgpt/status")
def api_attribute_chatgpt_status():
    ensure_storage()
    from services.attribute_chatgpt_control import chatgpt_status

    return jsonify(chatgpt_status())


@bp.post("/api/attribute-assistant/chatgpt/login")
def api_attribute_chatgpt_login():
    ensure_storage()
    from services.attribute_chatgpt_control import start_device_login

    try:
        return jsonify(start_device_login())
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503


@bp.post("/api/attribute-assistant/chatgpt/logout")
def api_attribute_chatgpt_logout():
    ensure_storage()
    from services.attribute_chatgpt_control import logout_chatgpt

    try:
        return jsonify(logout_chatgpt())
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503

