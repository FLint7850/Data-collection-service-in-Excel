"""HTTP API for the Attribute Assistant workspace."""

from __future__ import annotations

import uuid
from pathlib import Path

import requests
from flask import Blueprint, Response, g, request, send_file, session

from models import AttributeAllowedValue, AttributeDonor, AttributeTemplateField, AttributeValueSynonym
from services.application import ensure_storage
from services.attribute_assistant import (
    add_value_synonym,
    allowed_value_field_ids,
    assistant_subdir,
    batch_report,
    batch_summary,
    bulk_update_values,
    copy_template,
    create_allowed_value,
    create_empty_template,
    create_template_field,
    delete_batch_files,
    delete_template_field,
    delete_value_synonym,
    export_batch_csv,
    export_batch_report_csv,
    export_template_csv,
    field_allowed_values,
    import_products_csv,
    import_products_from_urls,
    import_template_csv,
    list_attribute_donors,
    list_template_revisions,
    load_batch,
    load_product_page,
    load_product,
    load_template,
    parse_donor_for_product,
    preview_template_csv,
    product_logs,
    public_batch,
    public_donor,
    public_product,
    public_template,
    resolve_batch_export,
    resolve_batch_report,
    restore_template_revision,
    reorder_template_fields,
    rollback_value_change,
    save_attribute_donor,
    save_mapping_rule,
    update_product_value,
    update_allowed_value_settings,
    update_template_field,
    workspace_payload,
    _validate_http_url,
)
from services.normalization import jsonify, safe_filename
from services.attribute_ai import (
    ATTRIBUTE_ANALYSIS_OUTPUT_SCHEMA,
    apply_attribute_suggestions,
    attribute_analysis_needs_web_fallback,
    build_attribute_url_analysis_prompt,
    validate_attribute_analysis,
)
from services.codex_app_server import (
    CodexAppServerError,
    CodexAppServerTimeout,
    CodexAppServerUnavailable,
    codex_app_servers,
)


bp = Blueprint("routes_attribute_assistant", __name__)


def uploaded_csv():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        raise ValueError("Выберите CSV-файл")
    if Path(uploaded.filename).suffix.lower() != ".csv":
        raise ValueError("Можно загрузить только CSV-файл")
    content = uploaded.read()
    if not content:
        raise ValueError("Загруженный CSV-файл пуст")
    return uploaded, content


def compact_product_payload(db, product):
    fields_with_values = allowed_value_field_ids(
        db,
        (item.template_field_id for item in product.values or []),
    )
    return public_product(product, allowed_fields=fields_with_values)


def error_response(error: Exception, status: int = 400):
    return jsonify({"error": str(error)}), status


def current_codex_client():
    return codex_app_servers.client(session.get("user_id"))


def codex_error_response(error: Exception):
    if isinstance(error, CodexAppServerUnavailable):
        return error_response(error, 503)
    if isinstance(error, CodexAppServerTimeout):
        return error_response(error, 504)
    return error_response(error, 502)


@bp.get("/api/attribute-assistant")
def api_attribute_assistant_workspace():
    ensure_storage()
    return jsonify(workspace_payload(g.db))


@bp.get("/api/attribute-assistant/chatgpt/status")
def api_attribute_chatgpt_status():
    ensure_storage()
    try:
        return jsonify(current_codex_client().account_status())
    except (ValueError, CodexAppServerError) as error:
        return jsonify(
            {
                "available": False,
                "authenticated": False,
                "auth_mode": "",
                "email": "",
                "plan_type": "",
                "pending": False,
                "verification_url": "",
                "user_code": "",
                "error": str(error),
            }
        )


@bp.post("/api/attribute-assistant/chatgpt/login/device")
def api_attribute_chatgpt_device_login():
    ensure_storage()
    try:
        return jsonify(current_codex_client().start_device_login())
    except (ValueError, CodexAppServerError) as error:
        return codex_error_response(error)


