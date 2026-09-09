"""Read-only OpenCart transport and transactional category-template synchronization."""
import hashlib
import ipaddress
import json
import re
import socket
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import urllib3
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from models import (
    AttributeAllowedValue, AttributeCategory, AttributeShopConnection,
    AttributeShopTemplateLink, AttributeTemplate, AttributeTemplateField, utc_now,
)
from services.attribute_assistant import (
    clean_text, normalize_key, dictionary_value_key, exact_value_key,
    set_field_value_type, save_template_revision,
)

MAX_BYTES = 20 * 1024 * 1024
LEASE = timedelta(minutes=10)
ROUTE = "extension/module/attribute_bridge"


def endpoint_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        raise ValueError("Укажите полный HTTPS URL API из настроек модуля.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError):
        raise ValueError("Некорректный URL API.") from None
    if (parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or parsed.fragment
            or not re.fullmatch(r"[a-z0-9.:-]+", host)):
        raise ValueError("Нужен HTTPS URL API без логина, пароля и фрагмента.")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if query != [("route", ROUTE)]:
        raise ValueError("Скопируйте URL API из настроек модуля Attribute Bridge.")
    if not parsed.path.endswith("/index.php"):
        raise ValueError("URL API должен указывать на index.php магазина.")
    authority = "[" + host + "]" if ":" in host else host
    if port and port != 443:
        authority += ":" + str(port)
    return urlunsplit(("https", authority, parsed.path, urlencode({"route": ROUTE}), ""))


def serialize_shop(shop: AttributeShopConnection) -> dict:
    return {
        "id": shop.id, "name": shop.name, "endpoint": shop.endpoint,
        "language_code": shop.language_code, "enabled": shop.enabled,
        "has_api_key": bool(shop.api_key),
        "last_sync_at": shop.last_sync_at.isoformat() + "Z" if shop.last_sync_at else "",
        "last_error": shop.last_error, "last_report": shop.last_report,
        "syncing": bool(shop.sync_token and shop.sync_started_at
                        and shop.sync_started_at > utc_now() - LEASE),
    }


def configure_shop(db: Session, data: dict, shop: AttributeShopConnection | None = None):
    if not isinstance(data, dict):
        raise ValueError("Настройки должны быть объектом.")
    name = clean_text(data.get("name", ""))
    endpoint = endpoint_url(data.get("endpoint", ""))
    language = data.get("language_code", "ru-ru")
    key = data.get("api_key", "")
    enabled = data.get("enabled", True)
    if not name or len(name) > 160:
        raise ValueError("Укажите название магазина длиной до 160 символов.")
    if not isinstance(language, str) or not re.fullmatch(r"[a-zA-Z0-9-]{2,12}", language):
        raise ValueError("Некорректный код языка.")
    if not isinstance(enabled, bool):
        raise ValueError("Статус подключения должен быть логическим значением.")
    if not isinstance(key, str) or (key and not re.fullmatch(r"[a-f0-9]{64}", key)):
        raise ValueError("Ключ должен содержать 64 символа, выданных модулем магазина.")
    if shop and serialize_shop(shop)["syncing"]:
        raise ValueError("Дождитесь окончания синхронизации.")
    if shop is None:
        if not key:
            raise ValueError("Укажите ключ API магазина.")
        shop = AttributeShopConnection(api_key=key)
        db.add(shop)
    shop.name, shop.endpoint, shop.language_code, shop.enabled = name, endpoint, language, enabled
    if key:
        shop.api_key = key
    return shop


def fetch_snapshot(shop: AttributeShopConnection) -> dict:
    """Pin a validated public address; never follow redirects with credentials."""
    endpoint = endpoint_url(shop.endpoint)
    parsed = urlsplit(endpoint)
    host, port = parsed.hostname, parsed.port or 443
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )})
        if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
            raise ValueError("API магазина должен быть доступен по публичному интернет-адресу.")
    except (socket.gaierror, OSError):
        raise ValueError("Не удалось определить адрес магазина.") from None
    target = parsed.path + "?" + urlencode({"route": ROUTE, "language": shop.language_code})
    pool = urllib3.HTTPSConnectionPool(
        addresses[0], port=port, server_hostname=host, assert_hostname=host,
        cert_reqs="CERT_REQUIRED", ca_certs=requests.certs.where(),
        timeout=urllib3.Timeout(connect=10, read=45), maxsize=1,
    )
    response = None
    started = time.monotonic()
    try:
        response = pool.urlopen(
            "GET", target, redirect=False, retries=False, preload_content=False,
            headers={"Host": parsed.netloc, "X-Attribute-Bridge-Key": shop.api_key,
                     "User-Agent": "AttributeBridge/1.0",
                     "Accept": "application/json", "Accept-Encoding": "identity"},
        )
        if response.status == 401:
            raise ValueError("Магазин отклонил ключ. Проверьте ключ и включение модуля.")
        if response.status != 200:
            raise ValueError("API магазина вернул HTTP " + str(response.status) + ".")
        chunks, length = [], 0
        for chunk in response.stream(65536, decode_content=False):
            length += len(chunk)
            if length > MAX_BYTES or time.monotonic() - started > 120:
                raise ValueError("Ответ магазина превышает предел размера или времени.")
            chunks.append(chunk)
        try:
            result = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeError, ValueError):
            raise ValueError("Магазин вернул некорректный JSON. Проверьте URL API.") from None
        return result
    except urllib3.exceptions.HTTPError:
        raise ValueError("Не удалось получить данные магазина по HTTPS.") from None
    finally:
        if response:
            response.close()
        pool.close()


