#!/usr/bin/env python3
"""Run read-only Python lint/format checks using project configuration."""

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

PYTHON_ROOT_MARKERS = (
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    ".flake8",
    "ruff.toml",
    ".ruff.toml",
)

PYPROJECT_TOOL_RE = re.compile(
    r"^\s*\[tool\.(ruff|black|isort|flake8)\]\s*$",
    re.MULTILINE,
)
SETUP_CFG_FLAKE8_RE = re.compile(r"^\s*\[flake8\]\s*$", re.MULTILINE)
CI_WORKFLOW_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".gitlab-ci.yml",
    ".gitlab-ci.yaml",
)


@dataclass(frozen=True)
class ProjectPythonTools:
    """Lint/format tools inferred for a Python tree."""

    python_root: Path
    uses_ruff: bool
    uses_flake8: bool
    uses_black: bool
    uses_isort: bool
    primary: str  # ruff | flake8-stack | ruff-fallback
    notes: tuple[str, ...] = ()

    def selected_tools(self) -> list[str]:
        if self.primary == "ruff":
            tools = ["ruff-check", "ruff-format-check"]
            return tools
        if self.primary == "flake8-stack":
            tools = ["flake8"]
            if self.uses_isort:
                tools.append("isort-check")
            if self.uses_black:
                tools.append("black-check")
            return tools
        return ["ruff-check", "ruff-format-check"]


@dataclass
class CommandResult:
    """Outcome of a single external command."""

    name: str
    argv: list[str]
    cwd: str
    exit_code: int
    output: str
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped or self.exit_code == 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.ok
        return data


@dataclass
class CheckReport:
    """Aggregate report for one check-python invocation."""

    python_root: str
    paths: list[str]
    tools: ProjectPythonTools
    results: list[CommandResult] = field(default_factory=list)
    versions: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def to_dict(self) -> dict:
        return {
            "python_root": self.python_root,
            "paths": self.paths,
            "primary": self.tools.primary,
            "uses_ruff": self.tools.uses_ruff,
            "uses_flake8": self.tools.uses_flake8,
            "uses_black": self.tools.uses_black,
            "uses_isort": self.tools.uses_isort,
            "notes": list(self.tools.notes),
            "versions": self.versions,
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
        }


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def find_python_root(start: Path) -> Path:
    """Walk up from *start* until a Python project marker is found."""
    path = start.resolve()
    if path.is_file():
        path = path.parent

    for candidate in (path, *path.parents):
        for marker in PYTHON_ROOT_MARKERS:
            if (candidate / marker).exists():
                return candidate

    return path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _pyproject_tools(pyproject: Path) -> set[str]:
    text = _read_text(pyproject)
    found: set[str] = set()
    for match in PYPROJECT_TOOL_RE.finditer(text):
        found.add(match.group(1))
    return found


def _setup_cfg_has_flake8(setup_cfg: Path) -> bool:
    return bool(SETUP_CFG_FLAKE8_RE.search(_read_text(setup_cfg)))


def _precommit_hooks(root: Path) -> set[str]:
    hooks: set[str] = set()
    for candidate in (root, *list(root.parents)[:4]):
        precommit = candidate / ".pre-commit-config.yaml"
        if not precommit.is_file():
            continue
        text = _read_text(precommit)
        for hook in ("ruff", "ruff-format", "flake8", "black", "isort"):
            if re.search(rf"\bid:\s*{re.escape(hook)}\b", text):
                hooks.add(hook)
        if "repo: https://github.com/astral-sh/ruff-pre-commit" in text:
            hooks.add("ruff")
    return hooks


def _ci_mentions(root: Path, needle: str) -> bool:
    for pattern in CI_WORKFLOW_GLOBS:
        for path in root.glob(pattern):
            if path.is_file() and needle in _read_text(path):
                return True
        for parent in list(root.parents)[:3]:
            for path in parent.glob(pattern):
                if path.is_file() and needle in _read_text(path):
                    return True
    return False


