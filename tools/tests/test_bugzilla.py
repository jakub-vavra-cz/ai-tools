from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ai_tools.bugzilla import (
    BugRecord,
    BugzillaClient,
    BugzillaConfig,
    BugzillaError,
    config_from_env,
    format_bug,
    normalize_host,
    parse_bug_ids,
    _http_json,
)


class NormalizeHostTests(unittest.TestCase):
    def test_adds_https_scheme(self) -> None:
        self.assertEqual(
            normalize_host("bugzilla.redhat.com"),
            "https://bugzilla.redhat.com",
        )

    def test_strips_trailing_slash(self) -> None:
        self.assertEqual(
            normalize_host("https://bugzilla.redhat.com/"),
            "https://bugzilla.redhat.com",
        )


class ParseBugIdsTests(unittest.TestCase):
    def test_parses_multiple_tokens(self) -> None:
        self.assertEqual(parse_bug_ids(("1002592", "1547234,1695576")), [1002592, 1547234, 1695576])

    def test_rejects_invalid(self) -> None:
        with self.assertRaises(BugzillaError):
            parse_bug_ids(("abc",))


class ConfigFromEnvTests(unittest.TestCase):
    def test_requires_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(BugzillaError):
                config_from_env()

    def test_reads_env(self) -> None:
        env = {
            "BUGZILLA_API_TOKEN": "secret",
            "BUGZILLA_HOST": "bugzilla.example.com",
            "BUGZILLA_USERNAME": "user@example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            config = config_from_env()
        self.assertEqual(config.host, "https://bugzilla.example.com")
        self.assertEqual(config.api_token, "secret")
        self.assertEqual(config.username, "user@example.com")


class HttpJsonTests(unittest.TestCase):
    def test_raises_on_http_error(self) -> None:
        from urllib.error import HTTPError

        payload = json.dumps({"message": "not authorized"}).encode()
        error = HTTPError(
            url="https://bugzilla.example.com/rest/bug/1",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        error.read = lambda: payload
        with patch("ai_tools.bugzilla.urlopen", side_effect=error):
            with self.assertRaises(BugzillaError) as ctx:
                _http_json("https://bugzilla.example.com/rest/bug/1", api_token="t")
        self.assertIn("401", str(ctx.exception))


class BugzillaClientTests(unittest.TestCase):
    def test_get_bugs(self) -> None:
        config = BugzillaConfig(
            host="https://bugzilla.example.com",
            api_token="token",
            username="user@example.com",
        )
        response = {
            "bugs": [
                {
                    "id": 1002592,
                    "summary": "example bug",
                    "status": "CLOSED",
                    "resolution": "CURRENTRELEASE",
                    "component": "sssd",
                }
            ]
        }

        with patch("ai_tools.bugzilla._http_json", return_value=response) as mock_http:
            client = BugzillaClient(config)
            bugs = client.get_bugs([1002592])

        self.assertEqual(len(bugs), 1)
        self.assertEqual(bugs[0].id, 1002592)
        self.assertEqual(bugs[0].summary, "example bug")
        mock_http.assert_called_once()
        called_url = mock_http.call_args.args[0]
        self.assertTrue(called_url.endswith("/rest/bug"))

    def test_get_bugs_missing(self) -> None:
        config = BugzillaConfig(host="https://bugzilla.example.com", api_token="token")
        with patch("ai_tools.bugzilla._http_json", return_value={"bugs": []}):
            client = BugzillaClient(config)
            with self.assertRaises(BugzillaError):
                client.get_bugs([999])

    def test_search_requires_filter(self) -> None:
        config = BugzillaConfig(host="https://bugzilla.example.com", api_token="token")
        client = BugzillaClient(config)
        with self.assertRaises(BugzillaError):
            client.search_bugs()


class FormatBugTests(unittest.TestCase):
    def test_format_bug(self) -> None:
        bug = BugRecord(
            id=1547234,
            summary="SSSD's GPO code ignores ad_site option",
            status="CLOSED",
            resolution="CURRENTRELEASE",
            component="sssd",
            assigned_to="dev@example.com",
            url="https://bugzilla.redhat.com/show_bug.cgi?id=1547234",
        )
        text = format_bug(bug)
        self.assertIn("BZ 1547234", text)
        self.assertIn("ad_site", text)
        self.assertIn("assigned_to", text)


if __name__ == "__main__":
    unittest.main()
