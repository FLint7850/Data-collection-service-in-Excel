"""Authenticated shop connection settings and per-shop synchronization."""
from flask import Blueprint, g, jsonify, request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from models import AttributeShopConnection, AttributeShopTemplateLink
from services.application import ensure_storage
from services.opencart_sync import configure_shop, serialize_shop, sync_shop

bp = Blueprint("routes_opencart", __name__)
BASE = "/api/attribute-assistant/shops"


def body():
    if request.content_length is None or request.content_length > 16384:
        raise ValueError("Некорректный размер запроса.")
    result = request.get_json(silent=True)
    if not isinstance(result, dict):
        raise ValueError("Ожидается JSON-объект.")
    return result


def shop_by_id(sid):
    shop = g.db.get(AttributeShopConnection, sid)
    if shop is None:
        raise ValueError("Подключение не найдено.")
    return shop


@bp.get(BASE)
def api_opencart_shops():
    ensure_storage()
    return jsonify([serialize_shop(s) for s in g.db.scalars(
        select(AttributeShopConnection).order_by(AttributeShopConnection.id))])


@bp.post(BASE)
@bp.patch(BASE + "/<int:sid>")
def api_opencart_save(sid=None):
    ensure_storage()
    try:
        shop = configure_shop(g.db, body(), shop_by_id(sid) if sid else None)
        g.db.flush()
        return jsonify(serialize_shop(shop)), 200 if sid else 201
    except (ValueError, IntegrityError) as error:
        g.db.rollback()
        message = str(error) if isinstance(error, ValueError) else "Магазин с таким названием или URL уже добавлен."
        return jsonify({"error": message}), 400


@bp.delete(BASE + "/<int:sid>")
def api_opencart_delete(sid):
    ensure_storage()
    try:
        shop = shop_by_id(sid)
        if serialize_shop(shop)["syncing"]:
            raise ValueError("Дождитесь окончания синхронизации.")
        g.db.execute(delete(AttributeShopTemplateLink).where(AttributeShopTemplateLink.connection_id == sid))
        g.db.delete(shop)
        g.db.flush()
        return jsonify({"deleted": True})
    except ValueError as error:
        g.db.rollback()
        return jsonify({"error": str(error)}), 400


@bp.post(BASE + "/<int:sid>/sync")
def api_opencart_sync(sid):
    ensure_storage()
    try:
        shop = shop_by_id(sid)
        report = sync_shop(g.db, shop)
        return jsonify({"shop": serialize_shop(shop), "report": report})
    except ValueError as error:
        g.db.rollback()
        return jsonify({"error": str(error)}), 400
