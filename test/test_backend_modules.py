import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class BackendModuleTests(unittest.TestCase):
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

    def test_progress_endpoint_includes_requested_form_details(self) -> None:
        from app import app
        from routes.progress import progress_poll

        project = {"id": "1", "name": "Project", "state": {"status": "idle"}}
        monitor = {"id": "2", "brand_id": 3, "brand": "Bora", "group": "Маржа"}
        with (
            app.test_request_context(
                "/progress?projects=1&news=1&project_detail=1&news_detail=2"
            ),
            patch("routes.progress.ensure_storage"),
            patch("routes.progress.progress_payload", return_value={"cursor": "r1:1"}),
            patch("routes.progress.get_project", return_value=project),
            patch("routes.progress.public_project", return_value={**project, "start_urls": []}),
            patch("routes.progress.get_news_monitor", return_value=monitor),
            patch(
                "routes.progress.public_news_brand_monitors",
                return_value=[{**monitor, "start_urls": []}],
            ),
        ):
            payload = progress_poll().get_json()

        self.assertEqual(payload["project_detail"]["id"], "1")
        self.assertEqual(payload["news_details"][0]["id"], "2")

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


if __name__ == "__main__":
    unittest.main()
