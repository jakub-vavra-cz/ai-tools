from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.brew_fetch_nvr import (
    BrewFetchError,
    DEFAULT_BREWROOT,
    fetch_nvr,
    is_debug_rpm,
    list_hrefs,
    nvr_dir_url,
    rpm_names_from_listing,
    select_arch_dirs,
)
from ai_tools.nvr import parse_nvr


NVR_HTML = """
<html><body>
<a href="../">Parent Directory</a>
<a href="x86_64/">x86_64/</a>
<a href="noarch/">noarch/</a>
<a href="src/">src/</a>
<a href="data/">data/</a>
</body></html>
"""

ARCH_HTML = """
<html><body>
<a href="sudo-1.9.17-5.p2.el10_2.x86_64.rpm">sudo</a>
<a href="sudo-python-plugin-1.9.17-5.p2.el10_2.x86_64.rpm">plugin</a>
<a href="sudo-debuginfo-1.9.17-5.p2.el10_2.x86_64.rpm">dbg</a>
<a href="sudo-debugsource-1.9.17-5.p2.el10_2.x86_64.rpm">src</a>
</body></html>
"""

NOARCH_HTML = """
<html><body>
<a href="sudo-foo-1.9.17-5.p2.el10_2.noarch.rpm">foo</a>
</body></html>
"""


class ListingTests(unittest.TestCase):
    def test_hrefs_and_arch_filter(self) -> None:
        entries = list_hrefs(NVR_HTML)
        self.assertIn("x86_64/", entries)
        self.assertIn("src/", entries)
        dirs = select_arch_dirs(entries, ["x86_64"])
        self.assertEqual(dirs, ["x86_64", "noarch"])
        self.assertNotIn("src", dirs)
        self.assertNotIn("data", dirs)

    def test_absolute_hrefs(self) -> None:
        html = '<a href="/brewroot/packages/sudo/1.9.17/5.p2.el10_2/x86_64/">x86_64</a>'
        self.assertEqual(list_hrefs(html), ["x86_64/"])

    def test_skips_debug_rpms(self) -> None:
        keep, skipped = rpm_names_from_listing(list_hrefs(ARCH_HTML))
        self.assertEqual(
            keep,
            [
                "sudo-1.9.17-5.p2.el10_2.x86_64.rpm",
                "sudo-python-plugin-1.9.17-5.p2.el10_2.x86_64.rpm",
            ],
        )
        self.assertTrue(any("debuginfo" in name for name in skipped))
        self.assertTrue(is_debug_rpm("sudo-debugsource-1.rpm"))

    def test_nvr_url(self) -> None:
        nvr = parse_nvr("sudo-1.9.17-5.p2.el10_2")
        url = nvr_dir_url(nvr, DEFAULT_BREWROOT)
        self.assertTrue(url.endswith("/sudo/1.9.17/5.p2.el10_2/"))
        self.assertTrue(url.startswith(DEFAULT_BREWROOT))


class FetchTests(unittest.TestCase):
    def test_downloads_arch_and_noarch(self) -> None:
        payloads = {
            "root": NVR_HTML.encode(),
            "x86_64": ARCH_HTML.encode(),
            "noarch": NOARCH_HTML.encode(),
            "rpm": b"rpm-bytes",
        }

        def fake_fetch(url: str, *, ca_bundle=None, timeout=120):
            if url.endswith("/x86_64/") or url.endswith("/x86_64"):
                return payloads["x86_64"]
            if url.endswith("/noarch/") or url.endswith("/noarch"):
                return payloads["noarch"]
            if url.endswith(".rpm"):
                return payloads["rpm"]
            if url.rstrip("/").endswith("5.p2.el10_2"):
                return payloads["root"]
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "brew-rpms"
            with patch("ai_tools.brew_fetch_nvr.fetch_bytes", side_effect=fake_fetch):
                result = fetch_nvr(
                    "sudo-1.9.17-5.p2.el10_2",
                    dest=dest,
                    arches=["x86_64"],
                    base_url="https://example.test/brewroot/packages",
                )
            self.assertEqual(result.arches, ["x86_64", "noarch"])
            self.assertIn("sudo-1.9.17-5.p2.el10_2.x86_64.rpm", result.downloaded)
            self.assertIn("sudo-foo-1.9.17-5.p2.el10_2.noarch.rpm", result.downloaded)
            self.assertTrue(any("debuginfo" in name for name in result.skipped))
            self.assertTrue(
                (dest / "sudo-1.9.17-5.p2.el10_2.x86_64.rpm").read_bytes() == b"rpm-bytes"
            )

    def test_missing_arch_dirs(self) -> None:
        with patch(
            "ai_tools.brew_fetch_nvr.fetch_bytes",
            return_value=b'<a href="src/">src/</a>',
        ):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(BrewFetchError):
                    fetch_nvr("sudo-1.9.17-5.p2.el10_2", dest=Path(tmp), arches=["x86_64"])


if __name__ == "__main__":
    unittest.main()
