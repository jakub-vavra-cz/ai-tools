from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_tools.twd_rpm import (
    DEFAULT_HOSTS,
    HostModuleResult,
    TwdRpmError,
    ansible_cmd,
    install_rpms,
    iter_host_results,
    parse_ansible_json,
    query_rpms,
)


ANSIBLE_JSON = {
    "plays": [
        {
            "tasks": [
                {
                    "hosts": {
                        "client.test": {
                            "changed": True,
                            "rc": 0,
                            "stdout": "sudo-1.9.17-5.p2.el10_2.x86_64\n",
                            "stderr": "",
                            "failed": False,
                        }
                    }
                }
            ]
        }
    ]
}


def _twd_with_inventory(tmp: Path) -> Path:
    twd = tmp / "twd"
    twd.mkdir()
    (twd / "metadata.yaml").write_text("domains: []\n")
    config = twd / "config"
    config.mkdir()
    (config / "test.inventory.yaml").write_text("all: {}\n")
    return twd


class AnsibleHelperTests(unittest.TestCase):
    def test_default_hosts_is_client(self) -> None:
        cmd = ansible_cmd(Path("/inv"), DEFAULT_HOSTS, "shell", "rpm -q sudo")
        self.assertEqual(cmd[0], "ansible")
        self.assertIn("client", cmd)
        self.assertIn("-b", cmd)

    def test_hosts_can_be_other_groups(self) -> None:
        cmd = ansible_cmd(Path("/inv"), "ipa", "copy", "src=a dest=b", become=False)
        self.assertIn("ipa", cmd)
        self.assertNotIn("-b", cmd)
        self.assertNotIn("client", cmd)

    def test_parse_json_and_hosts(self) -> None:
        payload = parse_ansible_json("ignored\n" + json.dumps(ANSIBLE_JSON))
        results = iter_host_results(payload)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].host, "client.test")
        self.assertEqual(results[0].rc, 0)

    def test_rejects_non_json(self) -> None:
        with self.assertRaises(TwdRpmError):
            parse_ansible_json("no json here")


class QueryInstallTests(unittest.TestCase):
    def test_query_same_on_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd_with_inventory(Path(tmp))

            def runner(cmd):
                self.assertIn("client", cmd)
                self.assertIn("rpm -q", cmd[-1])
                return [
                    HostModuleResult(
                        host="client.test",
                        rc=0,
                        stdout="sudo-1.9.17-5.p2.el10_2.x86_64\n",
                    )
                ]

            result = query_rpms(
                twd,
                "sudo-1.9.17-5.p2.el10_2",
                runner=runner,
            )
            self.assertEqual(result.hosts, "client")
            self.assertEqual(result.results[0].relation, "same")
            self.assertEqual(
                result.results[0].installed,
                "sudo-1.9.17-5.p2.el10_2.x86_64",
            )

    def test_query_older_on_ipa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd_with_inventory(Path(tmp))

            def runner(cmd):
                self.assertIn("ipa", cmd)
                return [
                    HostModuleResult(
                        host="master.ipa.test",
                        rc=0,
                        stdout="sudo-1.9.16-1.el10.x86_64\n",
                    )
                ]

            result = query_rpms(
                twd,
                "sudo-1.9.17-5.p2.el10_2",
                hosts="ipa",
                runner=runner,
            )
            self.assertEqual(result.hosts, "ipa")
            self.assertEqual(result.results[0].relation, "older")

    def test_install_dry_run_uses_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd_with_inventory(Path(tmp))
            rpm_dir = twd / "brew-rpms"
            rpm_dir.mkdir()
            (rpm_dir / "sudo-1.9.17-5.p2.el10_2.x86_64.rpm").write_bytes(b"x")
            (rpm_dir / "sudo-debuginfo-1.9.17-5.p2.el10_2.x86_64.rpm").write_bytes(b"x")
            result = install_rpms(twd, hosts="dns", dry_run=True, runner=lambda cmd: [])
            self.assertEqual(result.hosts, "dns")
            self.assertEqual(result.rpms, ["sudo-1.9.17-5.p2.el10_2.x86_64.rpm"])
            self.assertEqual(len(result.argv), 2)
            self.assertIn("dns", result.argv[0])
            self.assertIn("copy", result.argv[0])
            self.assertIn("dnf install -y", result.argv[1][-1])

    def test_install_without_rpms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            twd = _twd_with_inventory(Path(tmp))
            (twd / "brew-rpms").mkdir()
            with self.assertRaises(TwdRpmError):
                install_rpms(twd, dry_run=True, runner=lambda cmd: [])


if __name__ == "__main__":
    unittest.main()
