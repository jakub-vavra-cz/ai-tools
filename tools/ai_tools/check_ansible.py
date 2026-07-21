#!/usr/bin/env python3
"""Run writing-ansible YAML/Ansible checks on system and uvx stacks."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_ANSIBLE_PIN = "9.13.0"
DEFAULT_PYTHON = "3.12"

DEPRECATION_RE = re.compile(
    r"\[DEPRECATION WARNING\]|DEPRECATION WARNING",
    re.IGNORECASE,
)

# Markers used to locate $ANSIBLE_ROOT (nearest ancestor of edited files).
ANSIBLE_ROOT_MARKERS = (
    "ansible.cfg",
    ".ansible-lint",
    ".ansible-lint.yml",
    ".yamllint",
    ".yamllint.yml",
)

PLAYBOOK_HINT_RE = re.compile(
    r"(?m)^(?:-?\s*)?(?:hosts|import_playbook)\s*:",
)


@dataclass
class CommandResult:
    """Outcome of a single external command."""

    name: str
    stack: str
    argv: list[str]
    cwd: str
    exit_code: int
    output: str
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def ok(self) -> bool:
        if self.skipped:
            return True
        return self.exit_code == 0 and not has_deprecation_warning(self.output)

    @property
    def has_deprecation(self) -> bool:
        return has_deprecation_warning(self.output)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.ok
        data["has_deprecation"] = self.has_deprecation
        return data


@dataclass
class CheckReport:
    """Aggregate report for one check-ansible invocation."""

    ansible_root: str
    paths: list[str]
    uses_ansible_lint: bool
    results: list[CommandResult] = field(default_factory=list)
    versions: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def to_dict(self) -> dict:
        return {
            "ansible_root": self.ansible_root,
            "paths": self.paths,
            "uses_ansible_lint": self.uses_ansible_lint,
            "versions": self.versions,
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
        }


def has_deprecation_warning(text: str) -> bool:
    return bool(DEPRECATION_RE.search(text or ""))


def find_ansible_root(start: Path) -> Path:
    """Walk up from *start* until an Ansible/yamllint config marker is found.

    If nothing is found, return the start directory (or its parent if *start*
    is a file).
    """
    path = start.resolve()
    if path.is_file():
        path = path.parent

    for candidate in (path, *path.parents):
        for marker in ANSIBLE_ROOT_MARKERS:
            if (candidate / marker).exists():
                return candidate
        # Also accept repo root with src/ansible/ansible.cfg.
        nested = candidate / "src" / "ansible" / "ansible.cfg"
        if nested.is_file():
            return nested.parent

    return path


def project_uses_ansible_lint(root: Path) -> bool:
    """True when the project documents ansible-lint usage."""
    root = root.resolve()
    lint_yml = root / ".ansible-lint.yml"
    if (root / ".ansible-lint").is_file() or lint_yml.is_file():
        return True
    # Walk parents for monorepo layouts (ansible.cfg under src/ansible).
    for candidate in (root, *list(root.parents)[:4]):
        if (candidate / ".ansible-lint").is_file():
            return True
        if (candidate / ".ansible-lint.yml").is_file():
            return True
        precommit = candidate / ".pre-commit-config.yaml"
        if precommit.is_file():
            text = precommit.read_text(encoding="utf-8", errors="replace")
            if "ansible-lint" in text:
                return True
    return False


def is_playbook(path: Path) -> bool:
    """True if file looks like a playbook (hosts / import_playbook)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(PLAYBOOK_HINT_RE.search(text))


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def uvx_ansible_playbook_argv(
    *,
    python: str = DEFAULT_PYTHON,
    ansible_pin: str = DEFAULT_ANSIBLE_PIN,
) -> list[str]:
    return [
        "uvx",
        f"--python={python}",
        "--from",
        "ansible-core",
        "--with",
        f"ansible=={ansible_pin}",
        "ansible-playbook",
    ]


def uvx_ansible_lint_argv(
    *,
    python: str = DEFAULT_PYTHON,
    ansible_pin: str = DEFAULT_ANSIBLE_PIN,
) -> list[str]:
    return [
        "uvx",
        f"--python={python}",
        "--from",
        "ansible-lint",
        "--with",
        f"ansible=={ansible_pin}",
        "ansible-lint",
    ]


