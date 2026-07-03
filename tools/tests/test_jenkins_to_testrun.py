from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.jenkins_artifacts import PullResult, pull_jenkins_artifacts
from ai_tools.jenkins_to_testrun import (
    campaign_name_from_build,
    find_metadata_source,
    jenkins_to_testrun,
)


class CampaignNameTests(unittest.TestCase):
    def test_derives_from_nested_job_url(self) -> None:
        url = (
            "https://jenkins.example.com/job/Gating-c-ares/job/"
            "c-ares-sanity/job/c-ares-sssd-tier0/3/"
        )
        self.assertEqual(
            campaign_name_from_build(url, 3),
            "jenkins-c-ares-sanity-c-ares-sssd-tier0-3",
        )


class FindMetadataTests(unittest.TestCase):
    def test_prefers_metadata_mod_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config" / "metadata.yaml").parent.mkdir(parents=True)
            (root / "config" / "metadata.yaml").write_text("orig\n")
            (root / "metadata.mod.yaml").write_text("mod\n")
            self.assertEqual(
                find_metadata_source(root).name,
                "metadata.mod.yaml",
            )


class PullDecompressIntegrationTests(unittest.TestCase):
    def test_pull_runs_decompress_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            gz_log = out / "logs" / "test.log.gz"
            gz_log.parent.mkdir(parents=True)
            gz_log.write_bytes(gzip.compress(b"traceback\n"))

            with patch(
                "ai_tools.jenkins_artifacts.fetch_console",
                return_value="RD_JR_ARTIFACTS_URL=https://artifacts.example.com/x/\n",
            ), patch(
                "ai_tools.jenkins_artifacts.download_artifact",
                return_value=False,
            ):
                result = pull_jenkins_artifacts(
                    build_url="https://jenkins.example.com/job/foo/3/",
                    output_dir=out,
                    get_console=True,
                    download_artifacts=False,
                    decompress_after=True,
                    auth=("u", "p"),
                )

            self.assertIsNotNone(result.decompress)
            plain = out / "logs" / "test.log"
            self.assertTrue(plain.is_file())
            self.assertEqual(plain.read_text(), "traceback\n")


class JenkinsToTestrunTests(unittest.TestCase):
    def test_creates_campaign_twd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            git_root = Path(tmp)
            pull_dir = git_root / "pull"
            pull_dir.mkdir()
            (pull_dir / "metadata.mod.yaml").write_text("domains: []\n", encoding="utf-8")
            (pull_dir / "runner.log").write_text("FAILED\n", encoding="utf-8")

            fake_pull = PullResult(
                build_url="https://jenkins.example.com/job/foo/3/",
                build_number=3,
                artifacts_url="https://artifacts.example.com/x/",
                output_dir=pull_dir,
                downloaded=["metadata.mod.yaml"],
                missing=[],
            )

            with patch(
                "ai_tools.jenkins_to_testrun.pull_jenkins_artifacts",
                return_value=fake_pull,
            ):
                result = jenkins_to_testrun(
                    build_url="https://jenkins.example.com/job/foo/3/",
                    campaign="jenkins-foo-3",
                    git_path=git_root,
                    pull_output=pull_dir,
                    keep_pull_dir=True,
                    auth=("u", "p"),
                )

            twd = git_root / "@TESTRUNS" / "jenkins-foo-3" / "twd"
            self.assertEqual(result.twd, twd)
            self.assertEqual(
                (twd / "metadata.yaml").read_text(encoding="utf-8"),
                "domains: []\n",
            )
            self.assertEqual((twd / "runner.log").read_text(encoding="utf-8"), "FAILED\n")


if __name__ == "__main__":
    unittest.main()
