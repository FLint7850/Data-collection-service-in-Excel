"""HTTP routes for this application area."""

from flask import Blueprint

from runtime.news_tasks import send_news_email
from config import DEFAULT_FEED_GENERATE_URL, DEFAULT_FEED_URL
from flask import request
from runtime.state import news_lock, news_settings
from services.application import ensure_storage
from services.domain_revisions import bump_domain_revision
from services.normalization import jsonify, normalize_emails, normalize_feed_url, normalize_feed_urls, parse_db_int
from typing import List
from services.scraping import clean_text
from services.news import public_news_configuration, save_news_configuration

bp = Blueprint("routes_settings", __name__)


@bp.patch("/api/news/settings")
def api_update_news_settings():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    with news_lock:
        if "own_sites" in payload and isinstance(payload.get("own_sites"), list):
            own_sites_payload = [item for item in payload.get("own_sites", []) if isinstance(item, dict)]
            own_sites = []
            for index, item in enumerate(own_sites_payload, start=1):
                feed_url = normalize_feed_url(str(item.get("feed_url") or "").strip())
                if not feed_url:
                    continue
                feed_generate_url = normalize_feed_url(str(item.get("feed_generate_url") or "").strip())
                site = {
                    "name": clean_text(str(item.get("name") or "")) or f"Фид {index}",
                    "feed_url": feed_url,
                    "feed_generate_url": feed_generate_url,
                }
                site_id = parse_db_int(item.get("id"))
                if site_id:
                    site["id"] = site_id
                own_sites.append(site)
            feed_urls = [
                item["feed_url"]
                for item in own_sites
            ]
            feed_generate_urls = [
                item["feed_generate_url"]
                for item in own_sites
                if item.get("feed_generate_url")
            ]
            news_settings["own_sites"] = own_sites
            news_settings["feed_urls"] = feed_urls
            news_settings["feed_url"] = feed_urls[0] if feed_urls else ""
            news_settings["feed_generate_urls"] = feed_generate_urls
            news_settings["feed_generate_url"] = feed_generate_urls[0] if feed_generate_urls else ""
        if "feed_url" in payload:
            news_settings["feed_url"] = str(payload.get("feed_url") or DEFAULT_FEED_URL).strip()
        if "feed_generate_url" in payload:
            news_settings["feed_generate_url"] = str(payload.get("feed_generate_url") or DEFAULT_FEED_GENERATE_URL).strip()
        if "feed_urls" in payload:
            feed_urls = normalize_feed_urls(payload.get("feed_urls") or DEFAULT_FEED_URL, DEFAULT_FEED_URL)
            news_settings["feed_urls"] = feed_urls
            news_settings["feed_url"] = feed_urls[0] if feed_urls else DEFAULT_FEED_URL
        if "feed_generate_urls" in payload:
            feed_generate_urls = normalize_feed_urls(payload.get("feed_generate_urls") or DEFAULT_FEED_GENERATE_URL, DEFAULT_FEED_GENERATE_URL)
            news_settings["feed_generate_urls"] = feed_generate_urls
            news_settings["feed_generate_url"] = feed_generate_urls[0] if feed_generate_urls else DEFAULT_FEED_GENERATE_URL
        if "auto_cleanup" in payload:
            news_settings["auto_cleanup"] = bool(payload.get("auto_cleanup"))
        if "smtp" in payload and isinstance(payload.get("smtp"), dict):
            smtp_payload = payload["smtp"]
            smtp = dict(news_settings.get("smtp", {}))
            smtp.pop("sender", None)
            for key in ("host", "security", "username"):
                if key in smtp_payload:
                    smtp[key] = str(smtp_payload.get(key) or "").strip()
            if "port" in smtp_payload:
                try:
                    smtp["port"] = int(smtp_payload.get("port") or 465)
                except (TypeError, ValueError):
                    smtp["port"] = 465
            if "password" in smtp_payload and str(smtp_payload.get("password") or "").strip():
                smtp["password"] = str(smtp_payload.get("password")).strip()
            if "recipients" in smtp_payload:
                smtp["recipients"] = normalize_emails(smtp_payload.get("recipients"))
            news_settings["smtp"] = smtp
        save_news_configuration()
        if "own_sites" in payload:
            bump_domain_revision("feed_comparison")
    return jsonify(public_news_configuration())


@bp.post("/api/news/email/test")
def api_test_news_email():
    ensure_storage()
    errors: List[str] = []
    if not send_news_email(None, 0, test=True, error_holder=errors):
        return jsonify({"error": errors[-1] if errors else "Email не отправлен. Проверьте SMTP-настройки и логи мониторинга."}), 500
    return jsonify({"ok": True})
