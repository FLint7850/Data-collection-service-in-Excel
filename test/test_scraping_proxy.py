import os
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text

from services.scraping.proxy import (
    PROXY_ENV_NAME,
    browser_proxy_config,
    redact_proxy_credentials,
    resolve_scraping_proxy_url,
)


class ScrapingProxyPolicyTests(unittest.TestCase):
    proxy_url = "http://proxy-user:proxy-pass@127.0.0.1:8080"

    def test_direct_mode_does_not_require_or_use_configured_proxy(self) -> None:
        with patch.dict(os.environ, {PROXY_ENV_NAME: "invalid"}, clear=False):
            self.assertIsNone(resolve_scraping_proxy_url(False))

    def test_enabled_mode_requires_a_valid_configured_proxy(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PROXY_ENV_NAME, None)
            with self.assertRaisesRegex(RuntimeError, PROXY_ENV_NAME):
                resolve_scraping_proxy_url(True)

        with patch.dict(os.environ, {PROXY_ENV_NAME: "ftp://127.0.0.1:21"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "http://"):
                resolve_scraping_proxy_url(True)

    def test_authenticated_proxy_is_converted_without_credentials_in_server(self) -> None:
        config = browser_proxy_config(self.proxy_url)

        self.assertEqual(config["server"], "http://127.0.0.1:8080")
        self.assertEqual(config["username"], "proxy-user")
        self.assertEqual(config["password"], "proxy-pass")

    def test_proxy_credentials_are_redacted_from_errors(self) -> None:
        with patch.dict(os.environ, {PROXY_ENV_NAME: self.proxy_url}, clear=False):
            message = redact_proxy_credentials(
                f"Connection failed via {self.proxy_url} and http://other:secret@example.test:80"
            )

        self.assertNotIn("proxy-pass", message)
        self.assertNotIn("other:secret", message)
        self.assertIn("http://127.0.0.1:8080", message)

    def test_requests_session_obeys_the_per_scan_switch(self) -> None:
        with patch.dict(os.environ, {PROXY_ENV_NAME: self.proxy_url}, clear=False):
            with patch("services.scraping.fallback.BrowserMethodSession") as browser_session:
                from services.scraping.fallback import ProductSiteCrawler

                crawler = ProductSiteCrawler(
                    ["https://example.test/catalog/"],
                    1,
                    threading.Event(),
                    threading.Event(),
                    1,
                    use_proxy=True,
                )
                session = crawler.get_session()

        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies["http"], self.proxy_url)
        self.assertEqual(session.proxies["https"], self.proxy_url)
        browser_session.assert_called_once_with(
            crawler.stop_signal,
            1,
            profile_dir=None,
            initial_method="requests",
            proxy_url=self.proxy_url,
        )
        session.close()

    def test_project_and_news_forms_keep_independent_proxy_switches(self) -> None:
        from services.news import normalize_news_monitor
        from services.projects import make_project, public_project

        project = make_project("Proxy project", ["https://example.test/catalog/"])
        self.assertFalse(public_project(project)["use_proxy"])
        project["use_proxy"] = True
        self.assertTrue(public_project(project)["use_proxy"])

        direct_donor = normalize_news_monitor(
            {"brand": "Brand", "start_urls": ["https://direct.example.test"]}
        )
        proxy_donor = normalize_news_monitor(
            {
                "brand": "Brand",
                "start_urls": ["https://proxy.example.test"],
                "use_proxy": True,
            }
        )
        self.assertFalse(direct_donor["use_proxy"])
        self.assertTrue(proxy_donor["use_proxy"])

    def test_runtime_migration_upgrades_existing_project_and_donor_tables(self) -> None:
        from database.session import migrate_donors_table, migrate_projects_table

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("CREATE TABLE projects (id INTEGER PRIMARY KEY)")
                )
                connection.execute(
                    text(
                        "CREATE TABLE connection_methods ("
                        "id INTEGER PRIMARY KEY, code VARCHAR(64) UNIQUE)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO connection_methods (id, code) "
                        "VALUES (1, 'requests')"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE donors ("
                        "id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL)"
                    )
                )
                migrate_projects_table(connection)
                migrate_donors_table(connection)

            inspector = inspect(engine)
            project_columns = {
                column["name"] for column in inspector.get_columns("projects")
            }
            donor_columns = {
                column["name"] for column in inspector.get_columns("donors")
            }
            self.assertIn("use_proxy", project_columns)
            self.assertIn("use_proxy", donor_columns)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
