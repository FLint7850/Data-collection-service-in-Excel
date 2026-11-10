"""Staged product-creation workflow for CSV Price Pro / ocStore.

No media is fetched or uploaded during URL import, draft editing, validation,
or CSV export. CSV image URLs are handed to the operator-controlled importer,
which downloads them only when a confirmed import runs on the shop.
"""
from __future__ import annotations

import csv
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config import ATTRIBUTE_ASSISTANT_DIR
from models import (AttributeCatalogDraft, AttributeProduct,
                    AttributeShopConnection, AttributeShopTemplateLink, AttributeTemplate)
from services.attribute_assistant import clean_text, product_template, touch_product
from services.attribute_files import staged_path

FIELDS = ("_CATEGORY_", "_NAME_", "_MODEL_", "_MANUFACTURER_", "_PRICE_",
          "_IMAGE_", "_IMAGES_", "_PRODUCT_IMAGES_", "_ATTRIBUTES_")
MAX_IMAGES = 30
MAX_DESCRIPTION = 60_000


def safe_image_url(raw: str, base: str) -> str:
    """Allow absolute public-looking HTTPS media URLs; never fetch them here."""
    if not isinstance(raw, str) or len(raw) > 2048 or any(ord(c) < 32 for c in raw):
        return ""
    url = urljoin(base, raw.strip())
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or port not in (None, 443):
        return ""
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return ""
    # Also reject IP literals. URL import's validated network fetch is separate;
    # these media URLs are to be evaluated by the importing operator/shop.
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return ""
    except ValueError:
        pass
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _jsonld_products(soup: BeautifulSoup):
    def walk(node):
        if isinstance(node, list):
            for child in node:
                yield from walk(child)
        elif isinstance(node, dict):
            types = node.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if any(isinstance(kind, str) and kind.rsplit("/", 1)[-1].lower() == "product" for kind in types):
                yield node
            for subkey in ("@graph", "mainEntity", "item"):
                if subkey in node:
                    yield from walk(node[subkey])

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.string or script.get_text() or "{}"))
        except (TypeError, ValueError, RecursionError):
            continue


def extract_catalog_data(html: str, url: str) -> dict:
    """Extract safe metadata/remote image URLs from a product page."""
    soup = BeautifulSoup(html, "html.parser")
    result = {"price": "", "description": "", "images": []}
    candidates = []

    def images(value):
        if isinstance(value, dict):
            images(value.get("url") or value.get("contentUrl") or "")
        elif isinstance(value, list):
            for item in value:
                images(item)
        elif isinstance(value, str):
            parsed = safe_image_url(value, url)
            if parsed and parsed not in candidates and len(candidates) < MAX_IMAGES:
                candidates.append(parsed)

    for item in _jsonld_products(soup):
        result["description"] = result["description"] or clean_text(item.get("description"))[:MAX_DESCRIPTION]
        images(item.get("image"))
        offers = item.get("offers") or []
        if isinstance(offers, dict):
            offers = [offers]
        if isinstance(offers, list):
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                specification = offer.get("priceSpecification")
                price = offer.get("price") or (specification.get("price") if isinstance(specification, dict) else None)
                if price is not None and not result["price"]:
                    result["price"] = str(price)
    for selector, attr in (
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('[itemprop="image"]', "content"),
        ('.product-image img', "src"),
        ('.product-images img', "src"),
        ('.product-gallery img', "src"),
        ('.product__gallery img', "src"),
        ('[data-gallery] img', "src"),
    ):
        for tag in soup.select(selector)[:MAX_IMAGES]:
            # Prefer real lazy-loaded originals over a 1x1 placeholder src.
            for candidate in (
                tag.get("data-zoom-image"), tag.get("data-original"),
                tag.get("data-src"), tag.get("data-lazy-src"), tag.get(attr), tag.get("src"),
            ):
                if isinstance(candidate, str) and safe_image_url(candidate, url):
                    images(candidate)
                    break
    if not result["price"]:
        for selector, attr in (
            ('meta[itemprop="price"]', "content"),
            ('[itemprop="price"]', "content"),
            ('meta[property="product:price:amount"]', "content"),
        ):
            node = soup.select_one(selector)
            if node:
                result["price"] = clean_text(node.get(attr) or node.get_text(" "))
                break
    result["images"] = candidates
    result["price"] = normalize_price(result["price"], optional=True)
    return result