def uvx_yamllint_argv(*, python: str = DEFAULT_PYTHON) -> list[str]:
    return ["uvx", f"--python={python}", "--from", "yamllint", "yamllint"]


def run_command(
    name: str,
    stack: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    skipped: bool = False,
    skip_reason: str | None = None,
) -> CommandResult:
    if skipped:
        return CommandResult(
            name=name,
            stack=stack,
            argv=argv,
            cwd=str(cwd),
            exit_code=0,
            output="",
            skipped=True,
            skip_reason=skip_reason,
        )

    merged = os.environ.copy()
    if env:
        merged.update(env)
    merged.setdefault("ANSIBLE_DEPRECATION_WARNINGS", "True")

    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=merged,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            name=name,
            stack=stack,
            argv=argv,
            cwd=str(cwd),
            exit_code=127,
            output=f"command not found: {exc.filename or argv[0]}",
        )

    output = (completed.stdout or "") + (completed.stderr or "")
    return CommandResult(
        name=name,
        stack=stack,
        argv=argv,
        cwd=str(cwd),
        exit_code=completed.returncode,
        output=output,
    )


def capture_version(argv: list[str], *, cwd: Path) -> str:
    result = run_command("version", "probe", argv + ["--version"], cwd=cwd)
    if result.exit_code != 0:
        return result.output.strip() or f"(failed: exit {result.exit_code})"
    # First non-empty line is usually enough.
    for line in result.output.splitlines():
        line = line.strip()
        if line:
            return line
    return "(empty)"


