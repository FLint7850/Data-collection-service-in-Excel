import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, delete, event, inspect, select, text
from sqlalchemy.orm import sessionmaker

from models import AppSetting, ApplicationLog
from services import log_service


class DailyLogCleanupTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(self.directory.name) / 'logs.db'}")
        self.addCleanup(self.engine.dispose)
        AppSetting.__table__.create(self.engine)
        ApplicationLog.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.now = datetime(2026, 10, 9, 12, tzinfo=UTC)
        with self.Session.begin() as session:
            session.add(AppSetting(id=1, auto_cleanup=True))
        session_patch = patch.object(log_service, "session_scope", self.session_scope)
        session_patch.start()
        self.addCleanup(session_patch.stop)

    @contextmanager
    def session_scope(self):
        with self.Session.begin() as session:
            yield session

    def add_log(self, message, created_at):
        with self.Session.begin() as session:
            session.add(ApplicationLog(message=message, created_at=created_at.replace(tzinfo=None)))

    def messages(self):
        with self.Session() as session:
            return list(session.scalars(select(ApplicationLog.message).order_by(ApplicationLog.id)))

    def last_run(self):
        with self.Session() as session:
            return session.scalar(select(AppSetting.logs_last_cleanup_at).where(AppSetting.id == 1))

    def test_cleanup_preserves_seven_day_boundary_and_uses_utc(self):
        self.add_log("expired", self.now - timedelta(days=7, microseconds=1))
        self.add_log("boundary", self.now - timedelta(days=7))
        self.add_log("recent", self.now - timedelta(days=6))
        moscow_now = self.now.astimezone(timezone(timedelta(hours=3)))

        self.assertEqual(log_service.run_daily_log_cleanup(moscow_now), 1)

        self.assertEqual(self.messages(), ["boundary", "recent"])
        self.assertEqual(self.last_run(), self.now.replace(tzinfo=None))

    def test_disabled_cleanup_preserves_logs_and_runs_after_enable(self):
        log_service.set_log_auto_cleanup(False)
        self.add_log("expired", self.now - timedelta(days=8))

        self.assertIsNone(log_service.run_daily_log_cleanup(self.now))
        self.assertIsNone(self.last_run())
        self.assertEqual(self.messages(), ["expired"])

        log_service.set_log_auto_cleanup(True)
        self.assertEqual(log_service.run_daily_log_cleanup(self.now), 1)
        self.assertEqual(self.messages(), [])

    def test_missing_settings_leave_logs_untouched(self):
        with self.Session.begin() as session:
            session.execute(delete(AppSetting))
        self.add_log("expired", self.now - timedelta(days=8))

        self.assertIsNone(log_service.run_daily_log_cleanup(self.now))
        self.assertEqual(self.messages(), ["expired"])

    def test_daily_schedule_survives_new_sessions_and_runs_at_24_hours(self):
        self.add_log("first", self.now - timedelta(days=8))
        self.assertEqual(log_service.run_daily_log_cleanup(self.now), 1)
        self.add_log("second", self.now - timedelta(days=8))

        self.assertIsNone(log_service.run_daily_log_cleanup(self.now + timedelta(hours=24, microseconds=-1)))
        self.assertEqual(self.messages(), ["second"])
        self.assertEqual(log_service.run_daily_log_cleanup(self.now + timedelta(days=1)), 1)
        self.assertEqual(self.messages(), [])
        self.assertEqual(self.last_run(), (self.now + timedelta(days=1)).replace(tzinfo=None))

    def test_empty_cleanup_still_records_successful_daily_run(self):
        self.assertEqual(log_service.run_daily_log_cleanup(self.now), 0)
        self.add_log("late old event", self.now - timedelta(days=8))

        self.assertIsNone(log_service.run_daily_log_cleanup(self.now + timedelta(minutes=1)))
        self.assertEqual(self.messages(), ["late old event"])

    def test_failed_deletion_rolls_back_schedule_and_can_retry(self):
        self.add_log("expired", self.now - timedelta(days=8))

        def fail_deletion(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("DELETE FROM application_logs"):
                raise RuntimeError("temporary deletion failure")

        event.listen(self.engine, "before_cursor_execute", fail_deletion)
        try:
            with self.assertRaisesRegex(RuntimeError, "temporary deletion failure"):
                log_service.run_daily_log_cleanup(self.now)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_deletion)

        self.assertIsNone(self.last_run())
        self.assertEqual(self.messages(), ["expired"])
        self.assertEqual(log_service.run_daily_log_cleanup(self.now), 1)

    def test_concurrent_workers_perform_one_daily_cleanup(self):
        self.add_log("expired", self.now - timedelta(days=8))
        both_workers_ready = threading.Barrier(2, timeout=5)

        def synchronize_claims(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE app_settings"):
                both_workers_ready.wait()

        event.listen(self.engine, "before_cursor_execute", synchronize_claims)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(log_service.run_daily_log_cleanup, self.now) for _ in range(2)]
                results = [job.result(timeout=10) for job in jobs]
        finally:
            event.remove(self.engine, "before_cursor_execute", synchronize_claims)

        self.assertCountEqual(results, [1, None])
        self.assertEqual(self.messages(), [])

    def test_background_loop_cleans_without_log_viewer_requests(self):
        from runtime.log_cleanup import _cleanup_loop

        self.add_log("expired", datetime.now(UTC) - timedelta(days=8))
        stop_event = Mock()
        stop_event.is_set.side_effect = [False, True]

        _cleanup_loop(stop_event)

        self.assertEqual(self.messages(), [])
        self.assertIsNotNone(self.last_run())

    def test_viewing_logs_does_not_delete_records(self):
        from app import app
        from routes.logs import api_logs

        self.add_log("expired", self.now - timedelta(days=8))
        with app.test_request_context("/api/logs"), patch("routes.logs.ensure_storage"):
            payload = api_logs().get_json()

        self.assertEqual(payload["logs_total"], 1)
        self.assertTrue(payload["auto_cleanup"])
        self.assertEqual(self.messages(), ["expired"])
        self.assertIsNone(self.last_run())

    def test_existing_database_gets_schedule_column_without_losing_settings(self):
        import database.session as database_session

        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE app_settings DROP COLUMN logs_last_cleanup_at"))
            connection.execute(text("UPDATE app_settings SET smtp = '{\"host\":\"keep.example.test\"}'"))

        with patch.object(database_session, "engine", self.engine), patch.object(
            database_session, "DATA_DIR", Path(self.directory.name)
        ):
            database_session.init_db()
            database_session.init_db()

        self.assertIn("logs_last_cleanup_at", {column["name"] for column in inspect(self.engine).get_columns("app_settings")})
        with self.Session() as session:
            settings = session.get(AppSetting, 1)
            self.assertTrue(settings.auto_cleanup)
            self.assertEqual(settings.smtp, {"host": "keep.example.test"})
            self.assertIsNone(settings.logs_last_cleanup_at)


