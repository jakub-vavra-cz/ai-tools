from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.check_ansible import (
    CheckReport,
    CommandResult,
    DEFAULT_EXTRA_ANSIBLE_PIN,
    find_ansible_root,
    format_report,
    has_deprecation_warning,
    is_playbook,
    project_uses_ansible_lint,
    relative_to_root,
    resolve_paths,
    resolve_uvx_pins,
    uvx_ansible_lint_argv,
    uvx_ansible_playbook_argv,
)


class HasDeprecationWarningTests(unittest.TestCase):
    def test_detects_bracketed(self) -> None:
        msg = "[DEPRECATION WARNING]: foo is deprecated"
        self.assertTrue(has_deprecation_warning(msg))

    def test_detects_plain(self) -> None:
        msg = "DEPRECATION WARNING something"
        self.assertTrue(has_deprecation_warning(msg))

    def test_clean_output(self) -> None:
        self.assertFalse(has_deprecation_warning("playbook syntax check ok"))


class FindAnsibleRootTests(unittest.TestCase):
    def test_finds_ansible_cfg_in_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src" / "ansible"
            tasks = root / "roles" / "facts" / "tasks"
            tasks.mkdir(parents=True)
            (root / "ansible.cfg").write_text(
                "[defaults]\n",
                encoding="utf-8",
            )
            target = tasks / "RedHat.yml"
            target.write_text("---\n- name: x\n", encoding="utf-8")
            self.assertEqual(find_ansible_root(target), root.resolve())

    def test_finds_nested_src_ansible_from_repo_root_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            ansible = repo / "src" / "ansible"
            ansible.mkdir(parents=True)
            (ansible / "ansible.cfg").write_text(
                "[defaults]\n",
                encoding="utf-8",
            )
            # Walk finds nested src/ansible/ansible.cfg.
            play = ansible / "play.yml"
            play.write_text("- hosts: all\n", encoding="utf-8")
            self.assertEqual(find_ansible_root(play), ansible.resolve())

    def test_finds_dot_ansible_lint_at_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".ansible-lint").write_text(
                "skip_list: []\n",
                encoding="utf-8",
            )
            nested = repo / "src" / "ansible" / "roles" / "x" / "tasks"
            nested.mkdir(parents=True)
            target = nested / "main.yml"
            target.write_text("---\n", encoding="utf-8")
            # Without ansible.cfg under src/ansible, .ansible-lint at repo wins
            # when walking from nested (parents include repo).
            self.assertEqual(find_ansible_root(target), repo.resolve())


class ProjectUsesAnsibleLintTests(unittest.TestCase):
    def test_detects_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ansible-lint").write_text(
                "skip_list: []\n",
                encoding="utf-8",
            )
            self.assertTrue(project_uses_ansible_lint(root))

    def test_detects_pre_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                "- id: ansible-lint\n",
                encoding="utf-8",
            )
            self.assertTrue(project_uses_ansible_lint(root))

    def test_false_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(project_uses_ansible_lint(Path(tmp)))


class IsPlaybookTests(unittest.TestCase):
    def test_hosts_play(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "play.yml"
            path.write_text(
                "---\n- hosts: localhost\n  tasks: []\n",
                encoding="utf-8",
            )
            self.assertTrue(is_playbook(path))

    def test_role_tasks_not_playbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "RedHat.yml"
            path.write_text(
                "---\n- name: Set facts\n  set_fact:\n    x: true\n",
                encoding="utf-8",
            )
            self.assertFalse(is_playbook(path))

    def test_import_playbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site.yml"
            path.write_text(
                "---\n- import_playbook: a.yml\n",
                encoding="utf-8",
            )
            self.assertTrue(is_playbook(path))


class ResolvePathsTests(unittest.TestCase):
    def test_rejects_missing(self) -> None:
        with self.assertRaises(FileNotFoundError):
            resolve_paths([Path("/no/such/file.yml")])

    def test_rejects_non_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.txt"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_paths([path])


class RelativeToRootTests(unittest.TestCase):
    def test_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "roles" / "a.yml"
            child.parent.mkdir()
            child.write_text("---\n", encoding="utf-8")
            self.assertEqual(relative_to_root(child, root), "roles/a.yml")


class UvxArgvTests(unittest.TestCase):
    def test_playbook_argv(self) -> None:
        argv = uvx_ansible_playbook_argv(python="3.12", ansible_pin="9.13.0")
        self.assertEqual(argv[0], "uvx")
        self.assertIn("ansible==9.13.0", argv)
        self.assertEqual(argv[-1], "ansible-playbook")

    def test_lint_argv(self) -> None:
        argv = uvx_ansible_lint_argv()
        self.assertEqual(argv[-1], "ansible-lint")


class ResolveUvxPinsTests(unittest.TestCase):
    def test_default_includes_idmci_extra(self) -> None:
        pins = resolve_uvx_pins()
        self.assertEqual(len(pins), 2)
        self.assertEqual(pins[0].label, "uvx")
        self.assertEqual(pins[0].ansible_pin, "9.13.0")
        self.assertEqual(pins[1].label, f"uvx-{DEFAULT_EXTRA_ANSIBLE_PIN}")
        self.assertEqual(pins[1].ansible_pin, DEFAULT_EXTRA_ANSIBLE_PIN)
        self.assertEqual(pins[1].python, "3.12")

    def test_skip_extra(self) -> None:
        pins = resolve_uvx_pins(include_extra=False)
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0].label, "uvx")

    def test_dedupes_when_extra_matches_primary(self) -> None:
        pins = resolve_uvx_pins(
            ansible_pin="8.7.0",
            extra_ansible_pin="8.7.0",
            python="3.12",
            extra_python="3.12",
        )
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0].ansible_pin, "8.7.0")


