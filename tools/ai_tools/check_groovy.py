#!/usr/bin/env python3
"""Read-only Groovy/Jenkinsfile lint via npm-groovy-lint (host or podman)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

# CI's quay.io/idmops/node:18 is Debian 11 (EOL apt, no JRE, Node too old for
# current npm-groovy-lint), so use a current Node image and add a JRE.
DEFAULT_IMAGE = "docker.io/library/node:22-bookworm"
LINT_VERSION = "latest"
SERVERHOST = "http://127.0.0.1"
GROOVY_SUFFIXES = (".groovy", ".gvy", ".gradle")
CONFIG_MARKERS = (
    ".groovylintrc.json",
    ".groovylintrc.js",
    ".groovylintrc.yml",
    ".groovylintrc.yaml",
    ".groovylintrc",
)


@dataclass
class CommandResult:
    """Outcome of one linter invocation."""

    name: str
    runner: str
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
    """Aggregate report for one check-groovy invocation."""

    groovy_root: str
    paths: list[str]
    config: str | None
    results: list[CommandResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def to_dict(self) -> dict:
        return {
            "groovy_root": self.groovy_root,
            "paths": self.paths,
            "config": self.config,
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
        }


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def is_groovy_path(path: str) -> bool:
    """True for Groovy sources, Gradle scripts, and Jenkinsfile*."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.lower().endswith(GROOVY_SUFFIXES) or name.lower().startswith(
        "jenkinsfile",
    )


def find_groovy_root(start: Path) -> Path:
    """Walk up to the dir holding a .groovylintrc*; else the start dir."""
    path = start.resolve()
    if path.is_file():
        path = path.parent
    for candidate in (path, *path.parents):
        if any((candidate / m).exists() for m in CONFIG_MARKERS):
            return candidate
    return path


def find_config(root: Path) -> str | None:
    for marker in CONFIG_MARKERS:
        if (root / marker).exists():
            return marker
    return None


def lint_args(rel_paths: Sequence[str]) -> list[str]:
    """npm-groovy-lint args (no --fix; read-only)."""
    return [
        "--output",
        "txt",
        f"--serverhost={SERVERHOST}",
        "--files",
        ",".join(rel_paths),
    ]


def container_argv(
    root: Path,
    rel_paths: Sequence[str],
    *,
    image: str = DEFAULT_IMAGE,
    version: str = LINT_VERSION,
) -> list[str]:
    """podman command that installs Java + npm-groovy-lint and lints in *root*."""
    # Node images ship no JRE; npm-groovy-lint needs one for CodeNarc.
    steps = [
        (
            "command -v java >/dev/null 2>&1 || "
            "(apt-get update -qq && apt-get install -y -qq default-jre-headless) "
            ">/dev/null 2>&1"
        ),
        f"npm install -g npm-groovy-lint@{version} >/dev/null 2>&1",
        "npm-groovy-lint " + " ".join(_shquote(a) for a in lint_args(rel_paths)),
    ]
    inner = " && ".join(steps)
    return [
        "podman",
        "run",
        "--rm",
        "-v",
        f"{root}:/src:Z",
        "-w",
        "/src",
        image,
        "sh",
        "-c",
        inner,
    ]


def _shquote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _run(
    name: str,
    runner: str,
    argv: list[str],
    cwd: Path,
) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            name,
            runner,
            argv,
            str(cwd),
            127,
            f"command not found: {exc.filename or argv[0]}",
        )
    return CommandResult(
        name,
        runner,
        argv,
        str(cwd),
        proc.returncode,
        (proc.stdout or "") + (proc.stderr or ""),
    )


def resolve_paths(raw_paths: Sequence[Path]) -> list[Path]:
    resolved: list[Path] = []
    for path in raw_paths:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Not a file: {path}")
        if not is_groovy_path(path.name):
            raise ValueError(f"Not a Groovy/Jenkinsfile path: {path}")
        resolved.append(path)
    return resolved


