import subprocess
import sys
import unittest
from pathlib import Path


class BackendModuleTests(unittest.TestCase):
    def test_core_paths_still_resolve_from_the_repository_root(self) -> None:
        from services.core_service import BASE_DIR

        self.assertEqual(BASE_DIR, Path(__file__).resolve().parents[1])

    def test_service_modules_can_be_imported_without_app_bootstrap(self) -> None:
        modules = [
            "services.scraping_service",
            "services.project_service",
            "services.news_service",
            "services.progress_service",
            "services.log_service",
            "services.file_import_service",
            "services.feed_service",
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
        self.assertEqual(len(routes), 63)
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


if __name__ == "__main__":
    unittest.main()
