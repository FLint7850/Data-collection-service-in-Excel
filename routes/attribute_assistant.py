"""HTTP API for the isolated Attribute Assistant workspace."""

from pathlib import Path

from flask import Blueprint, g, request, send_file
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from werkzeug.exceptions import RequestEntityTooLarge

from config import (
    ATTRIBUTE_ASSISTANT_JSON_MAX_BYTES,
    ATTRIBUTE_ASSISTANT_MAX_URLS,
    ATTRIBUTE_ASSISTANT_UPLOAD_MAX_BYTES,
)

from models import (
    AttributeAllowedValue,
    AttributeBatch,
    AttributeMappingRule,
    AttributeValueMappingRule,
    AttributeProductRevision,
    AttributeProduct,
    AttributeProductValue,
    AttributeTemplate,
    AttributeTemplateField,
    AttributeTemplateRevision,
)
from services.application import ensure_storage
from services.attribute_assistant import (
    add_allowed_value,
    allowed_value_options,
    assign_product_template,
    batch_report,
    apply_parsed_attributes,
    apply_similar_products,
    bulk_action,
    clean_text,
    create_batch_from_csv,
    create_batch_from_urls,
    copy_template,
    create_template_field,
    delete_attribute_batch,
    delete_attribute_template,
    delete_extra_product_value,
    delete_template_field,
    export_batch_csv,
    export_batch_report_csv,
    import_template_csv,
    normalize_key,
    normalize_value,
    preview_template_csv,
    product_history,
    process_product_donors,
    recommend_donors,
    resolve_export_path,
    resolve_original_path,
    restore_product_snapshot,
    restore_template_revision,
    replace_allowed_value_synonyms,
    save_allowed_value_revision,
    save_mapping_rule,
    save_value_mapping_rule,
    save_template_revision,
    list_mapping_rules,
    list_value_mapping_rules,
    snapshot_product,
    serialize_batch,
    serialize_product,
    serialize_template,
    serialize_value,
    update_product_value,
    update_template_from_csv,
    validate_template_field_update,
    workspace,
)
from services.normalization import jsonify


bp = Blueprint("routes_attribute_assistant", __name__)


def _json_body() -> dict:
    if (
        request.content_length is not None
        and request.content_length > ATTRIBUTE_ASSISTANT_JSON_MAX_BYTES
    ):
        raise RequestEntityTooLarge(
            description="JSON-запрос для модуля атрибутов превышает допустимый размер"
        )
    return request.get_json(silent=True) or {}


def _read_csv_upload(upload) -> bytes:
    data = upload.stream.read(ATTRIBUTE_ASSISTANT_UPLOAD_MAX_BYTES + 1)
    if len(data) > ATTRIBUTE_ASSISTANT_UPLOAD_MAX_BYTES:
        raise ValueError(
            "CSV-файл превышает допустимый размер "
            f"{ATTRIBUTE_ASSISTANT_UPLOAD_MAX_BYTES // (1024 * 1024)} МБ"
        )
    return data


def _template(template_id: int, *, load_allowed_values: bool = True, load_revisions: bool = False) -> AttributeTemplate:
    options = [
        selectinload(AttributeTemplate.category),
        selectinload(AttributeTemplate.fields),
    ]
    if load_allowed_values:
        options.append(
            selectinload(AttributeTemplate.fields)
            .selectinload(AttributeTemplateField.allowed_values)
            .selectinload(AttributeAllowedValue.synonyms)
        )
    if load_revisions:
        options.append(selectinload(AttributeTemplate.revisions))
    row = g.db.scalar(
        select(AttributeTemplate).where(AttributeTemplate.id == template_id).options(*options)
    )
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
        lazy = request.args.get("lazy", "").lower() in {"1", "true", "yes"}
        template = _template(
            template_id,
            load_allowed_values=not lazy,
            load_revisions=False,
        )
        counts = None
        if lazy and template.fields:
            field_ids = [field.id for field in template.fields]
            counts = dict(g.db.execute(
                select(AttributeAllowedValue.field_id, func.count(AttributeAllowedValue.id))
                .where(AttributeAllowedValue.field_id.in_(field_ids))
                .group_by(AttributeAllowedValue.field_id)
            ).all())
        return jsonify(serialize_template(
            template, include_values=True, include_allowed_values=not lazy, allowed_value_counts=counts
        ))
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
            _read_csv_upload(upload),
            name=request.form.get("name", ""),
            category=request.form.get("category", ""),
            product_type=request.form.get("product_type", ""),
            description=request.form.get("description", ""),
        )
        g.db.flush()
        return jsonify(serialize_template(template, include_values=True)), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/templates/<int:template_id>/fields")
