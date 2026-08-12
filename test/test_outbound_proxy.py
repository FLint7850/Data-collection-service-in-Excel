import os
import unittest
from unittest.mock import patch

import requests

from services.outbound_proxy import (
    OutboundProxyConfigurationError,
    configured_outbound_proxy,
    is_internal_url,
    outbound_requests_session,
    outbound_proxy_environment,
    redact_proxy_secrets,
)


class OutboundProxyTests(unittest.TestCase):
    proxy_url = "http://proxy-user:proxy-pass@198.51.100.10:6584"

    def proxy_environment(self):
        return patch.dict(
            os.environ,
            {
                "OUTBOUND_PROXY_URL": self.proxy_url,
                "OUTBOUND_PROXY_REQUIRED": "1",
                "OUTBOUND_PROXY_NO_PROXY": "localhost,127.0.0.1,parser,10.0.0.0/8",
            },
            clear=False,
        )

    def test_proxy_formats_keep_credentials_out_of_playwright_server(self) -> None:
        with self.proxy_environment():
            proxy = configured_outbound_proxy()

        self.assertEqual(proxy.requests()["https"], self.proxy_url)
        with self.proxy_environment():
            playwright_proxy = proxy.playwright()
        self.assertEqual(
            playwright_proxy,
            {
                "server": "http://198.51.100.10:6584",
                "bypass": "localhost,127.0.0.1,parser,10.0.0.0/8",
                "username": "proxy-user",
                "password": "proxy-pass",
            },
        )

    def test_internal_addresses_bypass_but_public_hosts_do_not(self) -> None:
        with self.proxy_environment():
            self.assertTrue(is_internal_url("http://parser:5000/api/health"))
            self.assertTrue(is_internal_url("http://127.0.0.1:5000"))
            self.assertTrue(is_internal_url("http://10.20.30.40/private"))
            self.assertFalse(is_internal_url("https://example.com"))

    def test_requests_session_ignores_ambient_vpn_proxy(self) -> None:
        with self.proxy_environment():
            session = outbound_requests_session()

        self.assertFalse(session.trust_env)

    def test_requests_session_routes_external_and_internal_per_request(self) -> None:
        session = outbound_requests_session()
        captured = []

        def fake_request(_session, method, url, **kwargs):
            captured.append((method, url, kwargs.get("proxies")))
            return object()

        with (
            self.proxy_environment(),
            patch("requests.Session.request", new=fake_request),
        ):
            session.get("https://example.com")
            session.get("http://parser:5000/api/health")

        self.assertEqual(captured[0][2], {"http": self.proxy_url, "https": self.proxy_url})
        self.assertEqual(captured[1][2], {})

    def test_child_environment_does_not_mutate_parent_and_keeps_internal_bypass(self) -> None:
        parent = {"HTTPS_PROXY": "http://old-proxy", "UNRELATED": "kept"}
        with self.proxy_environment():
            child = outbound_proxy_environment(parent)

        self.assertEqual(parent["HTTPS_PROXY"], "http://old-proxy")
        self.assertEqual(child["HTTPS_PROXY"], self.proxy_url)
        self.assertEqual(child["UNRELATED"], "kept")
        self.assertIn("parser", child["NO_PROXY"])

    def test_required_proxy_fails_closed_and_never_echoes_secret(self) -> None:
        with patch.dict(
            os.environ,
            {"OUTBOUND_PROXY_URL": "", "OUTBOUND_PROXY_REQUIRED": "1"},
            clear=False,
        ):
            with self.assertRaises(OutboundProxyConfigurationError):
                configured_outbound_proxy()

        with self.proxy_environment():
            redacted = redact_proxy_secrets("failed " + self.proxy_url + " proxy-pass")
        self.assertNotIn("proxy-pass", redacted)
        self.assertNotIn("proxy-user", redacted)

    def test_log_service_redacts_proxy_credentials(self) -> None:
        from services.log_service import log_fetch_exception

        with (
            self.proxy_environment(),
            patch("services.log_service.fetch_debug_log") as fetch_debug_log,
        ):
            log_fetch_exception(
                "requests",
                "https://example.com",
                RuntimeError("cannot connect through " + self.proxy_url),
            )

        message = fetch_debug_log.call_args.args[0]
        self.assertNotIn("proxy-user", message)
        self.assertNotIn("proxy-pass", message)

    def test_requests_error_does_not_expose_proxy_credentials(self) -> None:
        session = outbound_requests_session()

        def fail_request(_session, _method, _url, **_kwargs):
            raise requests.exceptions.ProxyError("failed through " + self.proxy_url)

        with (
            self.proxy_environment(),
            patch("requests.Session.request", new=fail_request),
            self.assertRaises(requests.exceptions.ProxyError) as raised,
        ):
            session.get("https://example.com")

        self.assertNotIn("proxy-user", str(raised.exception))
        self.assertNotIn("proxy-pass", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