@bp.post("/api/attribute-assistant/chatgpt/logout")
def api_attribute_chatgpt_logout():
    ensure_storage()
    try:
        return jsonify(current_codex_client().logout())
    except (ValueError, CodexAppServerError) as error:
        return codex_error_response(error)


@bp.post("/api/attribute-assistant/chatgpt/analyze-url")
def api_analyze_attribute_url_with_chatgpt():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    template = None
    if payload.get("template_id") not in (None, "", 0, "0"):
        template = load_template(g.db, payload.get("template_id"))
        if template is None:
            return jsonify({"error": "Шаблон не найден"}), 404
    try:
        source_url = _validate_http_url(payload.get("url"))
        prepared = build_attribute_url_analysis_prompt(
            g.db,
            source_url=source_url,
            template=template,
        )
        validation_context = dict(prepared["validation_context"])
        template_id = template.id if template is not None else None
        g.db.commit()
        codex_client = current_codex_client()
        raw_analysis = codex_client.run_json(
            str(prepared["prompt"]),
            ATTRIBUTE_ANALYSIS_OUTPUT_SCHEMA,
            allow_web=True,
        )
        if attribute_analysis_needs_web_fallback(raw_analysis):
            prepared = build_attribute_url_analysis_prompt(
                g.db,
                source_url=source_url,
                template=template,
                same_domain_fallback=True,
            )
            validation_context = dict(prepared["validation_context"])
            raw_analysis = codex_client.run_json(
                str(prepared["prompt"]),
                ATTRIBUTE_ANALYSIS_OUTPUT_SCHEMA,
                allow_web=True,
            )
        g.db.expire_all()
        current_template = load_template(g.db, template_id) if template_id is not None else None
        if template_id is not None and current_template is None:
            return jsonify({"error": "Шаблон был удалён во время анализа"}), 404
        analysis = validate_attribute_analysis(
            g.db,
            response=raw_analysis,
            page_evidence=str(validation_context.get("page_evidence") or ""),
            template=current_template,
        )
    except ValueError as error:
        return error_response(error)
    except CodexAppServerError as error:
        return codex_error_response(error)
    return jsonify({"analysis": analysis})


@bp.post("/api/attribute-assistant/templates")
def api_create_attribute_template():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    try:
        template = create_empty_template(
            g.db,
            category_name=str(payload.get("category_name") or ""),
            category_path=str(payload.get("category_path") or ""),
            template_name=str(payload.get("template_name") or ""),
            product_type=str(payload.get("product_type") or ""),
            is_default=bool(payload.get("is_default")),
        )
    except ValueError as error:
        return error_response(error)
    return jsonify({"template": public_template(template), "workspace": workspace_payload(g.db)})