class CommandResultOkTests(unittest.TestCase):
    def test_fail_on_deprecation_even_if_exit_zero(self) -> None:
        result = CommandResult(
            name="syntax-check",
            stack="system",
            argv=["ansible-playbook"],
            cwd="/tmp",
            exit_code=0,
            output="[DEPRECATION WARNING]: bare variables\n",
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.has_deprecation)

    def test_skipped_is_ok(self) -> None:
        result = CommandResult(
            name="yamllint",
            stack="system",
            argv=[],
            cwd="/tmp",
            exit_code=0,
            output="",
            skipped=True,
            skip_reason="missing",
        )
        self.assertTrue(result.ok)


class FormatReportTests(unittest.TestCase):
    def test_includes_overall(self) -> None:
        report = CheckReport(
            ansible_root="/tmp/ansible",
            paths=["roles/x.yml"],
            uses_ansible_lint=True,
            results=[
                CommandResult(
                    name="yamllint",
                    stack="system",
                    argv=["yamllint"],
                    cwd="/tmp",
                    exit_code=0,
                    output="",
                ),
            ],
        )
        text = format_report(report, quiet=True)
        self.assertIn("overall: PASS", text)
        self.assertIn("[PASS] yamllint (system)", text)


class CheckAnsibleIntegrationTests(unittest.TestCase):
    """Smoke-test orchestration with subprocess mocked out."""

    def test_runs_yamllint_and_deprecations_for_role_tasks(self) -> None:
        from ai_tools import check_ansible as mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansible"
            tasks = root / "roles" / "facts" / "tasks"
            tasks.mkdir(parents=True)
            (root / "ansible.cfg").write_text(
                "[defaults]\n",
                encoding="utf-8",
            )
            (Path(tmp) / ".ansible-lint").write_text(
                "skip_list: []\n",
                encoding="utf-8",
            )
            target = tasks / "RedHat.yml"
            target.write_text(
                "---\n- name: Set facts\n  set_fact:\n    x: true\n",
                encoding="utf-8",
            )

            def fake_run(name, stack, argv, **kwargs):
                return CommandResult(
                    name=name,
                    stack=stack,
                    argv=argv,
                    cwd=str(kwargs.get("cwd", root)),
                    exit_code=0,
                    output="ok\n",
                    skipped=kwargs.get("skipped", False),
                    skip_reason=kwargs.get("skip_reason"),
                )

            with (
                patch.object(mod, "run_command", side_effect=fake_run),
                patch.object(mod, "which", return_value="/bin/fake"),
                patch.object(
                    mod,
                    "capture_version",
                    return_value="ansible 2.16",
                ),
            ):
                report = mod.check_ansible(
                    [target],
                    ansible_root=root,
                    skip_uvx=True,
                )

            names = [(r.name, r.stack) for r in report.results]
            self.assertIn(("yamllint", "system"), names)
            self.assertIn(("ansible-lint", "system"), names)
            self.assertIn(("ansible-lint-deprecations", "system"), names)
            # Role tasks are not playbooks → no syntax-check
            self.assertNotIn("syntax-check", {n for n, _ in names})
            self.assertTrue(report.ok)

    def test_runs_extra_uvx_pin_when_enabled(self) -> None:
        from ai_tools import check_ansible as mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansible"
            root.mkdir(parents=True)
            (root / "ansible.cfg").write_text(
                "[defaults]\n",
                encoding="utf-8",
            )
            target = root / "play.yml"
            target.write_text(
                "---\n- hosts: localhost\n  tasks: []\n",
                encoding="utf-8",
            )

            seen_argv: list[list[str]] = []

            def fake_run(name, stack, argv, **kwargs):
                if argv:
                    seen_argv.append(list(argv))
                return CommandResult(
                    name=name,
                    stack=stack,
                    argv=argv,
                    cwd=str(kwargs.get("cwd", root)),
                    exit_code=0,
                    output="ok\n",
                    skipped=kwargs.get("skipped", False),
                    skip_reason=kwargs.get("skip_reason"),
                )

            with (
                patch.object(mod, "run_command", side_effect=fake_run),
                patch.object(mod, "which", return_value="/bin/fake"),
                patch.object(
                    mod,
                    "capture_version",
                    return_value="ansible 2.16",
                ),
            ):
                report = mod.check_ansible(
                    [target],
                    ansible_root=root,
                    skip_ansible_lint=True,
                )

            stacks = {r.stack for r in report.results if r.name == "syntax-check"}
            self.assertIn("system", stacks)
            self.assertIn("uvx", stacks)
            self.assertIn(f"uvx-{DEFAULT_EXTRA_ANSIBLE_PIN}", stacks)
            joined = " ".join(" ".join(a) for a in seen_argv)
            self.assertIn("ansible==9.13.0", joined)
            self.assertIn(f"ansible=={DEFAULT_EXTRA_ANSIBLE_PIN}", joined)
            self.assertTrue(report.ok)


if __name__ == "__main__":
    unittest.main()