def api_attribute_field_create(template_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        template = _template(template_id)
        create_template_field(
            g.db,
            template,
            group_name=payload.get("group_name", ""),
            name=payload.get("name", ""),
            value_type=payload.get("value_type", "select"),
            is_required=payload.get("is_required", True),
            is_composite=payload.get("is_composite", False),
            separator=payload.get("separator", "/"),
        )
        return jsonify(serialize_template(template, include_values=True)), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.delete("/api/attribute-assistant/fields/<int:field_id>")
def api_attribute_field_delete(field_id: int):
    ensure_storage()
    field = g.db.get(AttributeTemplateField, field_id)
    if not field:
        return jsonify({"error": "Атрибут не найден"}), 404
    template_id = field.template_id
    try:
        delete_template_field(g.db, field)
        return jsonify({"deleted_id": field_id, "template_id": template_id})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.get("/api/attribute-assistant/fields/<int:field_id>/allowed-values")
def api_attribute_allowed_values(field_id: int):
    ensure_storage()
    field = g.db.get(AttributeTemplateField, field_id)
    if not field:
        return jsonify({"error": "Атрибут не найден"}), 404
    try:
        limit = int(request.args.get("limit", "80"))
    except ValueError:
        limit = 80
    return jsonify(allowed_value_options(
        field, request.args.get("q", ""), limit,
        include_inactive=request.args.get("editor", "").lower() in {"1", "true", "yes"},
    ))


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
    if Path(upload.filename).suffix.lower() != ".csv":
        return jsonify({"error": "Файл товаров должен быть в CSV"}), 400
    try:
        template = _template(int(request.form.get("template_id", "0")))
        batch = create_batch_from_csv(
            g.db,
            template,
            _read_csv_upload(upload),
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
        if not isinstance(urls, list):
            raise ValueError("Ссылки должны быть переданы списком")
        if len(urls) > ATTRIBUTE_ASSISTANT_MAX_URLS:
            raise ValueError(
                f"За одну обработку можно передать не больше {ATTRIBUTE_ASSISTANT_MAX_URLS} ссылок"
            )
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
        batch = _batch(batch_id)
        return jsonify(serialize_batch(batch, detailed=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.delete("/api/attribute-assistant/batches/<int:batch_id>")
def api_attribute_batch_delete(batch_id: int):
    ensure_storage()
    try:
        batch = _batch(batch_id)
        deleted = delete_attribute_batch(g.db, batch)
        return jsonify({"ok": True, "deleted": deleted})
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.get("/api/attribute-assistant/products/<int:product_id>")
def api_attribute_product(product_id: int):
    ensure_storage()
    try:
        product = _product(product_id)
        return jsonify(serialize_product(product, detailed=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.post("/api/attribute-assistant/products/<int:product_id>/process")
def api_attribute_product_process(product_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        product = _product(product_id)
        snapshot_product(g.db, product, "Перед обработкой доноров")
        report = process_product_donors(
            g.db,
            product,
            payload.get("donor_ids") or [],
            url_overrides=payload.get("url_overrides") or {},
        )
        g.db.flush()
        return jsonify({"report": report, "product": serialize_product(product, detailed=True)})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/products/<int:product_id>/similar")
def api_attribute_product_similar(product_id: int):
    ensure_storage()
    try:
        product = _product(product_id)
        snapshot_product(g.db, product, "Перед поиском по похожим товарам")
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
        snapshot_product(g.db, value.product, f"Перед изменением {value.attribute_name}")
        update_product_value(
            value,
            action=clean_text(payload.get("action")),
            manual_value=payload.get("value", ""),
            dash_reason=payload.get("dash_reason", ""),
        )
        return jsonify(serialize_value(value))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.delete("/api/attribute-assistant/values/<int:value_id>")
def api_attribute_value_delete(value_id: int):
    ensure_storage()
    value = g.db.get(AttributeProductValue, value_id)
    if not value:
        return jsonify({"error": "Значение не найдено"}), 404
    try:
        product = delete_extra_product_value(g.db, value)
        return jsonify({"deleted_id": value_id, "product": serialize_product(product, detailed=True)})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/values/<int:value_id>/mapping-rule")
def api_attribute_value_mapping_rule(value_id: int):
    ensure_storage()
    value = g.db.get(AttributeProductValue, value_id)
    if not value or not value.template_field:
        return jsonify({"error": "Значение атрибута не найдено"}), 404
    payload = _json_body()
    try:
        snapshot_product(g.db, value.product, f"Перед сохранением значения {value.attribute_name}")
        rule = save_value_mapping_rule(
            g.db,
            donor_id=int(payload.get("donor_id") or 0),
            field=value.template_field,
            raw_value=payload.get("raw_value", ""),
            allowed_value_id=int(payload.get("allowed_value_id") or 0),
        )
        update_product_value(value, action="accept", manual_value=rule.allowed_value.value)
        details = dict(value.source_details or {})
        details["unknown_values"] = [
            item for item in list(details.get("unknown_values") or [])
            if not (
                isinstance(item, dict)
                and int(item.get("donor_id") or 0) == rule.donor_id
                and normalize_key(item.get("value")) == rule.normalized_raw_value
            )
        ]
        value.source_details = details
        g.db.flush()
        return jsonify({"rule_id": rule.id, "value": serialize_value(value)}), 201
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/batches/<int:batch_id>/bulk")
def api_attribute_batch_bulk(batch_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        batch = _batch(batch_id)
        for product in batch.products:
            snapshot_product(g.db, product, f"Перед массовым действием {clean_text(payload.get('action'))}")
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
        path = export_batch_csv(batch, ready_only=bool(_json_body().get("ready_only")))
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



@bp.post("/api/attribute-assistant/products/<int:product_id>/chatgpt/analyze")
def api_attribute_product_chatgpt_analyze(product_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        from services.attribute_ai import (
            apply_analysis,
            build_product_prompt,
            prepare_product_source,
            validate_analysis,
        )
        from services.attribute_chatgpt_control import analyze_with_chatgpt

        product = _product(product_id)
        snapshot_product(g.db, product, "Перед анализом ChatGPT")
        source_url, html, parsed, _resolved_by = prepare_product_source(
            g.db,
            product,
            payload.get("donor_ids") or [],
        )
        prompt, page_evidence = build_product_prompt(
            product,
            source_url=source_url,
            html=html,
            parsed=parsed,
        )
        # Do not keep a SQLite write transaction open while ChatGPT is thinking.
        g.db.commit()
        response = analyze_with_chatgpt(prompt)
        g.db.expire_all()
        product = _product(product_id)
        analysis = validate_analysis(
            product,
            response.get("text", ""),
            page_evidence=page_evidence,
        )
        changed = apply_analysis(g.db, product, analysis, source_url=source_url)
        g.db.flush()
        return jsonify({
            "changed": changed,
            "analysis": analysis,
            "source_url": source_url,
            "product": serialize_product(product, detailed=True),
        })
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503


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



@bp.post("/api/attribute-assistant/templates/preview")
def api_attribute_template_preview():
    ensure_storage()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Выберите CSV-файл шаблона"}), 400
    if Path(upload.filename).suffix.lower() != ".csv":
        return jsonify({"error": "Шаблон должен быть в CSV"}), 400
    try:
        template_id = int(request.form.get("template_id") or 0)
        template = _template(template_id) if template_id else None
        return jsonify(preview_template_csv(_read_csv_upload(upload), template))
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@bp.post("/api/attribute-assistant/templates/<int:template_id>/update-csv")
def api_attribute_template_update_csv(template_id: int):
    ensure_storage()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Выберите CSV-файл шаблона"}), 400
    if Path(upload.filename).suffix.lower() != ".csv":
        return jsonify({"error": "Шаблон должен быть в CSV"}), 400
    try:
        template = _template(template_id)
        preview = update_template_from_csv(
            g.db, template, _read_csv_upload(upload), mode=clean_text(request.form.get("mode")) or "merge"
        )
        g.db.flush()
        return jsonify({"preview": preview, "template": serialize_template(template, include_values=True)})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.delete("/api/attribute-assistant/templates/<int:template_id>")
def api_attribute_template_delete(template_id: int):
    ensure_storage()
    try:
        template = _template(template_id)
        delete_attribute_template(g.db, template)
        return jsonify({"ok": True, "deleted_id": template_id})
    except ValueError as error:
        status = 404 if str(error) == "Шаблон не найден" else 409
        return jsonify({"error": str(error)}), status


@bp.post("/api/attribute-assistant/templates/<int:template_id>/copy")
def api_attribute_template_copy(template_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        result = copy_template(
            g.db, _template(template_id), name=payload.get("name", ""), category=payload.get("category", "")
        )
        g.db.flush()
        return jsonify(serialize_template(result, include_values=True)), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.patch("/api/attribute-assistant/templates/<int:template_id>")
def api_attribute_template_update(template_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        template = _template(template_id)
        changes = {}
        if "name" in payload:
            name = clean_text(payload.get("name"))
            if not name:
                raise ValueError("Название шаблона не может быть пустым")
            if len(name) > 255:
                raise ValueError("Название шаблона не должно превышать 255 символов")
            duplicate = g.db.scalar(
                select(AttributeTemplate.id).where(
                    AttributeTemplate.category_id == template.category_id,
                    AttributeTemplate.name == name,
                    AttributeTemplate.id != template.id,
                )
            )
            if duplicate:
                raise ValueError("Шаблон с таким названием уже существует в этой категории")
            changes["name"] = name
        if "product_type" in payload:
            product_type = clean_text(payload.get("product_type"))
            if len(product_type) > 255:
                raise ValueError("Тип товара не должен превышать 255 символов")
            changes["product_type"] = product_type
        if "description" in payload:
            description = clean_text(payload.get("description"))
            if len(description) > 20_000:
                raise ValueError("Описание шаблона слишком длинное")
            changes["description"] = description
        for field in ("is_active", "is_default"):
            if field in payload:
                if not isinstance(payload.get(field), bool):
                    raise ValueError(f"{field} должен быть логическим значением")
                changes[field] = payload[field]
        if not changes:
            raise ValueError("Не передано ни одного изменяемого поля")
        save_template_revision(g.db, template, "before_manual_edit")
        for field, value in changes.items():
            setattr(template, field, value)
        template.version += 1
        g.db.flush()
        return jsonify(serialize_template(template, include_values=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        g.db.rollback()
        return jsonify({"error": "Изменение конфликтует с существующим шаблоном"}), 409


@bp.get("/api/attribute-assistant/templates/<int:template_id>/revisions")
def api_attribute_template_revisions(template_id: int):
    ensure_storage()
    try:
        if not g.db.get(AttributeTemplate, template_id):
            raise ValueError("Шаблон не найден")
        rows = g.db.execute(
            select(
                AttributeTemplateRevision.id,
                AttributeTemplateRevision.version,
                AttributeTemplateRevision.action,
                AttributeTemplateRevision.report,
                AttributeTemplateRevision.created_at,
            )
            .where(AttributeTemplateRevision.template_id == template_id)
            .order_by(AttributeTemplateRevision.created_at.desc(), AttributeTemplateRevision.id.desc())
        ).all()
        return jsonify({"items": [
            {
                "id": item.id,
                "version": item.version,
                "action": item.action,
                "report": item.report or {},
                "created_at": item.created_at.isoformat(timespec="seconds") if item.created_at else "",
            }
            for item in rows
        ]})
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.post("/api/attribute-assistant/templates/<int:template_id>/revisions/<int:revision_id>/restore")
def api_attribute_template_restore(template_id: int, revision_id: int):
    ensure_storage()
    try:
        template = _template(template_id)
        revision = g.db.get(AttributeTemplateRevision, revision_id)
        if not revision:
            raise ValueError("Версия шаблона не найдена")
        restore_template_revision(g.db, template, revision)
        return jsonify(serialize_template(template, include_values=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.patch("/api/attribute-assistant/fields/<int:field_id>")
def api_attribute_field_update(field_id: int):
    ensure_storage()
    field = g.db.get(AttributeTemplateField, field_id)
    if not field:
        return jsonify({"error": "Атрибут не найден"}), 404
    payload = _json_body()
    try:
        updates = validate_template_field_update(g.db, field, payload)
        save_template_revision(g.db, field.template, "before_field_edit", {"field_id": field.id})
        for key, value in updates.items():
            setattr(field, key, value)
        field.template.version += 1
        g.db.flush()
        return jsonify(serialize_template(field.template, include_values=True))
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        g.db.rollback()
        return jsonify({"error": "Атрибут с таким названием уже существует в этой группе"}), 409


@bp.patch("/api/attribute-assistant/allowed-values/<int:allowed_id>")
def api_attribute_allowed_update(allowed_id: int):
    ensure_storage()
    allowed = g.db.get(AttributeAllowedValue, allowed_id)
    if not allowed:
        return jsonify({"error": "Значение не найдено"}), 404
    payload = _json_body()
    try:
        save_allowed_value_revision(g.db, allowed, "before_dictionary_edit")
        if "value" in payload:
            normalized = normalize_value(payload.get("value"), allowed.field.value_type, False)
            key = normalize_key(normalized)
            if not key:
                raise ValueError("Значение не может быть пустым")
            duplicate = next((item for item in allowed.field.allowed_values if item.id != allowed.id and item.normalized_value == key), None)
            if duplicate:
                raise ValueError("Такое значение уже есть в справочнике")
            allowed.value = normalized
            allowed.normalized_value = key
        for key in ("is_active", "is_combination"):
            if key in payload:
                setattr(allowed, key, bool(payload.get(key)))
        if "sort_order" in payload:
            allowed.sort_order = int(payload.get("sort_order") or 0)
        if "synonyms" in payload:
            synonyms = payload.get("synonyms") or []
            if not isinstance(synonyms, list):
                raise ValueError("Синонимы должны быть переданы списком")
            replace_allowed_value_synonyms(g.db, allowed, synonyms)
        allowed.field.template.version += 1
        return jsonify({
            "value": {
                "id": allowed.id,
                "value": allowed.value,
                "is_combination": allowed.is_combination,
                "is_active": allowed.is_active,
                "synonyms": [item.synonym for item in allowed.synonyms],
            },
            "template_version": allowed.field.template.version,
        })
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.patch("/api/attribute-assistant/products/<int:product_id>/template")
def api_attribute_product_template(product_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        product = _product(product_id)
        template = _template(int(payload.get("template_id") or 0))
        assign_product_template(g.db, product, template)
        return jsonify(serialize_product(product, detailed=True))
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@bp.get("/api/attribute-assistant/products/<int:product_id>/donor-recommendations")
def api_attribute_product_donor_recommendations(product_id: int):
    ensure_storage()
    try:
        return jsonify({"items": recommend_donors(g.db, _product(product_id))})
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.post("/api/attribute-assistant/products/<int:product_id>/map-attribute")
def api_attribute_product_map_attribute(product_id: int):
    ensure_storage()
    payload = _json_body()
    try:
        product = _product(product_id)
        field = g.db.get(AttributeTemplateField, int(payload.get("field_id") or 0))
        donor_id = int(payload.get("donor_id") or 0)
        if not field or not product.template or field.template_id != product.template.id:
            raise ValueError("Атрибут шаблона не найден")
        snapshot_product(g.db, product, "Перед ручным сопоставлением атрибута")
        save_mapping_rule(
            g.db,
            donor_id=donor_id,
            template=product.template,
            field=field,
            donor_attribute_name=payload.get("donor_attribute_name", ""),
        )
        stats = apply_parsed_attributes(
            g.db,
            product,
            [{"name": payload.get("donor_attribute_name", ""), "value": payload.get("value", "")}],
            source=payload.get("source", "Ручное сопоставление"),
            priority=int(payload.get("priority") or 0),
            donor_id=donor_id,
            source_url=payload.get("source_url", ""),
        )
        return jsonify({"stats": stats, "product": serialize_product(product, detailed=True)})
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@bp.get("/api/attribute-assistant/mapping-rules")
def api_attribute_mapping_rules():
    ensure_storage()
    try:
        template_id = int(request.args.get("template_id") or 0)
    except ValueError:
        template_id = 0
    return jsonify({"items": list_mapping_rules(g.db, template_id or None)})


@bp.delete("/api/attribute-assistant/mapping-rules/<int:rule_id>")
def api_attribute_mapping_rule_delete(rule_id: int):
    ensure_storage()
    rule = g.db.get(AttributeMappingRule, rule_id)
    if not rule:
        return jsonify({"error": "Правило не найдено"}), 404
    g.db.delete(rule)
    return jsonify({"ok": True})


@bp.get("/api/attribute-assistant/value-mapping-rules")
def api_attribute_value_mapping_rules():
    ensure_storage()
    try:
        template_id = int(request.args.get("template_id") or 0)
    except ValueError:
        template_id = 0
    return jsonify({"items": list_value_mapping_rules(g.db, template_id or None)})


@bp.delete("/api/attribute-assistant/value-mapping-rules/<int:rule_id>")
def api_attribute_value_mapping_rule_delete(rule_id: int):
    ensure_storage()
    rule = g.db.get(AttributeValueMappingRule, rule_id)
    if not rule:
        return jsonify({"error": "Правило значения не найдено"}), 404
    g.db.delete(rule)
    return jsonify({"ok": True})


@bp.get("/api/attribute-assistant/products/<int:product_id>/history")
def api_attribute_product_history(product_id: int):
    ensure_storage()
    try:
        product = _product(product_id)
        return jsonify({"items": product_history(g.db, product)})
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.post("/api/attribute-assistant/products/<int:product_id>/history/<int:revision_id>/restore")
def api_attribute_product_history_restore(product_id: int, revision_id: int):
    ensure_storage()
    try:
        product = _product(product_id)
        revision = g.db.get(AttributeProductRevision, revision_id)
        if not revision:
            raise ValueError("Снимок не найден")
        restore_product_snapshot(g.db, product, revision)
        return jsonify(serialize_product(product, detailed=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@bp.get("/api/attribute-assistant/batches/<int:batch_id>/report")
def api_attribute_batch_report(batch_id: int):
    ensure_storage()
    try:
        return jsonify(batch_report(_batch(batch_id)))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.get("/api/attribute-assistant/batches/<int:batch_id>/report/download")
def api_attribute_batch_report_download(batch_id: int):
    ensure_storage()
    try:
        batch = _batch(batch_id)
        path = export_batch_report_csv(batch)
        return send_file(path, as_attachment=True, download_name=path.name, mimetype="text/csv")
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@bp.get("/api/attribute-assistant/batches/<int:batch_id>/original/download")
def api_attribute_batch_original_download(batch_id: int):
    ensure_storage()
    try:
        batch = _batch(batch_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    path = resolve_original_path(batch)
    if not path:
        return jsonify({"error": "Исходный файл не найден"}), 404
    return send_file(path, as_attachment=True, download_name=batch.source_filename or path.name, mimetype="text/csv")