def validate_snapshot(data: dict, language_code: str) -> tuple[dict, dict]:
    def integer(value, zero=False):
        if type(value) is not int or value < (0 if zero else 1):
            raise ValueError("API вернул некорректный идентификатор.")
        return value

    def string(value, limit, empty=False):
        if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
            raise ValueError("API вернул пустую или слишком длинную строку.")
        if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise ValueError("API вернул управляющие символы в строке.")
        return value

    if not isinstance(data, dict) or data.get("schema") != "attributico-category-snapshot" or data.get("version") != 1:
        raise ValueError("Неподдерживаемый формат API магазина.")
    if not re.fullmatch(r"[a-f0-9]{32}", str(data.get("source_id", ""))):
        raise ValueError("API не передал идентификатор установки.")
    language = data.get("language")
    if not isinstance(language, dict) or language.get("code") != language_code:
        raise ValueError("Язык ответа магазина не совпадает с настройками.")
    integer(language.get("id"))
    if data.get("values_origin") != "product_attribute" or data.get("values_scope") != "database_attributes_linked_to_categories":
        raise ValueError("API использует неподдерживаемый источник значений.")
    categories, attributes = {}, {}
    total_values, total_links = 0, 0
    for key in ("categories", "attributes"):
        if not isinstance(data.get(key), list) or len(data[key]) > 10000:
            raise ValueError("Некорректный или слишком большой список " + key + ".")
    for item in data["attributes"]:
        if not isinstance(item, dict):
            raise ValueError("Некорректный атрибут.")
        aid = integer(item.get("id"))
        if aid in attributes:
            raise ValueError("Повторяющийся ID атрибута.")
        string(item.get("name"), 500)
        string(item.get("group_name"), 255)
        integer(item.get("group_id"))
        for key in ("sort_order", "group_sort_order"):
            if type(item.get(key)) is not int:
                raise ValueError("Некорректный порядок сортировки.")
        string(item.get("duty_raw", ""), 100000, empty=True)
        if not isinstance(item.get("values"), list):
            raise ValueError("Отсутствует список значений атрибута.")
        for value in item["values"]:
            string(value, 1000, empty=True)
        if len(set(item["values"])) != len(item["values"]):
            raise ValueError("API вернул повторяющиеся значения.")
        total_values += len(item["values"])
        attributes[aid] = item
    for item in data["categories"]:
        if not isinstance(item, dict):
            raise ValueError("Некорректная категория.")
        cid = integer(item.get("id"))
        if cid in categories:
            raise ValueError("Повторяющийся ID категории.")
        integer(item.get("parent_id"), zero=True)
        string(item.get("name"), 255)
        if type(item.get("enabled")) is not bool or type(item.get("sort_order")) is not int:
            raise ValueError("Некорректный статус или порядок категории.")
        ids = item.get("attribute_ids")
        if not isinstance(ids, list):
            raise ValueError("Отсутствует список атрибутов категории.")
        for aid in ids:
            integer(aid)
            if aid not in attributes:
                raise ValueError("Категория ссылается на отсутствующий атрибут.")
        if len(set(ids)) != len(ids):
            raise ValueError("Повторяющаяся связь категории с атрибутом.")
        total_links += len(ids)
        categories[cid] = item
    if total_values > 100000 or total_links > 100000:
        raise ValueError("Превышен размер снимка магазина.")
    for category in categories.values():
        seen, current = set(), category
        while current["parent_id"]:
            if current["id"] in seen or current["parent_id"] not in categories:
                raise ValueError("Неполное или циклическое дерево категорий.")
            seen.add(current["id"])
            current = categories[current["parent_id"]]
    counts = {"categories": len(categories), "attributes": len(attributes),
              "links": total_links, "values": total_values}
    if data.get("counts") != counts:
        raise ValueError("Контрольные количества API не совпадают с данными.")
    return categories, attributes


