"""Unit tests for oc-login-sso helpers."""

from __future__ import annotations

import unittest
from unittest import mock

from ai_tools import oc_login_sso as mod


class FetchSsoTokenTests(unittest.TestCase):
    def test_missing_dependency(self) -> None:
        with (
            mock.patch.object(
                mod,
                "_ocp_oauth_login_cls",
                side_effect=mod.OcLoginSsoError("ocp-sso-token is required"),
            ),
            self.assertRaises(mod.OcLoginSsoError) as ctx,
        ):
            mod.fetch_sso_token("https://example.invalid:6443", ("OpenID",))
        self.assertIn("ocp-sso-token is required", str(ctx.exception))

    def test_empty_token(self) -> None:
        instance = mock.Mock()
        instance.token.return_value = "  "
        cls = mock.Mock(return_value=instance)
        with (
            mock.patch.object(mod, "ensure_ca_bundle", return_value=None),
            mock.patch.object(mod, "_ocp_oauth_login_cls", return_value=cls),
            self.assertRaises(mod.OcLoginSsoError) as ctx,
        ):
            mod.fetch_sso_token("https://example.invalid:6443", ("OpenID",))
        self.assertIn("empty token", str(ctx.exception))


class LoginSsoTests(unittest.TestCase):
    def test_skips_when_already_logged_in(self) -> None:
        with (
            mock.patch.object(mod, "current_user", return_value="jvavra"),
            mock.patch.object(mod, "current_project", return_value="ns"),
            mock.patch.object(mod, "oc_set_project") as set_proj,
            mock.patch.object(mod, "fetch_sso_token") as fetch,
        ):
            out = mod.login_sso(project="ns")
        self.assertTrue(out.skipped)
        self.assertFalse(out.refreshed)
        self.assertEqual(out.user, "jvavra")
        set_proj.assert_not_called()
        fetch.assert_not_called()

    def test_switches_project_when_skipped(self) -> None:
        with (
            mock.patch.object(mod, "current_user", return_value="jvavra"),
            mock.patch.object(mod, "current_project", return_value="other"),
            mock.patch.object(mod, "oc_set_project") as set_proj,
            mock.patch.object(mod, "fetch_sso_token") as fetch,
        ):
            out = mod.login_sso(project="ns")
        self.assertTrue(out.skipped)
        set_proj.assert_called_once_with("ns")
        fetch.assert_not_called()
        self.assertEqual(out.project, "ns")

    def test_force_refreshes(self) -> None:
        with (
            mock.patch.object(mod, "current_user", side_effect=["old", "jvavra"]),
            mock.patch.object(mod, "fetch_sso_token", return_value="tok") as fetch,
            mock.patch.object(mod, "oc_login_with_token") as login,
            mock.patch.object(mod, "oc_set_project") as set_proj,
        ):
            out = mod.login_sso(force=True, project="ns")
        self.assertTrue(out.refreshed)
        self.assertFalse(out.skipped)
        fetch.assert_called_once()
        login.assert_called_once()
        set_proj.assert_called_once_with("ns")


class CliMainTests(unittest.TestCase):
    def test_quiet_success(self) -> None:
        result = mod.OcLoginResult(user="jvavra", project="ns", refreshed=True, skipped=False)
        with mock.patch.object(mod, "login_sso", return_value=result):
            code = mod.main(["--quiet"])
        self.assertEqual(code, 0)

    def test_json_success(self) -> None:
        result = mod.OcLoginResult(user="jvavra", project="ns", refreshed=False, skipped=True)
        with (
            mock.patch.object(mod, "login_sso", return_value=result),
            mock.patch("click.echo") as echo,
        ):
            code = mod.main(["--json"])
        self.assertEqual(code, 0)
        payload = echo.call_args[0][0]
        self.assertIn('"user": "jvavra"', payload)
        self.assertNotIn("api.dno", payload)
        self.assertNotIn("ocp-hub", payload)


if __name__ == "__main__":
    unittest.main()