def check_groovy(
    paths: Sequence[Path],
    *,
    groovy_root: Path | None = None,
    image: str = DEFAULT_IMAGE,
    version: str = LINT_VERSION,
    skip_container: bool = False,
) -> CheckReport:
    """Lint *paths* with npm-groovy-lint on host, else in the CI container."""
    resolved = resolve_paths(paths)
    if not resolved:
        raise ValueError("No paths to check")

    root = (groovy_root or find_groovy_root(resolved[0])).resolve()
    rel_paths: list[str] = []
    for path in resolved:
        try:
            rel_paths.append(path.relative_to(root).as_posix())
        except ValueError as exc:
            raise ValueError(f"{path} is outside root {root}") from exc

    report = CheckReport(
        groovy_root=str(root),
        paths=rel_paths,
        config=find_config(root),
    )

    host_bin = which("npm-groovy-lint")
    if host_bin:
        report.results.append(
            _run(
                "npm-groovy-lint",
                "host",
                [host_bin, *lint_args(rel_paths)],
                root,
            ),
        )
    elif which("podman") and not skip_container:
        report.results.append(
            _run(
                "npm-groovy-lint",
                "podman",
                container_argv(root, rel_paths, image=image, version=version),
                root,
            ),
        )
    else:
        reason = (
            "npm-groovy-lint not on PATH and podman unavailable"
            if not skip_container
            else "npm-groovy-lint not on PATH and --skip-container set"
        )
        report.results.append(
            CommandResult(
                "npm-groovy-lint",
                "none",
                [],
                str(root),
                0,
                "",
                skipped=True,
                skip_reason=reason,
            ),
        )
    return report


def format_report(report: CheckReport, *, quiet: bool = False) -> str:
    lines = [
        f"groovy_root: {report.groovy_root}",
        f"paths: {', '.join(report.paths)}",
        f"config: {report.config or '(none; linter defaults)'}",
    ]
    for result in report.results:
        if result.skipped:
            status = "SKIP"
        elif result.ok:
            status = "PASS"
        else:
            status = "FAIL"
        header = f"[{status}] {result.name} ({result.runner})"
        if result.skipped and result.skip_reason:
            header += f" - {result.skip_reason}"
        elif not result.skipped:
            header += f" - exit {result.exit_code}"
        lines.append(header)
        if not quiet and result.output.strip() and not result.skipped:
            lines.extend(f"  | {ln}" for ln in result.output.rstrip().splitlines())
    lines.append(f"overall: {'PASS' if report.ok else 'FAIL'}")
    return "\n".join(lines) + "\n"


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "paths",
    nargs=-1,
    required=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Lint root (default: nearest dir with .groovylintrc*)",
)
@click.option("--image", default=DEFAULT_IMAGE, show_default=True, help="Container image")
@click.option(
    "--lint-version",
    default=LINT_VERSION,
    show_default=True,
    help="npm-groovy-lint version installed in the container",
)
@click.option(
    "--skip-container",
    is_flag=True,
    help="Do not fall back to podman when npm-groovy-lint is missing",
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON report")
@click.option("-q", "--quiet", is_flag=True, help="Omit linter output from text report")
def cli(
    paths: tuple[Path, ...],
    root: Path | None,
    image: str,
    lint_version: str,
    skip_container: bool,
    as_json: bool,
    quiet: bool,
) -> None:
    """Lint Groovy / Jenkinsfile PATHS with npm-groovy-lint (read-only)."""
    try:
        report = check_groovy(
            list(paths),
            groovy_root=root,
            image=image,
            version=lint_version,
            skip_container=skip_container,
        )
    except (FileNotFoundError, ValueError) as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        click.echo(format_report(report, quiet=quiet), nl=False)
    sys.exit(0 if report.ok else 1)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="check-groovy", standalone_mode=False)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
