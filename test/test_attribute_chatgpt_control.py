import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from services import attribute_chatgpt_control as control


class AttributeChatGptControlTests(unittest.TestCase):
    request_id = "a" * 32

    def setUp(self):
        self.uuid_patch = patch.object(control.uuid, "uuid4", return_value=SimpleNamespace(hex=self.request_id))
        self.sleep_patch = patch.object(control.time, "sleep")
        self.uuid_patch.start()
        self.sleep = self.sleep_patch.start()
        self.release_analysis = control._release_analysis
        self.release_patch = patch.object(control, "_release_analysis")
        self.release = self.release_patch.start()
        self.addCleanup(self.release_patch.stop)
        self.addCleanup(self.uuid_patch.stop)
        self.addCleanup(self.sleep_patch.stop)

    def state(self, status="running", **extra):
        return {"id": self.request_id, "status": status, **extra}

    def assert_one_submission(self, request):
        posts = [call for call in request.call_args_list if call.args[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].args[1], "/analyses")
        self.assertEqual(posts[0].kwargs["json_body"], {"request_id": self.request_id, "prompt": "all products"})
        for call in request.call_args_list:
            self.assertEqual(call.kwargs["timeout"], (5, 30))
            if call.args[0] == "GET":
                self.assertEqual(call.args[1], f"/analyses/{self.request_id}")

    def test_one_prompt_can_take_more_than_600_seconds(self):
        result = {"thread_id": "thread-1", "turn_id": "turn-1", "text": "one answer"}
        with patch.object(control, "bridge_request", side_effect=[
            self.state(), self.state(), self.state("completed", result=result),
        ]) as request, patch.object(control.time, "monotonic", side_effect=[0, 1, 901, 1801]):
            self.assertEqual(control.analyze_with_chatgpt("all products"), result)
        self.assert_one_submission(request)
        self.assertEqual(self.sleep.call_count, 2)
        self.release.assert_called_once_with(self.request_id)

    def test_lost_post_response_recovers_same_analysis_without_resubmitting(self):
        with patch.object(control, "bridge_request", side_effect=[
            control.BridgeTransportError("response lost"),
            self.state(),
            self.state("completed", result={"text": "recovered"}),
        ]) as request:
            self.assertEqual(control.analyze_with_chatgpt("all products"), {"text": "recovered"})
        self.assert_one_submission(request)

    def test_poll_connection_failure_does_not_repeat_prompt(self):
        with patch.object(control, "bridge_request", side_effect=[
            self.state(),
            control.BridgeTransportError("temporary disconnect"),
            self.state("completed", result={"text": "recovered"}),
        ]) as request:
            self.assertEqual(control.analyze_with_chatgpt("all products"), {"text": "recovered"})
        self.assert_one_submission(request)

    def test_failed_analysis_preserves_cause_and_is_not_restarted(self):
        with patch.object(control, "bridge_request", side_effect=[
            self.state(), self.state("failed", error="ChatGPT stopped responding"),
        ]) as request:
            with self.assertRaisesRegex(RuntimeError, "ChatGPT stopped responding"):
                control.analyze_with_chatgpt("all products")
        self.assert_one_submission(request)

    def test_lost_bridge_reports_uncertain_remote_state(self):
        with patch.object(control, "bridge_request", side_effect=[
            self.state(), control.BridgeTransportError("offline"),
        ]) as request, patch.object(control.time, "monotonic", side_effect=[0, 0, 61]):
            with self.assertRaisesRegex(RuntimeError, "могло продолжиться"):
                control.analyze_with_chatgpt("all products")
        self.assert_one_submission(request)
        self.release.assert_not_called()

    def test_received_result_is_acknowledged_without_repeating_model_request(self):
        with patch.object(control, "_release_analysis", self.release_analysis), \
                patch.object(control, "bridge_request", side_effect=[
                    self.state("completed", result={"text": "answer"}), {"ok": True},
                ]) as request:
            self.assertEqual(control.analyze_with_chatgpt("one product"), {"text": "answer"})
        self.assertEqual([call.args[0] for call in request.call_args_list], ["POST", "DELETE"])
        self.assertEqual(request.call_args_list[1].args[1], f"/analyses/{self.request_id}")
        self.assertEqual(request.call_args_list[1].kwargs["timeout"], (2, 2))

    def test_acknowledgement_failure_never_loses_received_result(self):
        with patch.object(control, "_release_analysis", self.release_analysis), \
                patch.object(control, "bridge_request", side_effect=[
                    self.state("completed", result={"text": "answer"}),
                    control.BridgeTransportError("lost acknowledgement"),
                ]) as request:
            self.assertEqual(control.analyze_with_chatgpt("one product"), {"text": "answer"})
        self.assertEqual([call.args[0] for call in request.call_args_list], ["POST", "DELETE"])

    def test_failed_analysis_is_acknowledged_without_hiding_its_error(self):
        with patch.object(control, "_release_analysis", self.release_analysis), \
                patch.object(control, "bridge_request", side_effect=[
                    self.state("failed", error="model error"),
                    control.BridgeHttpError("release failed", 503),
                ]):
            with self.assertRaisesRegex(RuntimeError, "model error"):
                control.analyze_with_chatgpt("one product")

    def test_missing_analysis_is_not_silently_restarted(self):
        with patch.object(control, "bridge_request", side_effect=[
            self.state(), control.BridgeHttpError("bridge restarted", 404),
        ]) as request:
            with self.assertRaisesRegex(RuntimeError, "bridge restarted"):
                control.analyze_with_chatgpt("all products")
        self.assert_one_submission(request)

    def test_old_bridge_requires_update_not_synchronous_fallback(self):
        with patch.object(control, "bridge_request", side_effect=control.BridgeHttpError("not found", 404)) as request:
            with self.assertRaisesRegex(RuntimeError, "parser и attribute-ai"):
                control.analyze_with_chatgpt("all products")
        self.assert_one_submission(request)

    def test_result_from_another_job_is_rejected(self):
        with patch.object(control, "bridge_request", return_value={"id": "wrong", "status": "completed", "result": {"text": "wrong"}}):
            with self.assertRaisesRegex(RuntimeError, "другой операции"):
                control.analyze_with_chatgpt("all products")

    def test_http_session_is_closed_and_does_not_use_parser_proxy(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.request.return_value.ok = True
        session.request.return_value.json.return_value = {"ok": True}
        with patch.object(control.requests, "Session", return_value=session):
            self.assertEqual(control.bridge_request("GET", "/health"), {"ok": True})
        self.assertFalse(session.trust_env)
        session.__exit__.assert_called_once()

    def test_read_timeout_is_a_transport_error_not_an_analysis_failure(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.request.side_effect = requests.ReadTimeout("test timeout")
        with patch.object(control.requests, "Session", return_value=session):
            with self.assertRaises(control.BridgeTransportError):
                control.bridge_request("GET", "/health")
        session.__exit__.assert_called_once()
