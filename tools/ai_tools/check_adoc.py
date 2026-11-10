#!/usr/bin/env python3
"""docs-idmci AsciiDoc build gate (writing-adoc): make target, no warnings."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

DEFAULT_IMAGE = "quay.io/idmops/docs-idmci-base:latest"
SCOPED_TARGETS = ("maintainer_docs", "user_docs")
WARNING_RE = re.compile(r"WARNING:|missing attribute", re.IGNORECASE)


@dataclass
class CommandResult:
    """Outcome of one make invocation."""

    name: str
    runner: str
    argv: list[str]
    cwd: str
    exit_code: int
    output: str
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def has_warning(self) -> bool:
        return bool(WARNING_RE.search(self.output or ""))

    @property
    def ok(self) -> bool:
        if self.skipped:
            return True
        return self.exit_code == 0 and not self.has_warning

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.ok
        data["has_warning"] = self.has_warning
        return data


@dataclass
class CheckReport:
    """Aggregate report for one check-adoc invocation."""

    docs_root: str
    paths: list[str]
    target: str
    results: list[CommandResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def to_dict(self) -> dict:
        return {
            "docs_root": self.docs_root,
            "paths": self.paths,
            "target": self.target,
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
        }


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def is_docs_root(path: Path) -> bool:
    """docs-idmci layout: Makefile with the doc targets + source-url macro."""
    makefile = path / "Makefile"
    if not makefile.is_file() or not (path / "macros" / "source-url.rb").is_file():
        return False
    text = makefile.read_text(encoding="utf-8", errors="replace")
    return "user_docs" in text and "maintainer_docs" in text


def find_docs_root(start: Path, *, stop: Path | None = None) -> Path | None:
    """Walk up from *start* to a docs root; do not go above *stop*."""
    path = start.resolve()
    if path.is_file():
        path = path.parent
    limit = stop.resolve() if stop else None
    for candidate in (path, *path.parents):
        if is_docs_root(candidate):
            return candidate
        if limit is not None and candidate == limit:
            break
    return None


def pick_target(rel_paths: Sequence[str]) -> str:
    """Scoped make target when every file is in one tree, else ``all``."""
    tops = {p.split("/", 1)[0] for p in rel_paths}
    if len(tops) == 1:
        top = next(iter(tops))
        if top in SCOPED_TARGETS:
            return top
    return "all"


def container_argv(
    root: Path,
    target: str,
    *,
    image: str = DEFAULT_IMAGE,
) -> list[str]:
    return [
        "podman",
        "run",
        "--rm",
        "--user",
        "root",
        "-v",
        f"{root}:/docs:Z",
        "-w",
        "/docs",
        image,
        "make",
        target,
    ]


def _run(name: str, runner: str, argv: list[str], cwd: Path) -> CommandResult:
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


def check_adoc(
    paths: Sequence[Path],
    *,
    docs_root: Path | None = None,
    target: str | None = None,
    image: str = DEFAULT_IMAGE,
    skip_container: bool = False,
    clean: bool = True,
) -> CheckReport:
    """Build the docs tree containing *paths*; fail on errors or warnings."""
    resolved = [p.expanduser().resolve() for p in paths]
    if not resolved:
        raise ValueError("No paths to check")
    for path in resolved:
        if not path.is_file():
            raise FileNotFoundError(f"Not a file: {path}")
        if path.suffix != ".adoc":
            raise ValueError(f"Not an .adoc file: {path}")

    root = docs_root.resolve() if docs_root else find_docs_root(resolved[0])
    if root is None or not is_docs_root(root):
        raise ValueError(
            f"No docs-idmci root (Makefile + macros/source-url.rb) for {resolved[0]}",
        )

    rel_paths: list[str] = []
    for path in resolved:
        try:
            rel_paths.append(path.relative_to(root).as_posix())
        except ValueError as exc:
            raise ValueError(f"{path} is outside docs root {root}") from exc

    chosen = target or pick_target(rel_paths)
    report = CheckReport(docs_root=str(root), paths=rel_paths, target=chosen)

    if which("asciidoctor") and which("make"):
        runner = "host"
        if clean:
            # Stale html/ could hide warnings; best effort, result ignored.
            _run("make-clean", runner, ["make", "clean"], root)
        report.results.append(_run(f"make {chosen}", runner, ["make", chosen], root))
    elif which("podman") and not skip_container:
        runner = "podman"
        report.results.append(
            _run(
                f"make {chosen}",
                runner,
                container_argv(root, chosen, image=image),
                root,
            ),
        )
    else:
        report.results.append(
            CommandResult(
                f"make {chosen}",
                "none",
                [],
                str(root),
                0,
                "",
                skipped=True,
                skip_reason="asciidoctor/make missing and podman unavailable",
            ),
        )
    return report


def format_report(report: CheckReport, *, quiet: bool = False) -> str:
    lines = [
        f"docs_root: {report.docs_root}",
        f"paths: {', '.join(report.paths)}",
        f"target: {report.target}",
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
            if result.has_warning:
                header += " [asciidoctor WARNING in output]"
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
    help="Docs root (default: nearest dir with Makefile + macros/source-url.rb)",
)
@click.option(
    "--target",
    type=click.Choice(["all", "user_docs", "maintainer_docs"]),
    default=None,
    help="Make target (default: scoped by changed paths)",
)
@click.option("--image", default=DEFAULT_IMAGE, show_default=True, help="Container image")
@click.option(
    "--skip-container",
    is_flag=True,
    help="Do not fall back to podman when asciidoctor/make is missing",
)
@click.option("--no-clean", is_flag=True, help="Skip make clean before building")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON report")
@click.option("-q", "--quiet", is_flag=True, help="Omit build output from text report")
def cli(
    paths: tuple[Path, ...],
    root: Path | None,
    target: str | None,
    image: str,
    skip_container: bool,
    no_clean: bool,
    as_json: bool,
    quiet: bool,
) -> None:
    """Build the docs-idmci tree for PATHS; fail on asciidoctor warnings."""
    try:
        report = check_adoc(
            list(paths),
            docs_root=root,
            target=target,
            image=image,
            skip_container=skip_container,
            clean=not no_clean,
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
        cli.main(args=argv, prog_name="check-adoc", standalone_mode=False)
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