def normalize_price(value, *, optional: bool = False) -> str:
    text = str(value if value is not None else "").strip().replace("\u00a0", "").replace(" ", "")
    if not text and optional:
        return ""
    if not re.fullmatch(r"\d{1,12}(?:[.,]\d{1,4})?", text):
        if optional:
            return ""  # An uncertain scraped price needs manual entry.
        raise ValueError("Цена должна быть неотрицательным числом, до 4 знаков после запятой")
    try:
        amount = Decimal(text.replace(",", "."))
        if amount > Decimal("999999999999"):
            raise InvalidOperation
    except InvalidOperation:
        raise ValueError("Некорректная цена") from None
    return format(amount.quantize(Decimal("0.0001")), ".4f")


def attach_catalog_draft(product: AttributeProduct, page: dict, shop_id: int | None = None) -> AttributeCatalogDraft:
    template = product_template(product)
    if template is None:
        raise ValueError("Для новой карточки необходимо выбрать шаблон")
    catalog = page.get("catalog") or {}
    draft = AttributeCatalogDraft(
        product=product, shop_id=shop_id, template_version=template.version,
        price=catalog.get("price", ""),
        description=clean_text(catalog.get("description") or page.get("description"))[:MAX_DESCRIPTION],
        images=list(catalog.get("images") or [])[:MAX_IMAGES],
        source_metadata={"page_url": page.get("url", ""), "source_category": page.get("category", ""),
                         "model_inferred": bool(page.get("model_inferred_from_url"))},
    )
    return draft


def serialize_catalog_draft(product: AttributeProduct) -> dict | None:
    draft = product.catalog_draft
    if draft is None:
        return None
    return {
        "id": draft.id, "product_id": product.id, "shop_id": draft.shop_id,
        "template_version": draft.template_version, "state": draft.state,
        "price": draft.price, "description": draft.description,
        "images": list(draft.images or []),
        "source_metadata": dict(draft.source_metadata or {}),
    }


def update_catalog_draft(db: Session, product: AttributeProduct, payload: dict) -> AttributeCatalogDraft:
    draft = product.catalog_draft
    if draft is None:
        raise ValueError("Товар не является черновиком для создания")
    if draft.state == "imported":
        raise ValueError("Импортированный черновик редактировать нельзя")
    if "shop_id" in payload:
        shop_id = payload["shop_id"]
        if shop_id is not None:
            if type(shop_id) is not int or shop_id < 1:
                raise ValueError("Некорректный магазин")
            shop = db.get(AttributeShopConnection, shop_id)
            if not shop or not shop.enabled:
                raise ValueError("Магазин не найден или отключён")
        draft.shop_id = shop_id
    if "description" in payload:
        if not isinstance(payload["description"], str) or len(payload["description"]) > MAX_DESCRIPTION:
            raise ValueError("Недопустимое значение description")
        draft.description = payload["description"].strip()
    if "price" in payload:
        draft.price = normalize_price(payload["price"], optional=not str(payload["price"]).strip())
    if "images" in payload:
        urls = payload["images"]
        if not isinstance(urls, list) or len(urls) > MAX_IMAGES:
            raise ValueError(f"Можно выбрать не более {MAX_IMAGES} изображений")
        normalized = []
        for url in urls:
            parsed = safe_image_url(url, product.source_url)
            if not parsed:
                raise ValueError("Разрешены только внешние HTTPS-ссылки на изображения")
            if parsed not in normalized:
                normalized.append(parsed)
        draft.images = normalized
    for field, size in (("model", 255), ("name", 1000), ("brand", 255), ("category_name", 500)):
        if field in payload:
            if not isinstance(payload[field], str) or len(payload[field]) > size:
                raise ValueError(f"Недопустимое значение {field}")
            value = payload[field].strip()
            setattr(product, field, value.upper() if field == "model" else value)
    draft.state = "draft"
    touch_product(product)
    db.flush()
    return draft


