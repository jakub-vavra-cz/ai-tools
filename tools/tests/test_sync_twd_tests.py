from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_tools.nvr import NvrError, compare_evr, nvr_relation, parse_nvr, rpmvercmp
from ai_tools.sync_twd_tests import (
    SyncTwdError,
    overlay,
    resolve_dest,
    sync_twd_tests,
    test_step_paths,
)
from ai_tools.sync_twd_tests import main as sync_main


METADATA = """\
phases:
- name: test
  steps:
  - pytest-mh: ../sudo-tests/pytest/
    args: -k=regex
"""


def _campaign() -> tuple[Path, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    twd = root / "twd"
    twd.mkdir()
    (twd / "metadata.yaml").write_text(METADATA)
    (twd / "config").mkdir()
    return tmp, twd  # type: ignore[return-value]


class TestStepParseTests(unittest.TestCase):
    def test_pytest_mh_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "metadata.yaml"
            meta.write_text(METADATA)
            self.assertEqual(test_step_paths(meta), ["../sudo-tests/pytest/"])


class ResolveDestTests(unittest.TestCase):
    def test_repo_root_maps_to_sibling(self) -> None:
        tmp, twd = _campaign()
        with tmp:
            src = Path(tmp.name) / "sudoup-fork-regex_escape"
            src.mkdir()
            (src / ".git").mkdir()
            (src / "pytest").mkdir()
            dest = resolve_dest(twd, src)
            self.assertEqual(dest, (twd.parent / "sudo-tests").resolve())

    def test_pytest_dir_maps_to_test_step(self) -> None:
        tmp, twd = _campaign()
        with tmp:
            src = Path(tmp.name) / "sudoup-fork-regex_escape"
            pytest_dir = src / "pytest"
            pytest_dir.mkdir(parents=True)
            (src / ".git").mkdir()
            dest = resolve_dest(twd, pytest_dir)
            self.assertEqual(dest, (twd.parent / "sudo-tests" / "pytest").resolve())

    def test_rejects_dest_inside_twd(self) -> None:
        tmp, twd = _campaign()
        with tmp:
            src = Path(tmp.name) / "src"
            src.mkdir()
            with self.assertRaises(SyncTwdError):
                resolve_dest(twd, src, dest=twd / "logs")

    def test_campaign_root_as_twd(self) -> None:
        tmp, twd = _campaign()
        with tmp:
            src = Path(tmp.name) / "sudo-tests"
            src.mkdir()
            (src / ".git").mkdir()
            dest = resolve_dest(twd.parent, src)
            self.assertEqual(dest, (twd.parent / "sudo-tests").resolve())


class OverlayTests(unittest.TestCase):
    def test_excludes_git_and_keeps_dest_extras(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            (src / "pytest").mkdir(parents=True)
            (src / ".git").mkdir()
            (src / ".git" / "HEAD").write_text("ref\n")
            (src / "pytest" / "test_a.py").write_text("ok\n")
            dest.mkdir()
            (dest / "keep.txt").write_text("stay\n")
            copied = overlay(src, dest)
            self.assertEqual(copied, ["pytest/test_a.py"])
            self.assertTrue((dest / "pytest" / "test_a.py").is_file())
            self.assertFalse((dest / ".git").exists())
            self.assertTrue((dest / "keep.txt").is_file())

    def test_sync_json_count(self) -> None:
        tmp, twd = _campaign()
        with tmp:
            src = Path(tmp.name) / "fork"
            (src / "pytest").mkdir(parents=True)
            (src / ".git").mkdir()
            (src / "pytest" / "test_a.py").write_text("ok\n")
            result = sync_twd_tests(src, twd=twd)
            self.assertTrue((twd.parent / "sudo-tests" / "pytest" / "test_a.py").is_file())
            self.assertEqual(result.copied, ["pytest/test_a.py"])
            self.assertIn("sudo-tests", result.dest)


class NvrParseTests(unittest.TestCase):
    def test_nvr_and_nevra(self) -> None:
        nvr = parse_nvr("sudo-1.9.17-5.p2.el10_2")
        self.assertEqual((nvr.name, nvr.version, nvr.release), ("sudo", "1.9.17", "5.p2.el10_2"))
        nevra = parse_nvr("sudo-1.9.17-5.p2.el10_2.x86_64")
        self.assertEqual(nevra.nvr, "sudo-1.9.17-5.p2.el10_2")
        self.assertEqual(parse_nvr("0:sudo-1.9.17-5.p2.el10_2.x86_64").name, "sudo")

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(NvrError):
            parse_nvr("sudo")

    def test_relation(self) -> None:
        want = "sudo-1.9.17-5.p2.el10_2"
        self.assertEqual(nvr_relation("sudo-1.9.17-5.p2.el10_2.x86_64", want), "same")
        self.assertEqual(nvr_relation("sudo-1.9.16-1.el10.x86_64", want), "older")
        self.assertEqual(nvr_relation("sudo-1.9.18-1.el10.x86_64", want), "newer")
        self.assertEqual(nvr_relation("package sudo is not installed", want), "missing")
        self.assertEqual(nvr_relation(None, want), "missing")

    def test_rpmvercmp_numeric(self) -> None:
        self.assertEqual(rpmvercmp("1.9.17", "1.9.16"), 1)
        self.assertEqual(rpmvercmp("1.9.16", "1.9.17"), -1)
        self.assertEqual(rpmvercmp("5.p2.el10_2", "5.p2.el10_2"), 0)
        left = parse_nvr("sudo-1.9.17-5.p2.el10_2")
        right = parse_nvr("sudo-1.9.17-4.el10_2")
        self.assertEqual(compare_evr(left, right), 1)


class CliMainTests(unittest.TestCase):
    def test_missing_src_exits(self) -> None:
        self.assertEqual(sync_main(["--twd", "/nope", "/also-nope"]), 2)


if __name__ == "__main__":
    unittest.main()
