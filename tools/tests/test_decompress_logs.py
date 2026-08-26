from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from ai_tools.compression import maybe_decompress
from ai_tools.decompress_logs import decompress_file, decompress_logs, output_path_for


class CompressionTests(unittest.TestCase):
    def test_maybe_decompress_plain(self) -> None:
        self.assertEqual(maybe_decompress(b"plain"), b"plain")

    def test_maybe_decompress_gzip(self) -> None:
        payload = gzip.compress(b"log line\n")
        self.assertEqual(maybe_decompress(payload), b"log line\n")


class DecompressLogsTests(unittest.TestCase):
    def test_output_path_for_log_gz(self) -> None:
        path = Path("/tmp/client1_var_log_sssd_sssd_domain-8xzw.com.log.gz")
        self.assertEqual(
            output_path_for(path),
            Path("/tmp/client1_var_log_sssd_sssd_domain-8xzw.com.log"),
        )

    def test_decompress_gzip_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "runner.log.gz"
            src.write_bytes(gzip.compress(b"runner\n"))
            result = decompress_file(src)
            dest = Path(result.dest)
            self.assertEqual(result.action, "decompressed")
            self.assertEqual(dest.read_text(), "runner\n")
            self.assertTrue(src.exists())

    def test_rename_misnamed_gz(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "messages.gz"
            src.write_text("plain syslog\n")
            result = decompress_file(src)
            dest = Path(result.dest)
            self.assertEqual(result.action, "renamed")
            self.assertEqual(dest.read_text(), "plain syslog\n")
            self.assertTrue(src.exists())

    def test_remove_source_renames_plain_gz(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "messages.gz"
            src.write_text("plain syslog\n")
            result = decompress_file(src, remove_source=True)
            dest = Path(result.dest)
            self.assertEqual(result.action, "renamed")
            self.assertFalse(src.exists())
            self.assertTrue(dest.exists())

    def test_decompress_logs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plain.log").write_text("keep\n")
            gz = root / "sssd.log.gz"
            gz.write_bytes(gzip.compress(b"sssd\n"))
            misnamed = root / "messages.gz"
            misnamed.write_text("syslog\n")

            summary = decompress_logs([root])

            self.assertEqual(summary.to_dict()["decompressed"], 1)
            self.assertEqual(summary.to_dict()["renamed"], 1)
            self.assertEqual((root / "sssd.log").read_text(), "sssd\n")
            self.assertEqual((root / "messages").read_text(), "syslog\n")
            self.assertTrue((root / "plain.log").exists())


if __name__ == "__main__":
    unittest.main()
