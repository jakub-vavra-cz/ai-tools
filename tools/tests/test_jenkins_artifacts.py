from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.jenkins_artifacts import (
    DEFAULT_ARTIFACT_PATHS,
    download_artifact,
    extract_artifacts_url,
    normalize_artifacts_url,
    parse_build_url,
    pull_jenkins_artifacts,
)


class ParseBuildUrlTests(unittest.TestCase):
    def test_parses_nested_job_url(self) -> None:
        url = (
            "https://jenkins.example.com/job/Projects/job/sssd/job/tier1/42/"
        )
        build = parse_build_url(url)
        self.assertEqual(build.build_number, 42)
        self.assertEqual(
            build.build_url,
            "https://jenkins.example.com/job/Projects/job/sssd/job/tier1/42/",
        )

    def test_rejects_non_numeric_build(self) -> None:
        with self.assertRaises(ValueError):
            parse_build_url("https://jenkins.example.com/job/foo/latest/")


class ExtractArtifactsUrlTests(unittest.TestCase):
    def test_prefers_last_rd_jr_artifacts_url(self) -> None:
        console = """
RD_JR_ARTIFACTS_URL=https://artifacts.example.com/old/
some log line
RD_JR_ARTIFACTS_URL=https://artifacts.example.com/new/path/
"""
        self.assertEqual(
            extract_artifacts_url(console),
            "https://artifacts.example.com/new/path/",
        )

    def test_falls_back_to_artifacts_url_line(self) -> None:
        console = "Artifacts url: https://artifacts.example.com/fallback/3/\n"
        self.assertEqual(
            extract_artifacts_url(console),
            "https://artifacts.example.com/fallback/3/",
        )

    def test_returns_none_when_missing(self) -> None:
        self.assertIsNone(extract_artifacts_url("no artifacts here"))


class DownloadArtifactTests(unittest.TestCase):
    def test_downloads_plain_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "runner.log"
            payload = b"phase test failed\n"

            def fake_fetch(url: str, **kwargs) -> bytes | None:
                if url.endswith("runner.log"):
                    return payload
                if url.endswith("runner.log.gz"):
                    return None
                return None

            with patch("ai_tools.jenkins_artifacts.fetch_bytes", side_effect=fake_fetch):
                ok = download_artifact(
                    "https://artifacts.example.com/job/1/",
                    "runner.log",
                    dest,
                )

            self.assertTrue(ok)
            self.assertEqual(dest.read_bytes(), payload)

    def test_decompresses_gzip_at_plain_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "metadata.mod.yaml"
            plain = b"domains: []\n"
            gz = gzip.compress(plain)

            def fake_fetch(url: str, **kwargs) -> bytes | None:
                if url.endswith("metadata.mod.yaml"):
                    return gz
                return None

            with patch("ai_tools.jenkins_artifacts.fetch_bytes", side_effect=fake_fetch):
                ok = download_artifact(
                    "https://artifacts.example.com/job/1/",
                    "metadata.mod.yaml",
                    dest,
                )

            self.assertTrue(ok)
            self.assertEqual(dest.read_bytes(), plain)

    def test_decompresses_gzip_suffix_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "pytest-run.rc"
            plain = b"1"
            gz = gzip.compress(plain)

            def fake_fetch(url: str, **kwargs) -> bytes | None:
                if url.endswith("pytest-run.rc"):
                    return None
                if url.endswith("pytest-run.rc.gz"):
                    return gz
                return None

            with patch("ai_tools.jenkins_artifacts.fetch_bytes", side_effect=fake_fetch):
                ok = download_artifact(
                    "https://artifacts.example.com/job/1/",
                    "pytest-run.rc",
                    dest,
                )

            self.assertTrue(ok)
            self.assertEqual(dest.read_bytes(), plain)


class PullJenkinsArtifactsTests(unittest.TestCase):
    def test_pull_writes_console_and_downloads_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            console = (
                "RD_JR_ARTIFACTS_URL=https://artifacts.example.com/run/3/\n"
            )

            def fake_fetch_console(build, **kwargs) -> str:
                return console

            def fake_download(base, relpath, dest, **kwargs) -> bool:
                if relpath == "metadata.mod.yaml":
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text("domains: []\n", encoding="utf-8")
                    return True
                return False

            with patch(
                "ai_tools.jenkins_artifacts.fetch_console",
                side_effect=fake_fetch_console,
            ), patch(
                "ai_tools.jenkins_artifacts.download_artifact",
                side_effect=fake_download,
            ):
                result = pull_jenkins_artifacts(
                    build_url="https://jenkins.example.com/job/foo/3/",
                    output_dir=out,
                    auth=("user", "token"),
                )

            self.assertEqual(result.build_number, 3)
            self.assertEqual(
                result.artifacts_url,
                "https://artifacts.example.com/run/3/",
            )
            self.assertTrue((out / "console.txt").exists())
            self.assertTrue((out / "artifacts_url.txt").exists())
            self.assertIn("metadata.mod.yaml", result.downloaded)
            self.assertIn("runner.log", result.missing)

    def test_artifacts_url_only_skips_console(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)

            with patch(
                "ai_tools.jenkins_artifacts.download_artifact",
                return_value=False,
            ) as download_mock:
                result = pull_jenkins_artifacts(
                    artifacts_url="https://artifacts.example.com/direct/",
                    output_dir=out,
                    get_console=False,
                    artifact_paths=["metadata.mod.yaml"],
                )

            download_mock.assert_called_once()
            self.assertIsNone(result.console_path)
            self.assertEqual(
                result.artifacts_url,
                "https://artifacts.example.com/direct/",
            )


class DefaultsTests(unittest.TestCase):
    def test_default_artifact_list_includes_metadata(self) -> None:
        self.assertIn("metadata.mod.yaml", DEFAULT_ARTIFACT_PATHS)
        self.assertIn("runner.log", DEFAULT_ARTIFACT_PATHS)


class NormalizeArtifactsUrlTests(unittest.TestCase):
    def test_adds_trailing_slash(self) -> None:
        self.assertEqual(
            normalize_artifacts_url("https://artifacts.example.com/x"),
            "https://artifacts.example.com/x/",
        )


if __name__ == "__main__":
    unittest.main()
