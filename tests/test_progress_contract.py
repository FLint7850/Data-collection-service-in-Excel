import unittest
from unittest.mock import patch

import app as application


def project(project_id: str, *, name: str = "Проект", processed: int = 0) -> dict:
    return {
        "id": project_id,
        "name": name,
        "start_urls_count": 1,
        "thread_count": 4,
        "connection_method": "requests",
        "state": {"status": "running", "processed_products": processed},
    }


def monitor(monitor_id: str, *, brand: str = "Brand", processed: int = 0) -> dict:
    return {
        "id": monitor_id,
        "brand_id": "brand-1",
        "primary_donor_id": monitor_id,
        "group": "Маржа",
        "brand": brand,
        "site_url": "https://example.com",
        "start_urls": ["https://example.com/catalog"],
        "enabled": True,
        "created_at": "2026-07-30T12:00:00+03:00",
        "state": {"status": "running", "processed": processed},
    }


class ProgressContractTests(unittest.TestCase):
    def setUp(self) -> None:
        with application.progress_cursor_lock:
            application.progress_cursor_cache.clear()

    def test_unchanged_poll_returns_only_cursor(self) -> None:
        current = project("p1")
        cursor, _ = application.register_progress_items(project_items=[current])

        with patch.object(application, "projects_progress_payload", return_value=[current]):
            payload = application.progress_payload(True, False, cursor)

        self.assertEqual(payload, {"cursor": cursor})

    def test_state_change_returns_only_id_and_state(self) -> None:
        before = project("p1", processed=1)
        cursor, _ = application.register_progress_items(project_items=[before])
        after = project("p1", processed=2)

        with patch.object(application, "projects_progress_payload", return_value=[after]):
            payload = application.progress_payload(True, False, cursor)

        self.assertEqual(
            payload["projects"],
            [{"id": "p1", "state": {"processed_products": 2}}],
        )
        self.assertNotIn("upsert_projects", payload)

    def test_summary_change_returns_full_upsert(self) -> None:
        before = project("p1", name="До")
        cursor, _ = application.register_progress_items(project_items=[before])
        after = project("p1", name="После")

        with patch.object(application, "projects_progress_payload", return_value=[after]):
            payload = application.progress_payload(True, False, cursor)

        self.assertEqual(payload["upsert_projects"], [after])
        self.assertNotIn("projects", payload)

    def test_new_and_removed_items_are_synchronized(self) -> None:
        cursor, _ = application.register_progress_items(
            project_items=[project("old")]
        )
        added = project("new")

        with patch.object(application, "projects_progress_payload", return_value=[added]):
            payload = application.progress_payload(True, False, cursor)

        self.assertEqual(payload["upsert_projects"], [added])
        self.assertEqual(payload["removed_projects_ids"], ["old"])

    def test_news_state_change_uses_same_compact_contract(self) -> None:
        before = monitor("n1", processed=3)
        cursor, _ = application.register_progress_items(news_items=[before])
        after = monitor("n1", processed=4)

        with patch.object(application, "news_progress_payload", return_value=[after]):
            payload = application.progress_payload(False, True, cursor)

        self.assertEqual(
            payload["news"],
            [{"id": "n1", "state": {"processed": 4}}],
        )
        self.assertNotIn("upsert_news", payload)

    def test_expired_cursor_requests_client_side_replacement(self) -> None:
        current = project("p1")

        with patch.object(application, "projects_progress_payload", return_value=[current]):
            payload = application.progress_payload(True, False, "expired-cursor")

        self.assertTrue(payload["replace_projects"])
        self.assertEqual(payload["upsert_projects"], [current])

    def test_monitor_details_are_not_duplicated_in_response(self) -> None:
        selected = monitor("n1")
        client = application.app.test_client()
        with client.session_transaction() as client_session:
            client_session["user_id"] = 1

        with (
            patch.object(application, "get_news_monitor", return_value=selected),
            patch.object(application, "news_settings", {"monitors": [selected]}),
        ):
            response = client.get("/api/news/monitors/n1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(set(payload), {"monitors"})
        self.assertEqual(len(payload["monitors"]), 1)
        self.assertEqual(payload["monitors"][0]["id"], "n1")


if __name__ == "__main__":
    unittest.main()
