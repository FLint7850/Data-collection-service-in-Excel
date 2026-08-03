import io
import threading
import unittest
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.repositories.projects import delete_project, update_project
from config import MSK_TZ
from models import Base, Brand, Project
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

    def test_suspicious_xlsx_compression_is_rejected(self) -> None:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("xl/sharedStrings.xml", b"0" * (1024 * 1024))
        archive.seek(0)

        with self.assertRaisesRegex(ValueError, "коэффициент сжатия"):
            validate_xlsx_archive(archive)


if __name__ == "__main__":
    unittest.main()
