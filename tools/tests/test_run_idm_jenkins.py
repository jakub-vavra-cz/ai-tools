from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.run_idm_jenkins import (
    DEFAULT_IDMCI_GITBRANCH,
    DEFAULT_IDMCI_GITREPO,
    DEFAULT_JENKINS_JOB,
    JENKINS_PARAM_BY_NAME,
    IdmciSource,
    JenkinsTriggerInfo,
    RunIdmJenkinsError,
    build_jenkins_parameters,
    encode_project,
    git_url_to_https,
    jenkins_job_url,
    parse_envvar_file,
    parse_param,
    parse_queue_executable,
    prepare_run,
    queue_id_from_url,
    resolve_idmci_source,
    snippet_raw_url,
    trigger_jenkins_job,
)
from ai_tools.run_idm_jenkins import main as run_main


SNIPPET_PAYLOAD = {
    "id": 4242,
    "title": "idmci-metadata-job",
    "web_url": "https://gitlab.cee.redhat.com/sssd/sssd-qe/-/snippets/4242",
    "raw_url": "https://gitlab.cee.redhat.com/sssd/sssd-qe/-/snippets/4242/raw",
    "files": [
        {
            "path": "metadata.yaml",
            "raw_url": (
                "https://gitlab.cee.redhat.com/sssd/sssd-qe/-/snippets/4242/raw/main/metadata.yaml"
            ),
        }
    ],
}


def _meta(tmp: Path, name: str = "metadata.yaml") -> Path:
    path = tmp / name
    path.write_text("domains: []\nphases: []\n")
    return path


class GitUrlTests(unittest.TestCase):
    def test_scp_ssh(self) -> None:
        url = git_url_to_https("git@gitlab.cee.redhat.com:jvavra/idm-ci.git")
        self.assertEqual(url, "https://gitlab.cee.redhat.com/jvavra/idm-ci.git")

    def test_ssh_scheme(self) -> None:
        url = git_url_to_https("ssh://git@gitlab.cee.redhat.com/jvavra/idm-ci.git")
        self.assertEqual(url, "https://gitlab.cee.redhat.com/jvavra/idm-ci.git")

    def test_https_passthrough(self) -> None:
        src = "https://gitlab.cee.redhat.com/identity-management/idm-ci.git"
        self.assertEqual(git_url_to_https(src), src)


class ParamTests(unittest.TestCase):
    def test_split_value_with_equals(self) -> None:
        key, val = parse_param("IDMCI_REPLACE_TOKEN=SUITE:--importance=high")
        self.assertEqual(key, "IDMCI_REPLACE_TOKEN")
        self.assertEqual(val, "SUITE:--importance=high")

    def test_rejects_missing_equals(self) -> None:
        with self.assertRaises(RunIdmJenkinsError):
            parse_param("NOVALUE")

    def test_encode_project(self) -> None:
        self.assertEqual(encode_project("sssd/sssd-qe"), "sssd%2Fsssd-qe")


class SnippetUrlTests(unittest.TestCase):
    def test_prefers_file_raw_url(self) -> None:
        url = snippet_raw_url(SNIPPET_PAYLOAD, host="gitlab.cee.redhat.com", repo="sssd/sssd-qe")
        self.assertTrue(url.endswith("/raw/main/metadata.yaml"))

    def test_falls_back_to_snippet_raw(self) -> None:
        url = snippet_raw_url(
            {"id": 1, "raw_url": "https://example/raw"},
            host="h",
            repo="g/p",
        )
        self.assertEqual(url, "https://example/raw")

    def test_builds_from_id(self) -> None:
        url = snippet_raw_url({"id": 9}, host="h.example", repo="g/p")
        self.assertEqual(url, "https://h.example/g/p/-/snippets/9/raw")