def discover_project_tools(root: Path) -> ProjectPythonTools:
    """Infer which linters the project uses."""
    root = root.resolve()
    notes: list[str] = []
    pyproject = root / "pyproject.toml"
    py_tools = _pyproject_tools(pyproject) if pyproject.is_file() else set()

    uses_ruff = (
        "ruff" in py_tools
        or (root / "ruff.toml").is_file()
        or (root / ".ruff.toml").is_file()
    )
    uses_flake8 = (
        "flake8" in py_tools
        or (root / ".flake8").is_file()
        or _setup_cfg_has_flake8(root / "setup.cfg")
    )
    uses_black = "black" in py_tools
    uses_isort = "isort" in py_tools or (root / ".isort.cfg").is_file()

    hooks = _precommit_hooks(root)
    if "ruff" in hooks or "ruff-format" in hooks:
        uses_ruff = True
    if "flake8" in hooks:
        uses_flake8 = True
    if "black" in hooks:
        uses_black = True
    if "isort" in hooks:
        uses_isort = True

    if _ci_mentions(root, "ruff check") or _ci_mentions(root, "ruff format"):
        uses_ruff = True
        notes.append("CI mentions ruff")
    if _ci_mentions(root, "flake8"):
        uses_flake8 = True
        notes.append("CI mentions flake8")
    if _ci_mentions(root, "black"):
        uses_black = True
        notes.append("CI mentions black")
    if _ci_mentions(root, "isort"):
        uses_isort = True
        notes.append("CI mentions isort")

    if uses_ruff and not (uses_flake8 or uses_black or uses_isort):
        primary = "ruff"
    elif uses_flake8 or uses_black or uses_isort:
        primary = "flake8-stack"
    else:
        primary = "ruff-fallback"
        notes.append("no project lint config found; using ruff fallback")

    return ProjectPythonTools(
        python_root=root,
        uses_ruff=uses_ruff,
        uses_flake8=uses_flake8,
        uses_black=uses_black,
        uses_isort=uses_isort,
        primary=primary,
        notes=tuple(notes),
    )


def resolve_paths(raw_paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    for path in raw_paths:
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        if path.is_dir():
            raise ValueError(f"Expected a file, got directory: {path}")
        if path.suffix != ".py":
            raise ValueError(f"Not a Python file: {path}")
        resolved.append(path)
    return resolved


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def run_command(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    skipped: bool = False,
    skip_reason: str | None = None,
) -> CommandResult:
    if skipped:
        return CommandResult(
            name=name,
            argv=argv,
            cwd=str(cwd),
            exit_code=0,
            output="",
            skipped=True,
            skip_reason=skip_reason,
        )

    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            name=name,
            argv=argv,
            cwd=str(cwd),
            exit_code=127,
            output=f"command not found: {exc.filename or argv[0]}",
        )

    output = (completed.stdout or "") + (completed.stderr or "")
    return CommandResult(
        name=name,
        argv=argv,
        cwd=str(cwd),
        exit_code=completed.returncode,
        output=output,
    )


def capture_version(argv: list[str], *, cwd: Path) -> str:
    result = run_command("version", [*argv, "--version"], cwd=cwd)
    if result.exit_code != 0:
        return result.output.strip() or f"(failed: exit {result.exit_code})"
    for line in result.output.splitlines():
        line = line.strip()
        if line:
            return line
    return "(empty)"


def check_python(
    paths: list[Path],
    *,
    python_root: Path | None = None,
    skip_ruff: bool = False,
    skip_flake8: bool = False,
    skip_black: bool = False,
    skip_isort: bool = False,
    force_ruff: bool = False,
    force_flake8: bool = False,
) -> CheckReport:
    """Run read-only Python checks on *paths*."""
    resolved = resolve_paths(paths)
    if not resolved:
        raise ValueError("No paths to check")

    root = (python_root or find_python_root(resolved[0])).resolve()
    tools = discover_project_tools(root)

    if force_ruff:
        tools = ProjectPythonTools(
            python_root=root,
            uses_ruff=True,
            uses_flake8=False,
            uses_black=False,
            uses_isort=False,
            primary="ruff",
            notes=tools.notes + ("--force-ruff",),
        )
    elif force_flake8:
        tools = ProjectPythonTools(
            python_root=root,
            uses_ruff=False,
            uses_flake8=True,
            uses_black=tools.uses_black,
            uses_isort=tools.uses_isort,
            primary="flake8-stack",
            notes=tools.notes + ("--force-flake8",),
        )

    rel_paths = [relative_to_root(p, root) for p in resolved]
    report = CheckReport(
        python_root=str(root),
        paths=rel_paths,
        tools=tools,
    )

    for tool in ("ruff", "flake8", "black", "isort"):
        binary = which(tool)
        if binary:
            report.versions[tool] = capture_version([tool], cwd=root)

    selected = tools.selected_tools()
    if skip_ruff:
        selected = [t for t in selected if not t.startswith("ruff")]
    if skip_flake8:
        selected = [t for t in selected if t != "flake8"]
    if skip_black:
        selected = [t for t in selected if t != "black-check"]
    if skip_isort:
        selected = [t for t in selected if t != "isort-check"]

    for name in selected:
        if name == "ruff-check":
            report.results.append(
                _run_ruff_check(rel_paths, cwd=root),
            )
        elif name == "ruff-format-check":
            report.results.append(
                _run_ruff_format_check(rel_paths, cwd=root),
            )
        elif name == "flake8":
            report.results.append(
                _run_flake8(rel_paths, cwd=root),
            )
        elif name == "black-check":
            report.results.append(
                _run_black_check(rel_paths, cwd=root),
            )
        elif name == "isort-check":
            report.results.append(
                _run_isort_check(rel_paths, cwd=root),
            )

    return report