@bp.get("/api/attribute-assistant/templates/<int:template_id>")
def api_attribute_template(template_id: int):
    ensure_storage()
    template = load_template(g.db, template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    return jsonify(
        {
            "template": public_template(template),
            "revisions": list_template_revisions(g.db, template.id),
        }
    )


@bp.post("/api/attribute-assistant/templates/preview")
def api_preview_attribute_template():
    ensure_storage()
    try:
        _uploaded, content = uploaded_csv()
        report = preview_template_csv(
            g.db,
            content,
            category_name=str(request.form.get("category_name") or ""),
            category_path=str(request.form.get("category_path") or ""),
            template_name=str(request.form.get("template_name") or ""),
        )
    except ValueError as error:
        return error_response(error)
    return jsonify({"report": report})


@bp.post("/api/attribute-assistant/templates/import")
def api_import_attribute_template():
    ensure_storage()
    try:
        _uploaded, content = uploaded_csv()
        mode = str(request.form.get("mode") or "merge")
        template, report = import_template_csv(
            g.db,
            content,
            category_name=str(request.form.get("category_name") or ""),
            category_path=str(request.form.get("category_path") or ""),
            template_name=str(request.form.get("template_name") or ""),
            mode=mode,
            load_result=False,
            product_type=str(request.form.get("product_type") or ""),
            is_default=str(request.form.get("is_default") or "").lower() in {"1", "true", "yes", "on"},
            external_key=str(request.form.get("external_key") or ""),
        )
    except ValueError as error:
        return error_response(error)
    workspace = workspace_payload(g.db)
    template_payload = next(
        (item for item in workspace["templates"] if item["id"] == template.id),
        {"id": template.id},
    )
    return jsonify({"template": template_payload, "report": report, "workspace": workspace})


@bp.post("/api/attribute-assistant/templates/<int:template_id>/copy")
def api_copy_attribute_template(template_id: int):
    ensure_storage()
    template = load_template(g.db, template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        copied = copy_template(g.db, template, str(payload.get("name") or ""))
    except ValueError as error:
        return error_response(error)
    return jsonify({"template": public_template(copied), "workspace": workspace_payload(g.db)})


@bp.post("/api/attribute-assistant/templates/<int:template_id>/restore/<int:revision_id>")
def api_restore_attribute_template(template_id: int, revision_id: int):
    ensure_storage()
    template = load_template(g.db, template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    try:
        restored = restore_template_revision(g.db, template, revision_id)
    except LookupError as error:
        return error_response(error, 404)
    except ValueError as error:
        return error_response(error)
    return jsonify(
        {
            "template": public_template(restored),
            "revisions": list_template_revisions(g.db, restored.id),
            "workspace": workspace_payload(g.db),
        }
    )


@bp.get("/api/attribute-assistant/templates/<int:template_id>/export")
def api_export_attribute_template(template_id: int):
    ensure_storage()
    template = load_template(g.db, template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    content = export_template_csv(template)
    filename = f"{safe_filename(template.name)}.csv"
    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@bp.delete("/api/attribute-assistant/templates/<int:template_id>")
def api_delete_attribute_template(template_id: int):
    ensure_storage()
    template = load_template(g.db, template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    g.db.delete(template)
    g.db.flush()
    return jsonify({"ok": True, "workspace": workspace_payload(g.db)})


@bp.patch("/api/attribute-assistant/fields/<int:field_id>")
def api_update_attribute_field(field_id: int):
    ensure_storage()
    field = g.db.get(AttributeTemplateField, field_id)
    if field is None:
        return jsonify({"error": "Атрибут шаблона не найден"}), 404
    try:
        update_template_field(g.db, field, request.get_json(silent=True) or {})
    except (TypeError, ValueError) as error:
        return error_response(error)
    template = load_template(g.db, field.template_id)
    return jsonify({"template": public_template(template)})


@bp.post("/api/attribute-assistant/templates/<int:template_id>/fields")
def api_create_attribute_field(template_id: int):
    ensure_storage()
    template = load_template(g.db, template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    try:
        create_template_field(g.db, template, request.get_json(silent=True) or {})
    except ValueError as error:
        return error_response(error)
    template = load_template(g.db, template_id) or template
    return jsonify({"template": public_template(template)})


@bp.post("/api/attribute-assistant/templates/<int:template_id>/fields/reorder")
def api_reorder_attribute_fields(template_id: int):
    ensure_storage()
    template = load_template(g.db, template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        reordered = reorder_template_fields(g.db, template, payload.get("field_ids") or [])
    except ValueError as error:
        return error_response(error)
    return jsonify({"template": public_template(reordered)})


@bp.delete("/api/attribute-assistant/fields/<int:field_id>")
def api_delete_attribute_field(field_id: int):
    ensure_storage()
    field = g.db.get(AttributeTemplateField, field_id)
    if field is None:
        return jsonify({"error": "Атрибут шаблона не найден"}), 404
    template = load_template(g.db, field.template_id)
    if template is None:
        return jsonify({"error": "Шаблон не найден"}), 404
    delete_template_field(g.db, template, field)
    template = load_template(g.db, template.id) or template
    return jsonify({"template": public_template(template)})


@bp.get("/api/attribute-assistant/fields/<int:field_id>/allowed-values")
def api_attribute_field_allowed_values(field_id: int):
    ensure_storage()
    payload = field_allowed_values(g.db, field_id)
    if payload is None:
        return jsonify({"error": "Атрибут шаблона не найден"}), 404
    return jsonify(payload)


@bp.post("/api/attribute-assistant/fields/<int:field_id>/allowed-values")
def api_add_attribute_allowed_value(field_id: int):
    ensure_storage()
    field = g.db.get(AttributeTemplateField, field_id)
    if field is None:
        return jsonify({"error": "Атрибут шаблона не найден"}), 404
    try:
        value = create_allowed_value(g.db, field, request.get_json(silent=True) or {})
    except ValueError as error:
        return error_response(error)
    values = field_allowed_values(g.db, field.id)["allowed_values"]
    return jsonify({"value": next((item for item in values if item["id"] == value.id), {})})


@bp.patch("/api/attribute-assistant/allowed-values/<int:value_id>")
def api_update_attribute_allowed_value(value_id: int):
    ensure_storage()
    value = g.db.get(AttributeAllowedValue, value_id)
    if value is None:
        return jsonify({"error": "Разрешённое значение не найдено"}), 404
    update_allowed_value_settings(g.db, value, request.get_json(silent=True) or {})
    return jsonify({"ok": True})


@bp.post("/api/attribute-assistant/allowed-values/<int:value_id>/synonyms")
def api_add_attribute_value_synonym(value_id: int):
    ensure_storage()
    value = g.db.get(AttributeAllowedValue, value_id)
    if value is None:
        return jsonify({"error": "Разрешённое значение не найдено"}), 404
    try:
        synonym = add_value_synonym(
            g.db,
            value,
            (request.get_json(silent=True) or {}).get("synonym"),
            record_revision=True,
        )
    except ValueError as error:
        return error_response(error)
    return jsonify({"synonym": {"id": synonym.id, "synonym": synonym.synonym}})


@bp.delete("/api/attribute-assistant/synonyms/<int:synonym_id>")
def api_delete_attribute_value_synonym(synonym_id: int):
    ensure_storage()
    synonym = g.db.get(AttributeValueSynonym, synonym_id)
    if synonym is None:
        return jsonify({"error": "Синоним не найден"}), 404
    delete_value_synonym(g.db, synonym)
    return jsonify({"ok": True})


@bp.post("/api/attribute-assistant/batches/import")
def api_import_attribute_products():
    ensure_storage()
    try:
        uploaded, content = uploaded_csv()
        template = load_template(g.db, request.form.get("template_id"))
        if template is None:
            raise ValueError("Выберите существующий шаблон категории")
        stored_name = f"{uuid.uuid4().hex[:12]}_{safe_filename(Path(uploaded.filename).stem or 'products')}.csv"
        stored_path = assistant_subdir("batches") / stored_name
        stored_path.write_bytes(content)
        try:
            batch = import_products_csv(
                g.db,
                template,
                content,
                source_filename=Path(uploaded.filename).name,
                stored_filename=stored_name,
                processing_mode=str(request.form.get("processing_mode") or "suggest"),
            )
        except Exception:
            stored_path.unlink(missing_ok=True)
            raise
    except ValueError as error:
        return error_response(error)
    batch = load_batch(g.db, batch.id, include_products=True) or batch
    return jsonify({"batch": public_batch(batch), "workspace": workspace_payload(g.db)})


@bp.post("/api/attribute-assistant/batches/import-urls")
def api_import_attribute_product_urls():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    template_id = payload.get("template_id")
    template = load_template(g.db, template_id) if template_id not in (None, "", 0, "0") else None
    urls = payload.get("urls")
    if isinstance(urls, str):
        urls = urls.splitlines()
    try:
        batch = import_products_from_urls(
            g.db,
            template,
            urls if isinstance(urls, list) else [],
            processing_mode=str(payload.get("processing_mode") or "suggest"),
        )
    except ValueError as error:
        return error_response(error)
    batch = load_batch(g.db, batch.id, include_products=True) or batch
    return jsonify({"batch": public_batch(batch), "workspace": workspace_payload(g.db)})


@bp.get("/api/attribute-assistant/batches/<int:batch_id>")
def api_attribute_batch(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id, include_products=True)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    return jsonify({"batch": public_batch(batch), "report": batch_report(g.db, batch)})


@bp.delete("/api/attribute-assistant/batches/<int:batch_id>")
def api_delete_attribute_batch(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id, include_products=True)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    delete_batch_files(batch)
    g.db.delete(batch)
    g.db.flush()
    return jsonify({"ok": True, "workspace": workspace_payload(g.db)})


@bp.post("/api/attribute-assistant/batches/<int:batch_id>/bulk")
def api_bulk_update_attribute_batch(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    payload = request.get_json(silent=True) or {}
    result = bulk_update_values(
        g.db,
        batch,
        action=str(payload.get("action") or ""),
        value_ids=payload.get("value_ids") if isinstance(payload.get("value_ids"), list) else None,
        threshold=int(payload.get("threshold") or 95),
    )
    return jsonify({"result": result, "batch": batch_summary(batch)})


@bp.get("/api/attribute-assistant/products/<int:product_id>")
def api_attribute_product(product_id: int):
    ensure_storage()
    product = load_product(g.db, product_id, include_allowed_values=False)
    if product is None:
        return jsonify({"error": "Товар не найден"}), 404
    return jsonify({"product": compact_product_payload(g.db, product)})


@bp.patch("/api/attribute-assistant/products/<int:product_id>/values/<int:value_id>")
def api_update_attribute_product_value(product_id: int, value_id: int):
    ensure_storage()
    product = load_product(g.db, product_id)
    if product is None:
        return jsonify({"error": "Товар не найден"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        update_product_value(g.db, product, value_id, payload.get("final_value"))
    except LookupError as error:
        return error_response(error, 404)
    except ValueError as error:
        return error_response(error)
    product = load_product(g.db, product_id, include_allowed_values=False) or product
    batch = load_batch(g.db, product.batch_id) or product.batch
    return jsonify({"product": compact_product_payload(g.db, product), "batch": batch_summary(batch)})


@bp.get("/api/attribute-assistant/products/<int:product_id>/history")
def api_attribute_product_history(product_id: int):
    ensure_storage()
    if load_product(g.db, product_id, include_allowed_values=False) is None:
        return jsonify({"error": "Товар не найден"}), 404
    return jsonify({"logs": product_logs(g.db, product_id)})


@bp.post("/api/attribute-assistant/products/<int:product_id>/rollback/<int:log_id>")
def api_rollback_attribute_product_value(product_id: int, log_id: int):
    ensure_storage()
    product = load_product(g.db, product_id)
    if product is None:
        return jsonify({"error": "Товар не найден"}), 404
    try:
        rollback_value_change(g.db, product, log_id)
    except LookupError as error:
        return error_response(error, 404)
    except ValueError as error:
        return error_response(error)
    product = load_product(g.db, product_id, include_allowed_values=False) or product
    return jsonify({"product": compact_product_payload(g.db, product)})


@bp.post("/api/attribute-assistant/products/<int:product_id>/donors/parse")
def api_parse_attribute_product_donor(product_id: int):
    ensure_storage()
    product = load_product(g.db, product_id)
    if product is None:
        return jsonify({"error": "Товар не найден"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        source = parse_donor_for_product(
            g.db,
            product,
            url=str(payload.get("url") or ""),
            donor_id=payload.get("donor_id"),
            priority=int(payload.get("priority") or 0),
        )
    except (ValueError, requests.RequestException) as error:
        return error_response(error)
    product = load_product(g.db, product_id, include_allowed_values=False) or product
    return jsonify({"source_id": source.id, "product": compact_product_payload(g.db, product)})


@bp.post("/api/attribute-assistant/products/<int:product_id>/chatgpt/analyze")
def api_analyze_attribute_product_with_chatgpt(product_id: int):
    ensure_storage()
    product = load_product(g.db, product_id)
    if product is None:
        return jsonify({"error": "Товар не найден"}), 404
    template = load_template(g.db, product.batch.template_id)
    if template is None:
        return jsonify({"error": "Шаблон обработки удалён"}), 404
    payload = request.get_json(silent=True) or {}
    source_url = str(payload.get("url") or product.source_url or "").strip()
    if not source_url and product.donor_sources:
        source_url = str(product.donor_sources[0].url or "").strip()
    if not source_url:
        return error_response(ValueError("Укажите ссылку на страницу товара"))
    try:
        source_url = _validate_http_url(source_url)
        current_values = {
            int(item.template_field_id): item.current_value
            for item in product.values or []
            if item.template_field_id is not None
        }
        prepared = build_attribute_url_analysis_prompt(
            g.db,
            source_url=source_url,
            template=template,
            current_values=current_values,
        )
        validation_context = dict(prepared["validation_context"])
        template_id = template.id
        g.db.commit()
        codex_client = current_codex_client()
        raw_analysis = codex_client.run_json(
            str(prepared["prompt"]),
            ATTRIBUTE_ANALYSIS_OUTPUT_SCHEMA,
            allow_web=True,
        )
        if attribute_analysis_needs_web_fallback(raw_analysis):
            prepared = build_attribute_url_analysis_prompt(
                g.db,
                source_url=source_url,
                template=template,
                current_values=current_values,
                same_domain_fallback=True,
            )
            validation_context = dict(prepared["validation_context"])
            raw_analysis = codex_client.run_json(
                str(prepared["prompt"]),
                ATTRIBUTE_ANALYSIS_OUTPUT_SCHEMA,
                allow_web=True,
            )
        g.db.expire_all()
        product = load_product(g.db, product_id)
        if product is None:
            return jsonify({"error": "Товар был удалён во время анализа"}), 404
        template = load_template(g.db, product.batch.template_id)
        if template is None or template.id != template_id:
            return jsonify({"error": "Шаблон товара изменился во время анализа. Запустите анализ заново"}), 409
        current_values = {
            int(item.template_field_id): item.current_value
            for item in product.values or []
            if item.template_field_id is not None
        }
        analysis = validate_attribute_analysis(
            g.db,
            response=raw_analysis,
            page_evidence=str(validation_context.get("page_evidence") or ""),
            template=template,
            current_values=current_values,
        )
        changed = apply_attribute_suggestions(
            g.db,
            product,
            analysis,
            source_url=source_url,
        )
    except (TypeError, ValueError) as error:
        return error_response(error)
    except CodexAppServerError as error:
        return codex_error_response(error)
    product = load_product(g.db, product_id, include_allowed_values=False) or product
    batch = load_batch(g.db, product.batch_id) or product.batch
    return jsonify(
        {
            "analysis": analysis,
            "changed": changed,
            "product": compact_product_payload(g.db, product),
            "batch": batch_summary(batch),
        }
    )


@bp.get("/api/attribute-assistant/donors")
def api_attribute_donors():
    ensure_storage()
    return jsonify({"donors": list_attribute_donors(g.db)})


@bp.post("/api/attribute-assistant/donors")
def api_create_attribute_donor():
    ensure_storage()
    try:
        donor = save_attribute_donor(g.db, request.get_json(silent=True) or {})
    except ValueError as error:
        return error_response(error)
    return jsonify({"donor": public_donor(donor), "workspace": workspace_payload(g.db)})


@bp.patch("/api/attribute-assistant/donors/<int:donor_id>")
def api_update_attribute_donor(donor_id: int):
    ensure_storage()
    if g.db.get(AttributeDonor, donor_id) is None:
        return jsonify({"error": "Донор не найден"}), 404
    try:
        donor = save_attribute_donor(g.db, request.get_json(silent=True) or {}, donor_id)
    except ValueError as error:
        return error_response(error)
    return jsonify({"donor": public_donor(donor)})


@bp.delete("/api/attribute-assistant/donors/<int:donor_id>")
def api_delete_attribute_donor(donor_id: int):
    ensure_storage()
    donor = g.db.get(AttributeDonor, donor_id)
    if donor is None:
        return jsonify({"error": "Донор не найден"}), 404
    g.db.delete(donor)
    g.db.flush()
    return jsonify({"ok": True, "workspace": workspace_payload(g.db)})


@bp.post("/api/attribute-assistant/donors/test")
def api_test_attribute_donor():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    try:
        _final_url, _html, parsed = load_product_page(
            payload.get("url"),
            payload.get("selectors") or {},
        )
    except (ValueError, requests.RequestException) as error:
        return error_response(error)
    return jsonify({"parsed": parsed})


@bp.post("/api/attribute-assistant/mapping-rules")
def api_save_attribute_mapping_rule():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    try:
        donor = g.db.get(AttributeDonor, int(payload.get("donor_id") or 0))
        template = load_template(g.db, payload.get("template_id"))
        field = g.db.get(AttributeTemplateField, int(payload.get("template_field_id") or 0))
    except (TypeError, ValueError):
        return error_response(ValueError("Некорректный донор, шаблон или атрибут"))
    if donor is None or template is None or field is None or field.template_id != template.id:
        return error_response(ValueError("Некорректный донор, шаблон или атрибут"))
    try:
        rule = save_mapping_rule(
            g.db,
            donor=donor,
            template=template,
            donor_attribute_name=str(payload.get("donor_attribute_name") or ""),
            field=field,
        )
    except ValueError as error:
        return error_response(error)
    return jsonify({"rule_id": rule.id})


@bp.get("/api/attribute-assistant/batches/<int:batch_id>/report")
def api_attribute_batch_report(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    return jsonify(batch_report(g.db, batch))


@bp.post("/api/attribute-assistant/batches/<int:batch_id>/report")
def api_export_attribute_batch_report(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    path = export_batch_report_csv(g.db, batch)
    return jsonify({
        "filename": path.name,
        "download_url": f"/api/attribute-assistant/batches/{batch.id}/report/download",
    })


@bp.get("/api/attribute-assistant/batches/<int:batch_id>/report/download")
def api_download_attribute_batch_report(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    path = resolve_batch_report(batch)
    if path is None:
        return jsonify({"error": "Сначала сформируйте отчёт"}), 404
    return send_file(
        path,
        mimetype="text/csv; charset=windows-1251",
        as_attachment=True,
        download_name=path.name,
    )


@bp.post("/api/attribute-assistant/batches/<int:batch_id>/export")
def api_export_attribute_batch(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    payload = request.get_json(silent=True) or {}
    try:
        path = export_batch_csv(g.db, batch, only_ready=bool(payload.get("only_ready")))
    except ValueError as error:
        return error_response(error)
    return jsonify({
        "batch": batch_summary(batch),
        "filename": path.name,
        "download_url": f"/api/attribute-assistant/batches/{batch.id}/download",
    })


@bp.get("/api/attribute-assistant/batches/<int:batch_id>/download")
def api_download_attribute_batch(batch_id: int):
    ensure_storage()
    batch = load_batch(g.db, batch_id)
    if batch is None:
        return jsonify({"error": "Обработка не найдена"}), 404
    path = resolve_batch_export(batch)
    if path is None:
        return jsonify({"error": "Сначала сформируйте итоговый CSV"}), 404
    return send_file(
        path,
        mimetype="text/csv; charset=windows-1251",
        as_attachment=True,
        download_name=path.name,
    )