class JenkinsParamTests(unittest.TestCase):
    def test_maps_gitbranch_to_idmci_branch(self) -> None:
        source = IdmciSource(
            gitrepo="https://gitlab.cee.redhat.com/jvavra/idm-ci.git",
            gitbranch="fix-tree-dns",
        )
        params = build_jenkins_parameters(
            metadata_url="https://example/raw",
            source=source,
            extra={"IDMCI_REPLACE_OS": "rhel:rhel-9.6"},
        )
        self.assertEqual(params["IDMCI_METADATA_URL"], "https://example/raw")
        self.assertEqual(
            params["IDMCI_GITREPO"],
            "https://gitlab.cee.redhat.com/jvavra/idm-ci.git",
        )
        self.assertEqual(params["IDMCI_BRANCH"], "fix-tree-dns")
        self.assertNotIn("IDMCI_GITBRANCH", params)
        self.assertEqual(params["IDMCI_REPLACE_OS"], "rhel:rhel-9.6")

    def test_metadata_url_wins_over_extra(self) -> None:
        params = build_jenkins_parameters(
            metadata_url="https://real/raw",
            source=None,
            extra={"IDMCI_METADATA_URL": "https://stale/raw"},
        )
        self.assertEqual(params["IDMCI_METADATA_URL"], "https://real/raw")

    def test_known_flags_override_extra(self) -> None:
        params = build_jenkins_parameters(
            metadata_url="https://example/raw",
            source=None,
            extra={"IDMCI_PROVIDER": "openstack"},
            known={"IDMCI_PROVIDER": "aws", "IDMCI_IS_FIPS": "true"},
        )
        self.assertEqual(params["IDMCI_PROVIDER"], "aws")
        self.assertEqual(params["IDMCI_IS_FIPS"], "true")


ENVVAR_DUMP = """\
DEFAULT_IDMCI_GITBRANCH=master
DEFAULT_IDMCI_GITREPO=https://gitlab.cee.redhat.com/identity-management/idm-ci
IDMCI_GH_APP_CODE=834154
IDMCI_GATING_MESSAGING=kafka
IDMCI_METADATA_URL=https://gitlab.example/old.yaml
IDMCI_POLARION_PW=secret
IDMCI_PROVIDER=openstack
IDMCI_REPLACE_OS=rhel:rhel-10.2|client_os:rhel-10.3|windows:win-2025
IDMCI_REPLACE_TOKEN=SUITE:-k="test_gpo"|NAME:gpo
IDMCI_COMPOSE_URL=https://download.example/compose/
IDMCI_IS_FIPS=false
IDMCI_SKIP_POLARION=true
IDMCI_BRANCH=
IDMCI_GITREPO=
IDMCI_ABRT_EMAIL=
"""


class EnvvarFileTests(unittest.TestCase):
    def test_skips_secrets_empties_and_metadata_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envvar.txt"
            path.write_text(ENVVAR_DUMP)
            values = parse_envvar_file(path)
        self.assertEqual(values["IDMCI_PROVIDER"], "openstack")
        self.assertEqual(
            values["IDMCI_REPLACE_OS"],
            "rhel:rhel-10.2|client_os:rhel-10.3|windows:win-2025",
        )
        self.assertEqual(values["IDMCI_REPLACE_TOKEN"], 'SUITE:-k="test_gpo"|NAME:gpo')
        self.assertEqual(values["IDMCI_COMPOSE_URL"], "https://download.example/compose/")
        self.assertEqual(values["IDMCI_IS_FIPS"], "false")
        self.assertNotIn("IDMCI_METADATA_URL", values)
        self.assertNotIn("IDMCI_GH_APP_CODE", values)
        self.assertNotIn("IDMCI_POLARION_PW", values)
        self.assertNotIn("DEFAULT_IDMCI_GITREPO", values)
        self.assertNotIn("IDMCI_ABRT_EMAIL", values)
        self.assertNotIn("IDMCI_GITREPO", values)

    def test_catalog_covers_dump_job_params(self) -> None:
        for name in (
            "IDMCI_REPLACE_OS",
            "IDMCI_REPLACE_TOKEN",
            "IDMCI_COMPOSE_URL",
            "IDMCI_PROVIDER",
            "IDMCI_IS_FIPS",
            "IDMCI_SKIP_POLARION",
        ):
            self.assertIn(name, JENKINS_PARAM_BY_NAME)