def catalog_preflight(db: Session, product: AttributeProduct) -> dict:
    """Require EXACT template IDs/order. Blanks are fine, unknown/conflicts are not."""
    errors, warnings = [], []
    draft = product.catalog_draft
    template = product_template(product)
    if draft is None or template is None:
        return {"ok": False, "errors": ["Не задан черновик или шаблон"], "warnings": [], "attributes": []}
    if draft.template_version != template.version:
        errors.append("Шаблон изменился после разбора товара. Повторно назначьте/обработайте шаблон")
    fields = sorted(template.fields, key=lambda field: (field.sort_order, field.id))
    expected = [field.id for field in fields]
    actual = [value.template_field_id for value in product.values if value.is_in_template]
    if len(actual) != len(expected) or set(actual) != set(expected) or len(actual) != len(set(actual)):
        errors.append("Состав полей товара не совпадает с выбранным шаблоном")
    values_by_field = {value.template_field_id: value for value in product.values if value.is_in_template}
    attrs = []
    for field in fields:
        value = values_by_field.get(field.id)
        text = (value.final_value or "").strip() if value else ""
        if value and text and value.status in {"conflict", "unknown", "suggested", "needs_review"}:
            errors.append(f"Подтвердите значение: {field.name}")
        if any(symbol in field.name or symbol in field.group_name for symbol in ("|", "\n", "\r")):
            errors.append(f"Недопустимые символы в шаблоне: {field.name}")
        if any(symbol in text for symbol in ("|", "\n", "\r")):
            errors.append(f"Символы-разделители в значении: {field.name}")
        attrs.append(f"{field.group_name}|{field.name}|{text}")
    for column, data in (("Название", product.name), ("Модель", product.model),
                         ("Категория", product.category_name), ("Бренд", product.brand)):
        if data and (data.lstrip().startswith(("=", "+", "@")) or "\x00" in data):
            errors.append(f"Потенциально небезопасная строка CSV: {column}")
    if not product.name.strip() or not product.model.strip() or not product.category_name.strip():
        errors.append("Для создания нужны название, модель и категория назначения")
    if (draft.source_metadata or {}).get("model_inferred"):
        warnings.append("Модель определена предположительно; проверьте её вручную")
    if not draft.price:
        warnings.append("Цена не заполнена; проверьте цену перед импортом")
    if not draft.images:
        warnings.append("Не выбраны фотографии; карточка будет без изображений")
    if not draft.shop_id:
        warnings.append("Не выбран целевой магазин; CSV можно импортировать вручную")
    else:
        shop = db.get(AttributeShopConnection, draft.shop_id)
        if not shop or not shop.enabled:
            errors.append("Целевой магазин недоступен")
        elif not db.scalar(select(AttributeShopTemplateLink.id).where(
            AttributeShopTemplateLink.connection_id == draft.shop_id,
            AttributeShopTemplateLink.template_id == template.id,
        ).limit(1)):
            warnings.append("Для магазина нет подтверждённой связи шаблона с категорией OpenCart; проверьте соответствие")
    if product.model.strip():
        statement = (select(AttributeProduct.id).join(AttributeCatalogDraft)
            .where(AttributeProduct.id != product.id, AttributeProduct.model == product.model,
                   AttributeCatalogDraft.shop_id == draft.shop_id)
            .limit(1))
        if db.scalar(statement):
            warnings.append("Модель встречается в другом локальном черновике. Проверьте дубликат")
    return {"ok": not errors, "errors": list(dict.fromkeys(errors)),
            "warnings": list(dict.fromkeys(warnings)), "attributes": attrs,
            "total_fields": len(fields), "blank_fields": sum(not (values_by_field.get(f.id) and values_by_field[f.id].final_value) for f in fields)}


