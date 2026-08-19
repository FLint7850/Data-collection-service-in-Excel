from pathlib import Path
import unittest
from unittest.mock import patch

from services.codex_app_server import (
    CODEX_DISABLED_FEATURES,
    CODEX_WEB_INSTRUCTIONS,
    CodexAppServerClient,
    _resolve_codex_command,
)


class FakeCodexClient(CodexAppServerClient):
    def __init__(self):
        self.workspace = Path("/attribute-assistant-empty-workspace")
        self.calls = []

    def account_status(self):
        return {"authenticated": True}

    def request(self, method, params=None, timeout=20):
        self.calls.append((method, params, timeout))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        return {}

    def event_marker(self):
        return 10

    def wait_for_event(self, method, predicate, *, after, timeout):
        completed = {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        }
        self.assert_event_arguments = (method, predicate(completed), after, timeout)
        return 12, completed

    def events_between(self, start, end):
        self.assert_event_range = (start, end)
        return [
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": '{"suggestions":[]}',
                    }
                },
            }
        ]


class FakeLoginClient(CodexAppServerClient):
    def __init__(self):
        self._login = None
        self._login_error = ""
        self.calls = []
        self.account = None

    def request(self, method, params=None, timeout=20):
        self.calls.append((method, params))
        if method == "account/read":
            return {"account": self.account}
        if method == "account/login/start":
            return {
                "loginId": "login-1",
                "verificationUrl": "https://auth.openai.com/codex/device",
                "userCode": "ABCD-EFGH",
            }
        if method == "account/logout":
            self.account = None
        return {}


class CodexAppServerTests(unittest.TestCase):
    def test_resolved_command_disables_unneeded_agent_tools(self) -> None:
        with patch("services.codex_app_server.shutil.which", return_value="C:/tools/codex.cmd"):
            command = _resolve_codex_command()

        self.assertEqual(command[:4], ["C:/tools/codex.cmd", "app-server", "--listen", "stdio://"])
        self.assertIn('web_search="live"', command)
        disabled = [command[index + 1] for index, item in enumerate(command[:-1]) if item == "--disable"]
        self.assertEqual(disabled, list(CODEX_DISABLED_FEATURES))

    def test_device_login_exposes_only_public_code_and_logout_uses_null_params(self) -> None:
        client = FakeLoginClient()

        pending = client.start_device_login()

        self.assertFalse(pending["authenticated"])
        self.assertTrue(pending["pending"])
        self.assertEqual(pending["user_code"], "ABCD-EFGH")
        self.assertNotIn("loginId", pending)

        client.logout()

        self.assertIn(("account/login/cancel", {"loginId": "login-1"}), client.calls)
        self.assertIn(("account/logout", None), client.calls)

    def test_json_turn_uses_stable_read_only_api_and_is_deleted_after_completion(self) -> None:
        client = FakeCodexClient()
        schema = {"type": "object", "properties": {"suggestions": {"type": "array"}}}

        response = client.run_json("Analyze the exact source_url", schema, allow_web=True, timeout=45)

        self.assertEqual(response, '{"suggestions":[]}')
        thread_params = next(params for method, params, _timeout in client.calls if method == "thread/start")
        self.assertEqual(thread_params["sandbox"], "read-only")
        self.assertEqual(thread_params["baseInstructions"], CODEX_WEB_INSTRUCTIONS)
        self.assertIn("follow web_access_plan", thread_params["baseInstructions"])
        self.assertIn("fallback mode", thread_params["baseInstructions"])
        self.assertNotIn("dynamicTools", thread_params)
        self.assertNotIn("environments", thread_params)
        self.assertNotIn("ephemeral", thread_params)
        turn_params = next(params for method, params, _timeout in client.calls if method == "turn/start")
        self.assertEqual(turn_params["outputSchema"], schema)
        self.assertEqual(turn_params["sandboxPolicy"], {"type": "readOnly", "networkAccess": False})
        self.assertEqual(client.assert_event_arguments, ("turn/completed", True, 10, 45))
        self.assertEqual(client.assert_event_range, (10, 12))
        self.assertIn(("thread/delete", {"threadId": "thread-1"}, 10), client.calls)


if __name__ == "__main__":
    unittest.main()