class ResolveSourceTests(unittest.TestCase):
    def test_none_when_unset(self) -> None:
        self.assertIsNone(resolve_idmci_source(gitrepo=None, gitbranch=None, checkout=None))

    def test_fills_default_branch(self) -> None:
        source = resolve_idmci_source(
            gitrepo="https://gitlab.cee.redhat.com/jvavra/idm-ci.git",
            gitbranch=None,
            checkout=None,
        )
        assert source is not None
        self.assertEqual(source.gitbranch, DEFAULT_IDMCI_GITBRANCH)

    def test_fills_default_repo(self) -> None:
        source = resolve_idmci_source(gitrepo=None, gitbranch="topic", checkout=None)
        assert source is not None
        self.assertEqual(source.gitrepo, DEFAULT_IDMCI_GITREPO)
        self.assertEqual(source.gitbranch, "topic")

    def test_checkout_origin_and_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "idmci"
            root.mkdir()
            (root / ".git").mkdir()

            def fake_run(argv, **_kwargs):  # type: ignore[no-untyped-def]
                joined = " ".join(argv)

                class Proc:
                    stdout = ""
                    returncode = 0

                proc = Proc()
                if "remote get-url origin" in joined:
                    proc.stdout = "git@gitlab.cee.redhat.com:jvavra/idm-ci.git\n"
                elif "rev-parse --abbrev-ref HEAD" in joined:
                    proc.stdout = "fix-tree-dns\n"
                return proc

            with patch("ai_tools.run_idm_jenkins.run_cmd", side_effect=fake_run):
                source = resolve_idmci_source(gitrepo=None, gitbranch=None, checkout=root)
            assert source is not None
            self.assertEqual(
                source.gitrepo,
                "https://gitlab.cee.redhat.com/jvavra/idm-ci.git",
            )
            self.assertEqual(source.gitbranch, "fix-tree-dns")

    def test_explicit_flags_override_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "idmci"
            root.mkdir()
            (root / ".git").mkdir()

            def fake_run(_argv, **_kwargs):  # type: ignore[no-untyped-def]
                class Proc:
                    stdout = "ignored\n"
                    returncode = 0

                return Proc()

            with patch("ai_tools.run_idm_jenkins.run_cmd", side_effect=fake_run):
                source = resolve_idmci_source(
                    gitrepo="https://example/idm-ci.git",
                    gitbranch="explicit",
                    checkout=root,
                )
            assert source is not None
            self.assertEqual(source.gitrepo, "https://example/idm-ci.git")
            self.assertEqual(source.gitbranch, "explicit")


