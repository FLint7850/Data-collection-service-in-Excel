import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class BackendModuleTests(unittest.TestCase):
    def test_connection_catalog_fallback_survives_uninitialized_log_table(self) -> None:
        from runtime.state import connection_method_cache
        from services.connections import load_connection_methods

        with (
            patch.dict(connection_method_cache, {"methods": [], "loaded_at": 0.0}, clear=True),
            patch("services.connections.session_scope", side_effect=RuntimeError("database is not initialized")),
            patch("services.log_service.append_unified_log", side_effect=RuntimeError("log table is not initialized")),
        ):
            methods = load_connection_methods(force_refresh=True)

        self.assertEqual([method["code"] for method in methods], ["requests"])

    def test_partial_news_result_uses_collected_products_without_more_page_requests(self) -> None:
        from runtime.news_tasks import build_partial_news_items

        rows = build_partial_news_items(
            [
                {
                    "model": "ABC-1",
                    "price": "100",
                    "url": "https://example.test/product/abc-1",
                }
            ],
            {"group": "Маржа", "brand": "Demo"},
            [
                {"source_label": "Есть", "codes": {"ABC-1"}},
                {"source_label": "Нет", "codes": set()},
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "ABC-1")
        self.assertEqual(rows[0]["missing_on"], "Нет")

    def test_core_paths_still_resolve_from_the_repository_root(self) -> None:
        from config import BASE_DIR

        self.assertEqual(BASE_DIR, Path(__file__).resolve().parents[1])

    def test_service_modules_can_be_imported_without_app_bootstrap(self) -> None:
        modules = [
            "services.scraping",
            "services.projects",
            "services.news",
            "services.progress_service",
            "services.log_service",
            "services.file_import_service",
            "services.feeds",
            "runtime.news_tasks",
            "runtime.project_tasks",
        ]
        script = ";".join(f"import {module}" for module in modules)
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_blueprints_preserve_the_http_contract(self) -> None:
        from app import app

        routes = {
            (method, str(rule))
            for rule in app.url_map.iter_rules()
            for method in rule.methods - {"HEAD", "OPTIONS"}
        }
        self.assertTrue(
            {
                ("POST", "/api/auth/login"),
                ("GET", "/api/projects"),
                ("POST", "/api/projects/<project_id>/start"),
                ("GET", "/api/news"),
                ("PATCH", "/api/news/monitors/<monitor_id>"),
                ("POST", "/api/file-import/compare"),
                ("GET", "/api/price-converter"),
                ("POST", "/api/price-converter/convert"),
                ("POST", "/api/feed-comparison/start"),
                ("GET", "/api/logs"),
                ("GET", "/progress"),
            }.issubset(routes)
        )
        self.assertFalse(
            {
                ("GET", "/api/connection-methods"),
                ("GET", "/api/news/brands/<brand_id>"),
            }.intersection(routes)
        )

    def test_progress_endpoint_returns_only_the_compact_sync_payload(self) -> None:
        from app import app
        from routes.progress import progress_poll

        compact_payload = {
            "cursor": "r1:1",
            "upsert_projects": [
                {"id": "1", "name": "Project", "state": {"status": "idle"}}
            ],
        }
        with (
            app.test_request_context("/progress?projects=1&news=1"),
            patch("routes.progress.ensure_storage"),
            patch(
                "routes.progress.progress_payload",
                return_value=compact_payload,
            ),
        ):
            payload = progress_poll().get_json()

        self.assertEqual(payload, compact_payload)

    def test_news_deletion_publishes_progress_removals(self) -> None:
        from app import app
        from routes.news import api_delete_news_monitor

        monitor = {
            "id": "2",
            "brand_id": 3,
            "brand": "Bora",
            "group": "Маржа",
            "state": {"status": "idle"},
        }
        with (
            app.test_request_context(
                "/api/news/monitors/2?mode=brand",
                method="DELETE",
            ),
            patch("routes.news.get_news_monitor", return_value=monitor),
            patch("routes.news.news_settings", {"monitors": [monitor]}),
            patch("routes.news.news_stop_events", {}),
            patch("routes.news.request_news_stop"),
            patch("routes.news.delete_news_csv_for_monitor"),
            patch("routes.news.delete_news_records"),
            patch("routes.news.add_news_log"),
            patch("routes.news.publish_news_progress_snapshot") as publish_snapshot,
        ):
            response = api_delete_news_monitor("2")

        self.assertTrue(response.get_json()["ok"])
        publish_snapshot.assert_called_once_with()

    def test_domain_revisions_change_only_for_the_requested_domain(self) -> None:
        from services.domain_revisions import bump_domain_revision, domain_revision

        previous_file_import = domain_revision("file_import")
        previous_settings = domain_revision("settings")

        current_file_import = bump_domain_revision("file_import")

        self.assertNotEqual(current_file_import, previous_file_import)
        self.assertEqual(domain_revision("settings"), previous_settings)

    def test_settings_revision_endpoint_is_lightweight(self) -> None:
        from app import app
        from routes.news import api_news

        with (
            app.test_request_context("/api/news?scope=settings-revision"),
            patch("routes.news.ensure_storage"),
            patch("routes.news.domain_revision", return_value="settings-r2"),
        ):
            payload = api_news().get_json()

        self.assertEqual(payload, {"revision": "settings-r2"})

    def test_settings_accept_an_explicit_empty_feed_list(self) -> None:
        from app import app
        from routes.settings import api_update_news_settings

        settings = {"monitors": []}
        with (
            app.test_request_context(
                "/api/news/settings",
                method="PATCH",
                json={"own_sites": []},
            ),
            patch("routes.settings.ensure_storage"),
            patch("routes.settings.news_settings", settings),
            patch("routes.settings.save_news_configuration"),
            patch("routes.settings.bump_domain_revision"),
            patch(
                "routes.settings.public_news_configuration",
                return_value={"own_sites": []},
            ),
        ):
            response = api_update_news_settings()

        self.assertEqual(response.get_json()["own_sites"], [])
        self.assertEqual(settings["own_sites"], [])
        self.assertEqual(settings["feed_urls"], [])
        self.assertEqual(settings["feed_generate_urls"], [])


if __name__ == "__main__":
    unittest.main()