class LogCleanupSchedulerTests(unittest.TestCase):
    def test_loop_continues_after_failure(self):
        import runtime.log_cleanup as scheduler

        stop_event = Mock()
        stop_event.is_set.side_effect = [False, False, True]
        with patch.object(scheduler, "run_daily_log_cleanup", side_effect=[RuntimeError("busy"), 0]) as cleanup, patch.object(
            scheduler, "_logger"
        ) as logger:
            scheduler._cleanup_loop(stop_event)

        self.assertEqual(cleanup.call_count, 2)
        logger.exception.assert_called_once()
        self.assertEqual(stop_event.wait.call_count, 2)
        stop_event.wait.assert_called_with(60)

    def test_starting_scheduler_twice_keeps_one_background_thread(self):
        import runtime.log_cleanup as scheduler

        with patch.object(scheduler, "_scheduler_thread", None), patch.object(scheduler.threading, "Thread") as thread:
            thread.return_value.is_alive.return_value = True
            scheduler.start_log_cleanup_scheduler()
            scheduler.start_log_cleanup_scheduler()

        thread.assert_called_once()
        thread.return_value.start.assert_called_once()
        self.assertTrue(thread.call_args.kwargs["daemon"])

    def test_application_bootstrap_starts_cleanup_once(self):
        from services import application

        with TemporaryDirectory() as directory, ExitStack() as patches:
            patches.enter_context(patch.object(application, "_storage_initialized", False))
            for name in ("EXPORT_DIR", "FEED_DIR", "FILE_IMPORT_DIR", "PRICE_CONVERTER_DIR",
                         "ATTRIBUTE_ASSISTANT_DIR", "SCRAPE_CHECKPOINT_DIR", "PROJECT_PROFILE_DIR"):
                patches.enter_context(patch.object(application, name, Path(directory)))
            for target in (
                "services.application.init_db", "services.application.ensure_default_user",
                "services.application.run_data_migrations", "services.feeds.recover_interrupted_feed_comparison",
                "services.file_import_service.recover_interrupted_file_import_scan",
                "services.price_converter_service.recover_interrupted_price_conversion",
                "services.projects.load_projects", "services.news.load_news_settings",
                "runtime.news_tasks.start_news_scheduler",
            ):
                patches.enter_context(patch(target))
            cleanup = patches.enter_context(patch("runtime.log_cleanup.start_log_cleanup_scheduler"))

            application.ensure_storage()
            application.ensure_storage()

            cleanup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
