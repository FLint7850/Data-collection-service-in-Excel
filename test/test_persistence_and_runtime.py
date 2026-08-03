import io
import threading
import unittest
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.repositories.projects import delete_project, update_project
from config import MSK_TZ
from models import Base, Brand, FileImport, Project
from runtime.state import news_lock, news_settings
from services.file_validation import validate_xlsx_archive


class IsolatedDatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()


class TargetedPersistenceTests(IsolatedDatabaseTestCase):
    def test_project_update_and_delete_do_not_touch_siblings(self) -> None:
        with self.Session.begin() as session:
            first = Project(legacy_id="first", name="First", start_urls=[])
            second = Project(legacy_id="second", name="Second", start_urls=[])
            session.add_all([first, second])
            session.flush()
            first_id, second_id = first.id, second.id

            update_project(first_id, {"name": "Updated", "unknown": "ignored"}, session)
            self.assertTrue(delete_project(first_id, session))

        with self.Session() as session:
            self.assertIsNone(session.get(Project, first_id))
            self.assertEqual(session.get(Project, second_id).name, "Second")


class SupplierFeedConfigurationTests(unittest.TestCase):
    def test_supplier_payload_keeps_configured_optional_fields(self) -> None:
        from services.feeds import validate_feed_comparison_site_payload

        payload = validate_feed_comparison_site_payload(
            {
                "name": "Поставщик",
                "feed_url": "https://example.test/feed.xml",
                "model_field": "<model>",
                "name_field": "<product_name>",
                "price_field": "price",
                "brand_field": "param:Бренд",
                "url_field": " ",
            },
            supplier=True,
        )

        self.assertEqual(payload["model_field"], "model")
        self.assertEqual(payload["name_field"], "product_name")
        self.assertEqual(payload["price_field"], "price")
        self.assertEqual(payload["brand_field"], "param:Бренд")
        self.assertEqual(payload["url_field"], "")

    def test_csv_reads_only_explicitly_configured_optional_columns(self) -> None:
        from services.feeds import read_supplier_feed_rows

        content = (
            "SKU;Название поставщика;Стоимость;Марка поставщика;Карточка\n"
            "A-1;Чайник;12990;MAUNFELD;https://example.test/a-1\n"
        ).encode("utf-8")

        configured = read_supplier_feed_rows(
            content,
            "SKU",
            name_field="Название поставщика",
            price_field="Стоимость",
            brand_field="Марка поставщика",
            url_field="Карточка",
        )
        without_optional_fields = read_supplier_feed_rows(content, "SKU")

        self.assertEqual(
            configured[0],
            {
                "row_number": 2,
                "source_model": "A-1",
                "name": "Чайник",
                "price": "12990",
                "brand": "MAUNFELD",
                "url": "https://example.test/a-1",
            },
        )
        self.assertEqual(without_optional_fields[0]["name"], "A-1")
        self.assertEqual(without_optional_fields[0]["price"], "")
        self.assertEqual(without_optional_fields[0]["brand"], "")
        self.assertEqual(without_optional_fields[0]["url"], "")

    def test_xml_reads_only_explicitly_configured_optional_fields(self) -> None:
        from services.feeds import read_supplier_feed_rows

        content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <offers><offer>
          <sku>A-1</sku><display>Chaynik</display><cost>12990</cost>
          <maker>MAUNFELD</maker><href>https://example.test/a-1</href>
        </offer></offers>"""

        rows = read_supplier_feed_rows(
            content,
            "sku",
            name_field="display",
            price_field="cost",
            brand_field="maker",
            url_field="href",
        )

        self.assertEqual(rows[0]["name"], "Chaynik")
        self.assertEqual(rows[0]["price"], "12990")
        self.assertEqual(rows[0]["brand"], "MAUNFELD")
        self.assertEqual(rows[0]["url"], "https://example.test/a-1")

    def test_runtime_migration_adds_supplier_field_columns(self) -> None:
        from database.session import migrate_supplier_feeds_table

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE supplier_feeds ("
                        "id INTEGER PRIMARY KEY, model_field VARCHAR(255) NOT NULL, "
                        "exclusions JSON NOT NULL DEFAULT '[]', "
                        "replace_rules TEXT NOT NULL DEFAULT ''"
                        ")"
                    )
                )
                migrate_supplier_feeds_table(connection)
            columns = {column["name"] for column in inspect(engine).get_columns("supplier_feeds")}
        finally:
            engine.dispose()

        self.assertTrue(
            {"name_field", "price_field", "brand_field", "url_field"}.issubset(columns)
        )


class CompactPayloadTests(IsolatedDatabaseTestCase):
    def test_file_import_progress_skips_large_form_settings(self) -> None:
        import services.file_import_service as file_import_service

        with self.Session.begin() as session:
            session.add(
                FileImport(
                    id=1,
                    exclusions=["value"] * 100,
                    model_field="model",
                    price_field="price",
                    replace_rules="rule",
                    file={},
                    state={"status": "idle", "percent": 0},
                )
            )

        with (
            self.Session() as session,
            patch.object(
                file_import_service,
                "normalize_file_import_exclusions",
                side_effect=AssertionError("Compact polling touched form settings"),
            ),
        ):
            payload = file_import_service.public_file_import_progress(session)

        self.assertEqual(payload["state"]["status"], "idle")
        self.assertNotIn("exclusions", payload)


class LogStorageTests(IsolatedDatabaseTestCase):
    def test_sqlite_logs_support_initial_page_and_delta(self) -> None:
        import services.log_service as log_service

        @contextmanager
        def isolated_session_scope():
            session = self.Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        with patch.object(log_service, "session_scope", isolated_session_scope):
            first_id = log_service.append_log({"level": "info", "message": "Первое"})
            initial = log_service.query_logs(limit=10)
            second_id = log_service.append_log({"level": "error", "message": "Второе"})
            delta = log_service.query_logs(after_id=first_id, limit=10)
            log_service.clear_logs()
            after_clear = log_service.query_logs(after_id=second_id, limit=10)

        self.assertEqual(initial["logs_total"], 1)
        self.assertEqual(initial["logs"][0]["message"], "Первое")
        self.assertEqual([item["id"] for item in delta["logs"]], [second_id])
        self.assertEqual(delta["logs_counts"], {"error": 1, "info": 1})
        self.assertFalse(after_clear["delta"])
        self.assertEqual(after_clear["logs"], [])


class SchedulerQueryTests(IsolatedDatabaseTestCase):
    def test_scheduler_selects_only_due_enabled_brands(self) -> None:
        import runtime.news_tasks as news_tasks

        now = datetime.now(MSK_TZ).replace(second=15, microsecond=0)
        with self.Session.begin() as session:
            session.add_all(
                [
                    Brand(
                        name="Due",
                        search_name="due",
                        group_name="Маржа",
                        state={"status": "idle"},
                        enabled=True,
                        schedule_type="daily",
                        scan_time=now.strftime("%H:%M"),
                    ),
                    Brand(
                        name="Disabled",
                        search_name="disabled",
                        group_name="Маржа",
                        state={"status": "idle"},
                        enabled=False,
                        schedule_type="daily",
                        scan_time=now.strftime("%H:%M"),
                    ),
                    Brand(
                        name="Future",
                        search_name="future",
                        group_name="Маржа",
                        state={"status": "idle"},
                        enabled=True,
                        schedule_type="once",
                        next_run_at=(now + timedelta(hours=1)).replace(tzinfo=None),
                    ),
                ]
            )

        @contextmanager
        def isolated_session_scope():
            session = self.Session()
            try:
                yield session
                session.commit()
            finally:
                session.close()

        with patch.object(news_tasks, "session_scope", isolated_session_scope):
            candidates = news_tasks.scheduled_brand_candidates(now)

        self.assertEqual([brand.name for brand in candidates], ["Due"])


class RuntimeSafetyTests(unittest.TestCase):
    def test_independent_news_scans_start_without_global_limit(self) -> None:
        import runtime.news_tasks as news_tasks
        import services.news as news_service

        started = {"first": threading.Event(), "second": threading.Event()}
        release = threading.Event()

        def run_scan(monitor_id: str, _manual: bool) -> None:
            started[monitor_id].set()
            release.wait(2)

        def get_monitor(monitor_id: str):
            return {"id": monitor_id, "state": {"status": "queued"}}

        with (
            patch.object(news_service, "get_news_monitor", side_effect=get_monitor),
            patch.object(news_tasks, "scan_news_monitor", side_effect=run_scan),
        ):
            self.assertTrue(news_tasks.start_news_scan("first", manual=True))
            self.assertTrue(news_tasks.start_news_scan("second", manual=True))
            self.assertTrue(started["first"].wait(1))
            self.assertTrue(started["second"].wait(1))
            self.assertFalse(news_tasks.start_news_scan("first", manual=True))
            with news_lock:
                threads = list(news_tasks.news_scan_threads.values())
            release.set()
            for thread in threads:
                thread.join(2)

    def test_public_smtp_configuration_never_contains_password(self) -> None:
        from services.news import public_news_configuration

        with news_lock:
            original = deepcopy(news_settings)
            news_settings.clear()
            news_settings.update(
                {
                    "monitors": [],
                    "own_sites": [],
                    "smtp": {
                        "host": "smtp.example.test",
                        "password": "server-secret",
                        "username": "sender@example.test",
                    },
                }
            )
        try:
            payload = public_news_configuration()
        finally:
            with news_lock:
                news_settings.clear()
                news_settings.update(original)

        self.assertNotIn("password", payload["smtp"])
        self.assertTrue(payload["smtp"]["password_set"])

    def test_public_own_sites_keep_stable_database_ids(self) -> None:
        from services.news import own_sites_from_settings

        sites = own_sites_from_settings(
            {
                "own_sites": [
                    {
                        "id": 17,
                        "name": "Основной сайт",
                        "feed_url": "https://example.test/feed.xml",
                        "feed_generate_url": "",
                    }
                ]
            }
        )

        self.assertEqual(sites[0]["id"], 17)

    def test_suspicious_xlsx_compression_is_rejected(self) -> None:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("xl/sharedStrings.xml", b"0" * (1024 * 1024))
        archive.seek(0)

        with self.assertRaisesRegex(ValueError, "коэффициент сжатия"):
            validate_xlsx_archive(archive)


if __name__ == "__main__":
    unittest.main()