def _path(categories: dict, category: dict) -> str:
    parts, current = [clean_text(category["name"])], category
    while current["parent_id"]:
        current = categories[current["parent_id"]]
        parts.append(clean_text(current["name"]))
    return " > ".join(reversed(parts))


def import_snapshot(db: Session, shop: AttributeShopConnection, data: dict) -> dict:
    categories, attributes = validate_snapshot(data, shop.language_code)
    if shop.remote_source_id and shop.remote_source_id != data["source_id"]:
        raise ValueError("URL отвечает от другой установки магазина. Создайте отдельное подключение.")
    report = dict(created=0, updated=0, unchanged=0, fields_added=0, values_added=0,
                  categories_missing=0, fields_missing=0, values_missing=0,
                  local_changes_preserved=0, normalized_duplicates=0)
    links = {link.remote_category_id: link for link in db.scalars(
        select(AttributeShopTemplateLink).where(
            AttributeShopTemplateLink.connection_id == shop.id,
            AttributeShopTemplateLink.language_code == shop.language_code,
        )
    )}
    present = set()
    for cid, category in sorted(categories.items()):
        if not category["attribute_ids"]:
            continue
        present.add(cid)
        ordered = sorted((attributes[aid] for aid in category["attribute_ids"]),
                         key=lambda a: (a["group_sort_order"], a["group_id"], a["sort_order"], a["id"]))
        source = {"category": category, "path": _path(categories, category),
                  "attributes": [{**a, "values": sorted(a["values"])} for a in ordered],
                  "connection_name": shop.name}
        digest = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        link = links.get(cid)
        template = db.get(AttributeTemplate, link.template_id) if link and link.template_id else None
        if template is not None and link.source_hash == digest and link.state.get("dictionary_version") == 3:
            report["unchanged"] += 1
            continue
        previous = link.state if link and template is not None else {}
        old_attrs = {a["id"]: a for a in previous.get("source", {}).get("attributes", [])}
        field_ids = dict(previous.get("field_ids", {}))
        old_applied = previous.get("applied", {})
        applied = {}
        path = shop.name + " (" + shop.language_code + ") > " + source["path"] + " [#" + str(cid) + "]"
        if len(path) > 1000:
            raise ValueError("Путь категории превышает 1000 символов.")
        is_new = template is None
        if is_new:
            local_category = db.scalar(select(AttributeCategory).where(AttributeCategory.full_path == path))
            if local_category is None:
                local_category = AttributeCategory(name=clean_text(category["name"]), full_path=path)
                db.add(local_category)
            template = AttributeTemplate(
                category=local_category, name=clean_text(category["name"]),
                is_active=category["enabled"], is_default=not bool(local_category.templates),
            )
            db.add(template)
            db.flush()
            report["created"] += 1
        else:
            save_template_revision(db, template, "before_opencart_sync", {"connection_id": shop.id})
            for key, desired in (("name", clean_text(category["name"])), ("is_active", category["enabled"])):
                old = previous.get("template", {}).get(key, getattr(template, key))
                if getattr(template, key) == old:
                    setattr(template, key, desired)
                elif getattr(template, key) != desired:
                    report["local_changes_preserved"] += 1
            if template.category.full_path == previous.get("category_path"):
                template.category.full_path = path
                template.category.name = clean_text(category["name"])
            template.version += 1
            report["updated"] += 1
        current_fields = {field.id: field for field in template.fields}
        for order, source_field in enumerate(ordered):
            remote_id = str(source_field["id"])
            field = current_fields.get(field_ids.get(remote_id))
            if field is None and remote_id in field_ids:
                report["local_changes_preserved"] += 1  # Keep a field the user deliberately removed absent.
                continue
            desired = {"name": clean_text(source_field["name"]), "group_name": clean_text(source_field["group_name"]),
                       "sort_order": order}
            if field is None:
                occupied = {(f.group_name, f.name) for f in template.fields}
                if (desired["group_name"], desired["name"]) in occupied:
                    desired["name"] += " [#" + remote_id + "]"
                field = AttributeTemplateField(template=template, **desired, value_type="select", is_composite=False)
                db.add(field)
                db.flush()
                field_ids[remote_id] = field.id
                report["fields_added"] += 1
            else:
                old = old_applied.get(remote_id, desired)
                candidate = {key: desired[key] if getattr(field, key) == old.get(key)
                             else getattr(field, key) for key in desired}
                collision = any(f.id != field.id and (f.group_name, f.name) ==
                                (candidate["group_name"], candidate["name"]) for f in template.fields)
                if collision:
                    candidate["group_name"], candidate["name"] = field.group_name, field.name
                    report["local_changes_preserved"] += 1
                for key in desired:
                    if candidate[key] != desired[key]:
                        report["local_changes_preserved"] += 1
                    setattr(field, key, candidate[key])
            # Upgrade earlier imports and recover only variants lost to their lossy keys.
            old_raw = old_attrs.get(source_field["id"], {}).get("values", [])
            recover_keys = set()
            if previous and previous.get("dictionary_version") != 3 and field.value_type in {"select", "select_exact"}:
                old_exact_keys = {exact_value_key(raw) for raw in old_raw}
                legacy_key = (
                    (lambda value: clean_text(value).casefold().replace("ё", "е"))
                    if previous.get("dictionary_version") == 2 else normalize_key
                )
                retained = {
                    legacy_key(v.value) for v in field.allowed_values
                    if v.source == "opencart:" + str(shop.id)
                    and exact_value_key(v.value) in old_exact_keys
                }
                recover_keys = {exact_value_key(raw) for raw in old_raw if legacy_key(raw) in retained}
                set_field_value_type(db, field, "select")
                field.is_composite = False
            # Save the last source-owned targets, not the user's overrides.
            applied[remote_id] = desired
            allowed = {v.normalized_value: v for v in field.allowed_values}
            old_values = {dictionary_value_key(v, field.value_type) for v in old_raw}
            new_values = set()
            for raw in source_field["values"]:
                value, key = exact_value_key(raw), dictionary_value_key(raw, field.value_type)
                if not key:
                    continue
                if key in new_values:
                    report["normalized_duplicates"] += 1
                    continue
                new_values.add(key)
                if key in allowed:
                    continue
                if key in old_values and key not in recover_keys:
                    report["local_changes_preserved"] += 1
                    continue
                added = AttributeAllowedValue(
                    field=field, value=value, normalized_value=key, is_combination=False,
                    sort_order=len(allowed), source="opencart:" + str(shop.id),
                )
                db.add(added)
                allowed[key] = added
                report["values_added"] += 1
            report["values_missing"] += len(old_values - new_values)
        report["fields_missing"] += len(set(old_attrs) - set(category["attribute_ids"]))
        if link is None:
            link = AttributeShopTemplateLink(connection_id=shop.id, remote_category_id=cid,
                                             language_code=shop.language_code)
            db.add(link)
        link.template_id, link.source_hash = template.id, digest
        link.state = {"dictionary_version": 3, "source": source, "field_ids": field_ids, "applied": applied,
                      "template": {"name": clean_text(category["name"]), "is_active": category["enabled"]},
                      "category_path": path}
        if is_new:
            db.flush()
            save_template_revision(db, template, "opencart_import", {"connection_id": shop.id})
    report["categories_missing"] = len(set(links) - present)
    shop.remote_source_id = data["source_id"]
    shop.last_sync_at, shop.last_error, shop.last_report = utc_now(), "", report
    db.flush()
    return report


