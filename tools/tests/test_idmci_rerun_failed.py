from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.idmci_rerun_failed import (
    append_pytest_args,
    idmci_rerun_failed,
    write_rerun_metadata,
)
from ai_tools.te_test_summary import build_pytest_k_filter

SAMPLE_METADATA = """\
domains: []
phases:
- name: prep
  steps:
  - playbook: prep/foo.yaml
- name: test
  steps:
  - pytests: src/tests/multihost/ad
    git: ../sssd
    args: -m c_ares
    ssh_transport: openssh
- name: teardown
  steps:
  - playbook: teardown/bar.yaml
"""

JUNIT_FAIL = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" failures="1" errors="0" tests="2">
    <testcase classname="ad.test_adparameters_ported.TestADParamsPorted"
              name="test_0012_ad_parameters_server_unresolvable" time="1">
      <failure message="assert">fail</failure>
    </testcase>
    <testcase classname="ad.test_adparameters_ported.TestADParamsPorted"
              name="test_0013_other" time="1"/>
  </testsuite>
</testsuites>
"""


class AppendPytestArgsTests(unittest.TestCase):
    def test_appends_to_existing_args(self) -> None:
        patched = append_pytest_args(
            SAMPLE_METADATA,
            '-k test_0012_ad_parameters_server_unresolvable',
            phase="test",
        )
        self.assertIn(
            "args: -m c_ares -k test_0012_ad_parameters_server_unresolvable",
            patched,
        )
        self.assertIn("playbook: prep/foo.yaml", patched)

    def test_inserts_args_when_missing(self) -> None:
        metadata = """\
phases:
- name: test
  steps:
  - pytests: src/tests/foo
    git: ../sssd
"""
        patched = append_pytest_args(metadata, "-k test_foo", phase="test")
        self.assertIn("args: -k test_foo", patched)


class BuildPytestKFilterTests(unittest.TestCase):
    def test_single_failure(self) -> None:
        self.assertEqual(
            build_pytest_k_filter(
                ["ad.test::TestCls::test_0012_ad_parameters_server_unresolvable"],
            ),
            "-k test_0012_ad_parameters_server_unresolvable",
        )

    def test_multiple_failures(self) -> None:
        self.assertEqual(
            build_pytest_k_filter(
                [
                    "pkg::TestCls::test_one",
                    "pkg::TestCls::test_two",
                ],
            ),
            '-k "test_one or test_two"',
        )


class IdmciRerunFailedTests(unittest.TestCase):
    def test_prepares_rerun_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = Path(tmp)
            (twd / "metadata.yaml").write_text(SAMPLE_METADATA, encoding="utf-8")
            (twd / "junit.xml").write_text(JUNIT_FAIL, encoding="utf-8")

            result = idmci_rerun_failed(twd, run_te=False)

            rerun = Path(result.rerun_metadata)
            self.assertTrue(rerun.is_file())
            text = rerun.read_text(encoding="utf-8")
            self.assertIn("test_0012_ad_parameters_server_unresolvable", text)
            self.assertIn("args: -m c_ares -k", text)

    def test_runs_te(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = Path(tmp)
            (twd / "metadata.yaml").write_text(SAMPLE_METADATA, encoding="utf-8")
            (twd / "junit.xml").write_text(JUNIT_FAIL, encoding="utf-8")

            with patch(
                "ai_tools.idmci_rerun_failed.subprocess.run",
                return_value=type("R", (), {"returncode": 0})(),
            ) as run_mock:
                result = idmci_rerun_failed(twd)

            run_mock.assert_called_once()
            self.assertEqual(result.te_rc, 0)
            self.assertEqual(run_mock.call_args.args[0][-1], "metadata.rerun.yaml")


if __name__ == "__main__":
    unittest.main()
