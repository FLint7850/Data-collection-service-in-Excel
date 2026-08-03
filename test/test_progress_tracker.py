import unittest

from api_dto import news_monitor_dto, news_monitor_state_dto
from progress_tracker import ProgressTracker
from query_utils import normalize_search_text


class ProgressTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = ProgressTracker(journal_limit=128)
        self.project = {
            "id": "1",
            "name": "Demo",
            "state": {"status": "idle", "percent": 0},
        }

    def test_cursor_from_initial_snapshot_has_no_immediate_delta(self) -> None:
        cursor = self.tracker.synchronize(
            "projects",
            [self.project],
            initialize=True,
        )

        self.assertEqual(
            self.tracker.delta(cursor, ["projects"]),
            {"cursor": cursor},
        )

    def test_state_changes_are_small_and_collapsed(self) -> None:
        cursor = self.tracker.synchronize(
            "projects",
            [self.project],
            initialize=True,
        )
        self.tracker.publish(
            "projects",
            {
                **self.project,
                "state": {"status": "running", "percent": 10},
            },
        )
        self.tracker.publish(
            "projects",
            {
                **self.project,
                "state": {"status": "running", "percent": 20},
            },
        )

        payload = self.tracker.delta(cursor, ["projects"])

        self.assertIsNotNone(payload)
        self.assertEqual(
            payload["projects"],
            [
                {
                    "id": "1",
                    "state": {"status": "running", "percent": 20},
                }
            ],
        )
        self.assertNotIn("upsert_projects", payload)

    def test_upserts_and_removals_are_reported(self) -> None:
        cursor = self.tracker.synchronize(
            "news",
            [{"id": "1", "brand": "Bora", "state": {"status": "idle"}}],
            initialize=True,
        )
        self.tracker.publish(
            "news",
            {"id": "2", "brand": "Beko", "state": {"status": "idle"}},
        )
        self.tracker.remove("news", "1")

        payload = self.tracker.delta(cursor, ["news"])

        self.assertEqual([item["id"] for item in payload["upsert_news"]], ["2"])
        self.assertEqual(payload["removed_news_ids"], ["1"])

    def test_unknown_cursor_requests_a_full_snapshot(self) -> None:
        self.tracker.synchronize(
            "projects",
            [self.project],
            initialize=True,
        )

        self.assertIsNone(self.tracker.delta("legacy-hash", ["projects"]))


class ApiDtoTests(unittest.TestCase):
    def test_news_dto_never_exposes_large_internal_collections(self) -> None:
        source = {
            "id": "1",
            "brand": "Bora",
            "group": "Маржа",
            "state": {"status": "idle"},
            "seen_models": ["A", "B"],
            "known_new_products": {"A": True},
            "worker_thread": object(),
        }

        detailed = news_monitor_dto(source, include_details=True)
        summary = news_monitor_dto(source, include_details=False)

        for payload in (detailed, summary):
            self.assertNotIn("seen_models", payload)
            self.assertNotIn("known_new_products", payload)
            self.assertNotIn("worker_thread", payload)

    def test_public_news_payload_does_not_walk_internal_model_collections(self) -> None:
        from services.news import public_news_monitor

        class InternalOnlyList(list):
            def __iter__(self):
                raise AssertionError("Internal model history must not be serialized")

        payload = public_news_monitor(
            {
                "id": "1",
                "brand": "Bora",
                "group": "Маржа",
                "site_url": "https://example.test",
                "start_urls": [],
                "enabled": True,
                "state": {"status": "idle"},
                "seen_models": InternalOnlyList(["A"]),
                "known_new_products": {"A": True},
            },
            include_details=False,
        )

        self.assertEqual(payload["id"], "1")
        self.assertNotIn("seen_models", payload)
        self.assertNotIn("known_new_products", payload)

    def test_search_normalization_is_case_insensitive(self) -> None:
        self.assertEqual(normalize_search_text("  BEKO  "), "beko")
        self.assertEqual(normalize_search_text("БОРК"), "борк")

    def test_workspace_state_keeps_card_data_but_omits_modal_diagnostics(self) -> None:
        state = {
            "status": "running",
            "percent": 25,
            "error": "",
            "new_count": 4,
            "missing_by_feed": [{"source": "feed", "count": 4}],
            "active_urls": ["https://example.test/product"],
            "currenturl": "https://example.test/product",
            "started_at": "2026-07-31T12:00:00+03:00",
        }

        summary = news_monitor_state_dto(state, include_details=False)

        self.assertEqual(summary["new_count"], 4)
        self.assertIn("missing_by_feed", summary)
        self.assertNotIn("active_urls", summary)
        self.assertNotIn("currenturl", summary)
        self.assertNotIn("started_at", summary)


if __name__ == "__main__":
    unittest.main()