class PrepareRunTests(unittest.TestCase):
    def test_dry_run_skips_glab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(Path(tmp))
            result = prepare_run(
                meta,
                gitrepo="https://gitlab.cee.redhat.com/jvavra/idm-ci.git",
                gitbranch="topic",
                dry_run=True,
            )
            self.assertTrue(result.snippet.dry_run)
            self.assertEqual(result.jenkins_job, DEFAULT_JENKINS_JOB)
            self.assertEqual(result.idmci_gitbranch, "topic")
            self.assertEqual(result.jenkins_parameters["IDMCI_BRANCH"], "topic")
            self.assertIn("IDMCI_METADATA_URL", result.jenkins_parameters)
            self.assertTrue(result.snippet.raw_url.startswith("https://"))

    def test_empty_metadata_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.yaml"
            path.write_text("   \n")
            with self.assertRaises(RunIdmJenkinsError):
                prepare_run(path, dry_run=True)

    def test_upload_uses_file_raw_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(Path(tmp))
            with patch(
                "ai_tools.run_idm_jenkins.create_project_snippet",
                return_value=SNIPPET_PAYLOAD,
            ):
                result = prepare_run(meta)
            self.assertEqual(result.snippet.snippet_id, 4242)
            self.assertTrue(
                result.jenkins_parameters["IDMCI_METADATA_URL"].endswith("/raw/main/metadata.yaml")
            )
            self.assertFalse(result.snippet.dry_run)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._idmci_env = {
            key: os.environ.pop(key) for key in list(os.environ) if key.startswith("IDMCI_")
        }

    def tearDown(self) -> None:
        os.environ.update(self._idmci_env)

    def test_json_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(Path(tmp))
            with patch("ai_tools.run_idm_jenkins.click.echo") as echo:
                rc = run_main(
                    [
                        str(meta),
                        "-n",
                        "--json",
                        "--idmci-gitrepo",
                        "https://gitlab.cee.redhat.com/jvavra/idm-ci.git",
                        "--idmci-gitbranch",
                        "topic",
                        "--param",
                        "IDMCI_PROVIDER=aws",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(echo.call_args[0][0])
            self.assertEqual(payload["jenkins_parameters"]["IDMCI_PROVIDER"], "aws")
            self.assertEqual(payload["jenkins_parameters"]["IDMCI_BRANCH"], "topic")

    def test_named_flags_and_envvar_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(Path(tmp))
            envvar = Path(tmp) / "envvar.txt"
            envvar.write_text(ENVVAR_DUMP)
            with patch("ai_tools.run_idm_jenkins.click.echo") as echo:
                rc = run_main(
                    [
                        str(meta),
                        "-n",
                        "--json",
                        "--envvar-file",
                        str(envvar),
                        "--idmci-replace-token",
                        "SUITE:-k=override|NAME:gpo",
                        "--idmci-is-fips",
                        "true",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(echo.call_args[0][0])
            params = payload["jenkins_parameters"]
            self.assertEqual(params["IDMCI_PROVIDER"], "openstack")
            self.assertEqual(
                params["IDMCI_REPLACE_OS"],
                "rhel:rhel-10.2|client_os:rhel-10.3|windows:win-2025",
            )
            self.assertEqual(params["IDMCI_REPLACE_TOKEN"], "SUITE:-k=override|NAME:gpo")
            self.assertEqual(params["IDMCI_IS_FIPS"], "true")
            self.assertNotIn("IDMCI_GH_APP_CODE", params)
            self.assertNotEqual(params["IDMCI_METADATA_URL"], "https://gitlab.example/old.yaml")

    def test_json_contains_mapped_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(Path(tmp))
            with patch("ai_tools.run_idm_jenkins.click.echo") as echo:
                rc = run_main(
                    [
                        str(meta),
                        "-n",
                        "--json",
                        "--idmci-gitbranch",
                        "topic",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(echo.call_args[0][0])
            self.assertEqual(payload["jenkins_parameters"]["IDMCI_BRANCH"], "topic")
            self.assertEqual(payload["idmci_gitbranch"], "topic")
            self.assertEqual(
                payload["jenkins_parameters"]["IDMCI_GITREPO"],
                DEFAULT_IDMCI_GITREPO,
            )

    def test_missing_file(self) -> None:
        rc = run_main(["/no/such/metadata.yaml", "-n"])
        self.assertEqual(rc, 2)

    def test_trigger_dry_run_skips_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(Path(tmp))
            with (
                patch("ai_tools.run_idm_jenkins.click.echo") as echo,
                patch("ai_tools.run_idm_jenkins.trigger_jenkins_job") as trig,
            ):
                rc = run_main([str(meta), "-n", "--json", "--trigger"])
            self.assertEqual(rc, 0)
            trig.assert_not_called()
            payload = json.loads(echo.call_args[0][0])
            self.assertIsNone(payload.get("trigger"))
            self.assertTrue(any("trigger skipped" in note for note in payload["notes"]))

    def test_trigger_calls_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _meta(Path(tmp))
            info = JenkinsTriggerInfo(
                job=DEFAULT_JENKINS_JOB,
                queue_url="https://jenkins.example/queue/item/9/",
                queue_id=9,
                build_url="https://jenkins.example/job/User-Tools/job/trigger-test-suite-tool/12/",
                build_number=12,
            )
            with (
                patch("ai_tools.run_idm_jenkins.click.echo") as echo,
                patch(
                    "ai_tools.run_idm_jenkins.create_project_snippet",
                    return_value=SNIPPET_PAYLOAD,
                ),
                patch("ai_tools.run_idm_jenkins.trigger_jenkins_job", return_value=info) as trig,
            ):
                rc = run_main([str(meta), "--json", "--trigger", "--trigger-wait", "0"])
            self.assertEqual(rc, 0)
            trig.assert_called_once()
            payload = json.loads(echo.call_args[0][0])
            self.assertEqual(payload["trigger"]["build_number"], 12)
            args, _kwargs = trig.call_args
            self.assertEqual(args[0], DEFAULT_JENKINS_JOB)
            self.assertIn("IDMCI_METADATA_URL", args[1])


class JenkinsApiTests(unittest.TestCase):
    def test_job_url_folder(self) -> None:
        url = jenkins_job_url(
            "https://jenkins.example/",
            "User-Tools/trigger-test-suite-tool",
        )
        self.assertEqual(
            url,
            "https://jenkins.example/job/User-Tools/job/trigger-test-suite-tool",
        )

    def test_job_url_strips_job_segments(self) -> None:
        url = jenkins_job_url("https://j.example", "job/User-Tools/job/tool")
        self.assertEqual(url, "https://j.example/job/User-Tools/job/tool")

    def test_queue_id(self) -> None:
        self.assertEqual(queue_id_from_url("https://j.example/queue/item/42/"), 42)
        self.assertIsNone(queue_id_from_url("https://j.example/job/x/1/"))

    def test_parse_executable(self) -> None:
        url, number = parse_queue_executable(
            {"executable": {"url": "https://j.example/job/x/7", "number": 7}}
        )
        self.assertEqual(url, "https://j.example/job/x/7/")
        self.assertEqual(number, 7)

    def test_trigger_posts_and_polls(self) -> None:
        calls: list[str] = []

        def fake_http(url: str, **kwargs: object) -> tuple[int, dict[str, str], bytes]:
            calls.append(url)
            if "crumbIssuer" in url:
                return (
                    200,
                    {},
                    json.dumps({"crumb": "abc", "crumbRequestField": "Jenkins-Crumb"}).encode(),
                )
            if url.endswith("buildWithParameters"):
                self.assertEqual(kwargs.get("method"), "POST")
                headers = kwargs.get("headers")
                assert isinstance(headers, dict)
                self.assertEqual(headers.get("Jenkins-Crumb"), "abc")
                return 201, {"Location": "https://jenkins.example/queue/item/9"}, b""
            if "queue/item/9" in url:
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "executable": {
                                "url": "https://jenkins.example/job/User-Tools/job/tool/3/",
                                "number": 3,
                            }
                        }
                    ).encode(),
                )
            raise AssertionError(url)

        with patch("ai_tools.run_idm_jenkins.jenkins_http", side_effect=fake_http):
            info = trigger_jenkins_job(
                "User-Tools/tool",
                {"IDMCI_METADATA_URL": "https://example/raw"},
                base_url="https://jenkins.example",
                auth=("user", "token"),
                wait_seconds=5,
            )
        self.assertEqual(info.queue_id, 9)
        self.assertEqual(info.build_number, 3)
        self.assertTrue(info.build_url.endswith("/3/"))
        self.assertTrue(any(url.endswith("buildWithParameters") for url in calls))

    def test_trigger_requires_auth(self) -> None:
        with patch("ai_tools.run_idm_jenkins.jenkins_auth_from_env", return_value=None):
            with self.assertRaises(RunIdmJenkinsError):
                trigger_jenkins_job("job", {"A": "1"}, base_url="https://j.example")


if __name__ == "__main__":
    unittest.main()