def sync_shop(db: Session, shop: AttributeShopConnection) -> dict:
    if not shop.enabled:
        raise ValueError("Подключение выключено.")
    sid, token, now = shop.id, uuid.uuid4().hex, utc_now()
    acquired = db.execute(update(AttributeShopConnection).where(
        AttributeShopConnection.id == sid,
        or_(AttributeShopConnection.sync_token == "",
            AttributeShopConnection.sync_started_at < now - LEASE),
    ).values(sync_token=token, sync_started_at=now))
    if acquired.rowcount != 1:
        db.rollback()
        raise ValueError("Этот магазин уже синхронизируется.")
    db.commit()
    try:
        data = fetch_snapshot(shop)
        locked = db.execute(update(AttributeShopConnection).where(
            AttributeShopConnection.id == sid, AttributeShopConnection.sync_token == token,
        ).values(sync_started_at=utc_now()))
        if locked.rowcount != 1:
            raise ValueError("Синхронизация была заменена другим запуском.")
        report = import_snapshot(db, shop, data)
        shop.sync_token, shop.sync_started_at = "", None
        db.commit()
        return report
    except Exception as error:
        db.rollback()
        message = str(error) if isinstance(error, ValueError) else "Не удалось сохранить шаблоны магазина."
        db.execute(update(AttributeShopConnection).where(
            AttributeShopConnection.id == sid, AttributeShopConnection.sync_token == token,
        ).values(sync_token="", sync_started_at=None, last_error=message))
        db.commit()
        raise ValueError(message) from None