def export_catalog_batch(db: Session, batch_id: int, product_ids: list[int], *, include_attributes: bool = True) -> tuple[Path, list[dict]]:
    """Produce cp1251 CSV, but *do not* upload images or create products."""
    if not product_ids or len(product_ids) > 2000 or len(set(product_ids)) != len(product_ids):
        raise ValueError("Выберите от 1 до 2000 уникальных товаров")
    products = list(db.scalars(select(AttributeProduct)
        .where(AttributeProduct.batch_id == batch_id, AttributeProduct.id.in_(product_ids))
        .options(selectinload(AttributeProduct.catalog_draft),
                 selectinload(AttributeProduct.template).selectinload(AttributeTemplate.fields),
                 selectinload(AttributeProduct.values))).all())
    if len(products) != len(product_ids):
        raise ValueError("Некоторые товары не найдены в выбранной обработке")
    order = {product_id: index for index, product_id in enumerate(product_ids)}
    products.sort(key=lambda row: order[row.id])
    checks, rows = [], []
    for product in products:
        check = catalog_preflight(db, product)
        checks.append({"id": product.id, **check})
        if not check["ok"]:
            continue
        draft = product.catalog_draft
        imgs = list(draft.images or [])
        row = {
            "_CATEGORY_": product.category_name, "_NAME_": product.name,
            "_MODEL_": product.model, "_MANUFACTURER_": product.brand,
            "_PRICE_": draft.price, "_IMAGE_": imgs[0] if imgs else "",
            "_IMAGES_": ",".join(imgs[1:]),
            "_PRODUCT_IMAGES_": ",".join(imgs),
            "_ATTRIBUTES_": "\n".join(check["attributes"]),
        }
        rows.append(row)
    if len(rows) != len(products):
        raise ValueError("Экспорт отменён: ошибки проверки в товарах " +
                         ", ".join(str(c["id"]) for c in checks if not c["ok"]))
    # The base import profile has eight columns. Attribute-enabled profiles add
    # _ATTRIBUTES_; the operator MUST map the column to CSV Price Pro appropriately.
    headers = FIELDS if include_attributes else FIELDS[:-1]
    root = ATTRIBUTE_ASSISTANT_DIR / "exports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"catalog_{batch_id}_{uuid.uuid4().hex[:12]}.csv"
    staged = staged_path(db, path)
    with staged.open("w", encoding="cp1251", errors="strict", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, delimiter=";", lineterminator="\r\n",
                                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    return path, checks


def catalog_export_path(filename: str) -> Path:
    if not re.fullmatch(r"catalog_(?:attr_)?[0-9]+_[a-f0-9]{12}\.csv", filename):
        raise ValueError("Файл экспорта не найден")
    root = (ATTRIBUTE_ASSISTANT_DIR / "exports").resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("Файл экспорта не найден")
    return path


def export_catalog_attributes(db: Session, batch_id: int, product_ids: list[int]) -> Path:
    """Second CSV Price Pro pass: update strictly ordered attributes by model.

    Useful for base catalog import profiles that do not contain an
    _ATTRIBUTES_ column.
    """
    if not product_ids or len(product_ids) > 2000 or len(set(product_ids)) != len(product_ids):
        raise ValueError("Выберите от 1 до 2000 уникальных товаров")
    products = list(db.scalars(select(AttributeProduct)
        .where(AttributeProduct.batch_id == batch_id, AttributeProduct.id.in_(product_ids))
        .options(selectinload(AttributeProduct.catalog_draft),
                 selectinload(AttributeProduct.template).selectinload(AttributeTemplate.fields),
                 selectinload(AttributeProduct.values))).all())
    if len(products) != len(product_ids):
        raise ValueError("Некоторые товары не найдены")
    by_id = {row.id: row for row in products}
    rows = []
    for product_id in product_ids:
        product = by_id[product_id]
        check = catalog_preflight(db, product)
        if not check["ok"]:
            raise ValueError(f"Товар {product_id}: " + "; ".join(check["errors"]))
        rows.append({"_MODEL_": product.model, "_ATTRIBUTES_": "\n".join(check["attributes"])})
    root = ATTRIBUTE_ASSISTANT_DIR / "exports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"catalog_attr_{batch_id}_{uuid.uuid4().hex[:12]}.csv"
    temporary = staged_path(db, path)
    with temporary.open("w", encoding="cp1251", errors="strict", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["_MODEL_", "_ATTRIBUTES_"], delimiter=";",
                                lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return path