def _run_ruff_check(rel_paths: list[str], *, cwd: Path) -> CommandResult:
    if not which("ruff"):
        return run_command(
            "ruff-check",
            ["ruff", "check", *rel_paths],
            cwd=cwd,
            skipped=True,
            skip_reason="ruff not on PATH",
        )
    return run_command(
        "ruff-check",
        ["ruff", "check", *rel_paths],
        cwd=cwd,
    )


def _run_ruff_format_check(rel_paths: list[str], *, cwd: Path) -> CommandResult:
    if not which("ruff"):
        return run_command(
            "ruff-format-check",
            ["ruff", "format", "--check", *rel_paths],
            cwd=cwd,
            skipped=True,
            skip_reason="ruff not on PATH",
        )
    return run_command(
        "ruff-format-check",
        ["ruff", "format", "--check", *rel_paths],
        cwd=cwd,
    )


def _run_flake8(rel_paths: list[str], *, cwd: Path) -> CommandResult:
    if not which("flake8"):
        return run_command(
            "flake8",
            ["flake8", *rel_paths],
            cwd=cwd,
            skipped=True,
            skip_reason="flake8 not on PATH",
        )
    return run_command(
        "flake8",
        ["flake8", *rel_paths],
        cwd=cwd,
    )


def _run_black_check(rel_paths: list[str], *, cwd: Path) -> CommandResult:
    if not which("black"):
        return run_command(
            "black-check",
            ["black", "--check", *rel_paths],
            cwd=cwd,
            skipped=True,
            skip_reason="black not on PATH",
        )
    return run_command(
        "black-check",
        ["black", "--check", *rel_paths],
        cwd=cwd,
    )


def _run_isort_check(rel_paths: list[str], *, cwd: Path) -> CommandResult:
    if not which("isort"):
        return run_command(
            "isort-check",
            ["isort", "--check-only", *rel_paths],
            cwd=cwd,
            skipped=True,
            skip_reason="isort not on PATH",
        )
    return run_command(
        "isort-check",
        ["isort", "--check-only", *rel_paths],
        cwd=cwd,
    )


def format_report(report: CheckReport, *, quiet: bool = False) -> str:
    lines: list[str] = [
        f"python_root: {report.python_root}",
        f"paths: {', '.join(report.paths)}",
        f"primary: {report.tools.primary}",
        f"uses_ruff: {report.tools.uses_ruff}",
        f"uses_flake8: {report.tools.uses_flake8}",
        f"uses_black: {report.tools.uses_black}",
        f"uses_isort: {report.tools.uses_isort}",
    ]
    if report.tools.notes:
        lines.append(f"notes: {', '.join(report.tools.notes)}")
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
        header = f"[{status}] {result.name}"
        if result.skipped and result.skip_reason:
            header += f" — {result.skip_reason}"
        elif not result.skipped:
            header += f" — exit {result.exit_code}"
        lines.append(header)
        if not quiet and result.output.strip() and not result.skipped:
            for out_line in result.output.rstrip().splitlines():
                lines.append(f"  | {out_line}")

    lines.append(f"overall: {'PASS' if report.ok else 'FAIL'}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check Python files with project-appropriate read-only linters "
            "(ruff, flake8, black --check, isort --check-only)."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Python file(s) to check (.py)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override Python project root (pyproject.toml / lint config)",
    )
    parser.add_argument(
        "--skip-ruff",
        action="store_true",
        help="Skip ruff check / ruff format --check",
    )
    parser.add_argument(
        "--skip-flake8",
        action="store_true",
        help="Skip flake8",
    )
    parser.add_argument(
        "--skip-black",
        action="store_true",
        help="Skip black --check",
    )
    parser.add_argument(
        "--skip-isort",
        action="store_true",
        help="Skip isort --check-only",
    )
    parser.add_argument(
        "--force-ruff",
        action="store_true",
        help="Force ruff-only checks regardless of discovery",
    )
    parser.add_argument(
        "--force-flake8",
        action="store_true",
        help="Force flake8-stack checks regardless of discovery",
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
    try:
        report = check_python(
            args.paths,
            python_root=args.root,
            skip_ruff=args.skip_ruff,
            skip_flake8=args.skip_flake8,
            skip_black=args.skip_black,
            skip_isort=args.skip_isort,
            force_ruff=args.force_ruff,
            force_flake8=args.force_flake8,
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