def resolve_paths(raw_paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    for path in raw_paths:
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        if path.is_dir():
            raise ValueError(f"Expected a file, got directory: {path}")
        if path.suffix not in {".yml", ".yaml"}:
            raise ValueError(f"Not a YAML file: {path}")
        resolved.append(path)
    return resolved


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def check_ansible(
    paths: list[Path],
    *,
    ansible_root: Path | None = None,
    inventory: Path | None = None,
    python: str = DEFAULT_PYTHON,
    ansible_pin: str = DEFAULT_ANSIBLE_PIN,
    skip_uvx: bool = False,
    skip_yamllint: bool = False,
    skip_syntax_check: bool = False,
    skip_ansible_lint: bool = False,
    skip_deprecations: bool = False,
    force_ansible_lint: bool | None = None,
) -> CheckReport:
    """Run yamllint + dual-stack Ansible checks on *paths*."""
    resolved = resolve_paths(paths)
    if not resolved:
        raise ValueError("No paths to check")

    root = (ansible_root or find_ansible_root(resolved[0])).resolve()
    if force_ansible_lint is not None:
        uses_lint = force_ansible_lint
    else:
        uses_lint = project_uses_ansible_lint(root)

    rel_paths = [relative_to_root(p, root) for p in resolved]
    report = CheckReport(
        ansible_root=str(root),
        paths=rel_paths,
        uses_ansible_lint=uses_lint,
    )

    deprecation_env = {"ANSIBLE_DEPRECATION_WARNINGS": "True"}

    # --- Versions ---
    if which("ansible-playbook"):
        report.versions["system"] = capture_version(
            ["ansible-playbook"],
            cwd=root,
        )
    else:
        report.versions["system"] = "(ansible-playbook not on PATH)"

    if not skip_uvx and which("uvx"):
        report.versions["uvx"] = capture_version(
            uvx_ansible_playbook_argv(python=python, ansible_pin=ansible_pin),
            cwd=root,
        )
    elif skip_uvx:
        report.versions["uvx"] = "(skipped)"
    else:
        report.versions["uvx"] = "(uvx not on PATH)"

    # --- 1. yamllint ---
    if not skip_yamllint:
        yamllint_bin = which("yamllint")
        if yamllint_bin:
            report.results.append(
                run_command(
                    "yamllint",
                    "system",
                    [yamllint_bin, *rel_paths],
                    cwd=root,
                ),
            )
        elif not skip_uvx and which("uvx"):
            report.results.append(
                run_command(
                    "yamllint",
                    "uvx",
                    [*uvx_yamllint_argv(python=python), *rel_paths],
                    cwd=root,
                ),
            )
        else:
            report.results.append(
                run_command(
                    "yamllint",
                    "system",
                    ["yamllint", *rel_paths],
                    cwd=root,
                    skipped=True,
                    skip_reason="yamllint not installed and uvx unavailable",
                ),
            )

    playbooks = [p for p in resolved if is_playbook(p)]
    playbook_rels = [relative_to_root(p, root) for p in playbooks]
    role_or_other = [
        relative_to_root(p, root) for p in resolved if p not in playbooks
    ]

    # --- 2. ansible-playbook --syntax-check (playbooks only) ---
    if not skip_syntax_check and playbook_rels:
        syntax_argv_tail = ["--syntax-check"]
        if inventory is not None:
            syntax_argv_tail.extend(["-i", str(inventory)])
        syntax_argv_tail.extend(playbook_rels)

        if which("ansible-playbook"):
            report.results.append(
                run_command(
                    "syntax-check",
                    "system",
                    ["ansible-playbook", *syntax_argv_tail],
                    cwd=root,
                    env=deprecation_env,
                ),
            )
        else:
            report.results.append(
                run_command(
                    "syntax-check",
                    "system",
                    ["ansible-playbook", *syntax_argv_tail],
                    cwd=root,
                    skipped=True,
                    skip_reason="ansible-playbook not on PATH",
                ),
            )

        if skip_uvx:
            report.results.append(
                run_command(
                    "syntax-check",
                    "uvx",
                    [],
                    cwd=root,
                    skipped=True,
                    skip_reason="--skip-uvx",
                ),
            )
        elif which("uvx"):
            report.results.append(
                run_command(
                    "syntax-check",
                    "uvx",
                    [
                        *uvx_ansible_playbook_argv(
                            python=python,
                            ansible_pin=ansible_pin,
                        ),
                        *syntax_argv_tail,
                    ],
                    cwd=root,
                    env=deprecation_env,
                ),
            )
        else:
            report.results.append(
                run_command(
                    "syntax-check",
                    "uvx",
                    [],
                    cwd=root,
                    skipped=True,
                    skip_reason="uvx not on PATH",
                ),
            )

    # Deprecations always; full --strict for lint projects / non-playbooks.
    lint_targets = list(dict.fromkeys(rel_paths))

    def _run_ansible_lint(
        name: str,
        *,
        deprecations_only: bool,
        skip: bool,
        skip_reason: str | None = None,
    ) -> None:
        if skip or not lint_targets:
            report.results.append(
                run_command(
                    name,
                    "system",
                    [],
                    cwd=root,
                    skipped=True,
                    skip_reason=skip_reason or "skipped",
                ),
            )
            return

        lint_tail = ["--strict"]
        if deprecations_only:
            lint_tail.extend(["-t", "deprecations"])
        lint_tail.extend(lint_targets)

        # System
        if which("ansible-lint"):
            report.results.append(
                run_command(
                    name,
                    "system",
                    ["ansible-lint", *lint_tail],
                    cwd=root,
                    env=deprecation_env,
                ),
            )
        else:
            report.results.append(
                run_command(
                    name,
                    "system",
                    ["ansible-lint", *lint_tail],
                    cwd=root,
                    skipped=True,
                    skip_reason="ansible-lint not on PATH",
                ),
            )

        # uvx
        if skip_uvx:
            report.results.append(
                run_command(
                    name,
                    "uvx",
                    [],
                    cwd=root,
                    skipped=True,
                    skip_reason="--skip-uvx",
                ),
            )
        elif which("uvx"):
            report.results.append(
                run_command(
                    name,
                    "uvx",
                    [
                        *uvx_ansible_lint_argv(
                            python=python,
                            ansible_pin=ansible_pin,
                        ),
                        *lint_tail,
                    ],
                    cwd=root,
                    env=deprecation_env,
                ),
            )
        else:
            report.results.append(
                run_command(
                    name,
                    "uvx",
                    [],
                    cwd=root,
                    skipped=True,
                    skip_reason="uvx not on PATH",
                ),
            )

    # --- 3. ansible-lint --strict (project gate or non-playbook files) ---
    run_full_lint = (not skip_ansible_lint) and (
        uses_lint or bool(role_or_other)
    )
    if run_full_lint:
        _run_ansible_lint(
            "ansible-lint",
            deprecations_only=False,
            skip=False,
        )
    elif skip_ansible_lint:
        _run_ansible_lint(
            "ansible-lint",
            deprecations_only=False,
            skip=True,
            skip_reason="--skip-ansible-lint",
        )

    # --- 4. deprecation-only ansible-lint (always) ---
    if not skip_deprecations:
        _run_ansible_lint(
            "ansible-lint-deprecations",
            deprecations_only=True,
            skip=False,
        )
    else:
        _run_ansible_lint(
            "ansible-lint-deprecations",
            deprecations_only=True,
            skip=True,
            skip_reason="--skip-deprecations",
        )

    return report


def format_report(report: CheckReport, *, quiet: bool = False) -> str:
    lines: list[str] = []
    lines.append(f"ansible_root: {report.ansible_root}")
    lines.append(f"paths: {', '.join(report.paths)}")
    lines.append(f"uses_ansible_lint: {report.uses_ansible_lint}")
    if report.versions:
        lines.append("versions:")
        for key, value in report.versions.items():
            lines.append(f"  {key}: {value}")

    for result in report.results:
        if result.skipped:
            status = "SKIP"
        elif result.ok:
            status = "PASS"
        else:
            status = "FAIL"
        header = f"[{status}] {result.name} ({result.stack})"
        if result.skipped and result.skip_reason:
            header += f" — {result.skip_reason}"
        elif not result.skipped:
            header += f" — exit {result.exit_code}"
            if result.has_deprecation:
                header += " [DEPRECATION WARNING in output]"
        lines.append(header)
        if not quiet and result.output.strip() and not result.skipped:
            # Indent command output for readability.
            for out_line in result.output.rstrip().splitlines():
                lines.append(f"  | {out_line}")

    lines.append(f"overall: {'PASS' if report.ok else 'FAIL'}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check Ansible YAML with yamllint and dual-stack "
            "(system + uvx Python 3.12 / ansible pin) ansible-playbook "
            "syntax-check and ansible-lint, including a deprecations gate."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Ansible YAML file(s) to check (.yml / .yaml)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Override $ANSIBLE_ROOT (directory with ansible.cfg / lint config)"
        ),
    )
    parser.add_argument(
        "-i",
        "--inventory",
        type=Path,
        default=None,
        help="Inventory for ansible-playbook --syntax-check",
    )
    parser.add_argument(
        "--ansible-version",
        default=DEFAULT_ANSIBLE_PIN,
        help=(
            f"Pinned ansible package for uvx (default: {DEFAULT_ANSIBLE_PIN})"
        ),
    )
    parser.add_argument(
        "--python",
        default=DEFAULT_PYTHON,
        help=f"Python version for uvx (default: {DEFAULT_PYTHON})",
    )
    parser.add_argument(
        "--skip-uvx",
        action="store_true",
        help="Run system stack only",
    )
    parser.add_argument(
        "--skip-yamllint",
        action="store_true",
        help="Skip yamllint",
    )
    parser.add_argument(
        "--skip-syntax-check",
        action="store_true",
        help="Skip ansible-playbook --syntax-check",
    )
    parser.add_argument(
        "--skip-ansible-lint",
        action="store_true",
        help=(
            "Skip full ansible-lint --strict "
            "(deprecations still run unless skipped)"
        ),
    )
    parser.add_argument(
        "--skip-deprecations",
        action="store_true",
        help="Skip ansible-lint -t deprecations",
    )
    parser.add_argument(
        "--force-ansible-lint",
        action="store_true",
        help=("Always run full ansible-lint even without .ansible-lint"),
    )
    parser.add_argument(
        "--no-ansible-lint",
        action="store_true",
        help=(
            "Do not treat project as using ansible-lint "
            "(still lint non-playbooks)"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON report",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Omit command output bodies from text report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    force: bool | None = None
    if args.force_ansible_lint:
        force = True
    elif args.no_ansible_lint:
        force = False

    try:
        report = check_ansible(
            args.paths,
            ansible_root=args.root,
            inventory=args.inventory,
            python=args.python,
            ansible_pin=args.ansible_version,
            skip_uvx=args.skip_uvx,
            skip_yamllint=args.skip_yamllint,
            skip_syntax_check=args.skip_syntax_check,
            skip_ansible_lint=args.skip_ansible_lint,
            skip_deprecations=args.skip_deprecations,
            force_ansible_lint=force,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        sys.stdout.write(format_report(report, quiet=args.quiet))

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
