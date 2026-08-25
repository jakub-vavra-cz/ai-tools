#!/usr/bin/env python3
"""Extract the pytest/te short summary from a twd for a Jira draft.

Does not post to Jira.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

from ai_tools.clean_twd import require_twd

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}\s+")
OUTCOME_RE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S.*)$")
TOTALS_RE = re.compile(r"^=+\s+(.+ in [\d.]+s)\s+=+$")
RETURN_RE = re.compile(r"^RETURN CODE:\s*(-?\d+)\s*$")
STOP_PREFIXES = (
    "RETURN CODE:",
    "TESTS STEP END",
    "PHASE END",
    "PHASE START",
    "STOPPING EXECUTION",
)
OUTCOME_KEYS = {
    "PASSED": "passed",
    "FAILED": "failed",
    "ERROR": "errors",
    "SKIPPED": "skipped",
    "XFAIL": "xfailed",
    "XPASS": "xpassed",
}
TAIL_BYTES = 1_048_576


class TeSummaryError(RuntimeError):
    """No twd summary could be parsed."""


@dataclass
class TestSummary:
    """Last pytest/te short summary from a twd."""

    twd: str
    rc: int | None
    outcome: str
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    xfailed: list[str] = field(default_factory=list)
    xpassed: list[str] = field(default_factory=list)
    totals: str | None = None
    snippet: str = ""
    draft: str = ""
    source: str = ""
    command: str | None = None
    running: str | None = None
    upgraded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def strip_ts(line: str) -> str:
    return TS_RE.sub("", line.rstrip("\n"), count=1)


def read_tail(path: Path, max_bytes: int = TAIL_BYTES) -> str:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(-max_bytes, 2)
            data = fh.read()
            nl = data.find(b"\n")
            if nl >= 0:
                data = data[nl + 1 :]
        else:
            data = fh.read()
    return data.decode("utf-8", errors="replace")


def read_rc_file(twd: Path) -> int | None:
    path = twd / "pytest-run.rc"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    if not text:
        return None
    token = text[0].strip()
    if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
        return int(token)
    return None


def last_running_line(text: str) -> str | None:
    running: str | None = None
    for raw in text.splitlines():
        line = strip_ts(raw).strip()
        if line.startswith("Running:"):
            running = line[len("Running:") :].strip().strip('"')
    return running


def last_summary_block(text: str) -> tuple[list[str], int | None]:
    """Return stripped summary lines and RETURN CODE after the last short summary."""
    lines = [strip_ts(raw) for raw in text.splitlines()]
    starts = [i for i, line in enumerate(lines) if "short test summary info" in line.lower()]
    if not starts:
        return [], None
    start = starts[-1]
    block: list[str] = []
    rc: int | None = None
    for line in lines[start:]:
        stripped = line.strip()
        if block and "short test summary info" in stripped.lower() and line is not lines[start]:
            break
        if any(stripped.startswith(prefix) for prefix in STOP_PREFIXES):
            match = RETURN_RE.match(stripped)
            if match:
                rc = int(match.group(1))
            break
        block.append(line.rstrip())
    while block and not block[-1].strip():
        block.pop()
    return block, rc


def parse_outcomes(block: list[str]) -> dict[str, list[str] | str | None]:
    found: dict[str, list[str]] = {key: [] for key in OUTCOME_KEYS.values()}
    totals: str | None = None
    for line in block:
        stripped = line.strip()
        match = OUTCOME_RE.match(stripped)
        if match:
            key = OUTCOME_KEYS[match.group(1)]
            found[key].append(match.group(2).strip())
            continue
        totals_match = TOTALS_RE.match(stripped)
        if totals_match:
            totals = totals_match.group(1).strip()
    return {**found, "totals": totals}


def outcome_label(
    *,
    rc: int | None,
    failed: list[str],
    errors: list[str],
    passed: list[str],
) -> str:
    if failed or errors or (rc not in (None, 0)):
        return "failed"
    if passed or rc == 0:
        return "passed"
    return "unknown"


def format_draft(
    summary_lines: list[str],
    *,
    upgraded: list[str] | None = None,
) -> str:
    """Jira comment body: optional Upgraded NEVRAs, Complete!, pytest short summary."""
    parts: list[str] = []
    if upgraded:
        parts.append("Upgraded:")
        for nev in upgraded:
            parts.append(f"  {nev}")
        parts.append("")
    parts.append("Complete!")
    parts.append("")
    parts.extend(summary_lines)
    return "\n".join(parts).rstrip() + "\n"


def parse_junit(path: Path) -> tuple[list[str], dict[str, list[str]], str | None]:
    """Reconstruct a short summary from junit XML. Returns (lines, outcomes, totals)."""
    root = ET.parse(path).getroot()
    buckets: dict[str, list[str]] = {
        "passed": [],
        "failed": [],
        "errors": [],
        "skipped": [],
        "xfailed": [],
        "xpassed": [],
    }
    for case in root.iter("testcase"):
        name = case.get("name") or "unknown"
        classname = case.get("classname") or ""
        nodeid = f"{classname}::{name}" if classname else name
        if case.find("failure") is not None:
            buckets["failed"].append(nodeid)
        elif case.find("error") is not None:
            buckets["errors"].append(nodeid)
        elif case.find("skipped") is not None:
            buckets["skipped"].append(nodeid)
        else:
            buckets["passed"].append(nodeid)
    lines = ["=========================== short test summary info ============================"]
    for status, key in (
        ("PASSED", "passed"),
        ("FAILED", "failed"),
        ("ERROR", "errors"),
        ("SKIPPED", "skipped"),
    ):
        for nodeid in buckets[key]:
            lines.append(f"{status} {nodeid}")
    n_fail = len(buckets["failed"])
    n_pass = len(buckets["passed"])
    n_err = len(buckets["errors"])
    n_skip = len(buckets["skipped"])
    bits = []
    if n_fail:
        bits.append(f"{n_fail} failed")
    if n_err:
        bits.append(f"{n_err} error{'s' if n_err != 1 else ''}")
    if n_pass:
        bits.append(f"{n_pass} passed")
    if n_skip:
        bits.append(f"{n_skip} skipped")
    totals = ", ".join(bits) if bits else None
    if totals:
        lines.append(f"=========================== {totals} ===========================")
    return lines, buckets, totals


def newest_junit(twd: Path) -> Path | None:
    files = [path for path in twd.glob("*junit.xml") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def summarize_twd(
    twd: Path,
    *,
    upgraded: list[str] | None = None,
    log: Path | None = None,
) -> TestSummary:
    """Parse the last pytest short summary from twd logs (runner.log, else junit)."""
    twd = require_twd(twd)
    upgraded = list(upgraded or [])
    rc_file = read_rc_file(twd)
    runner = log if log is not None else twd / "runner.log"
    block: list[str] = []
    rc_log: int | None = None
    running: str | None = None
    source = ""

    if runner.is_file():
        text = read_tail(runner)
        running = last_running_line(text)
        block, rc_log = last_summary_block(text)
        if block:
            source = str(runner)

    outcomes: dict[str, list[str] | str | None]
    if block:
        outcomes = parse_outcomes(block)
    else:
        junit = newest_junit(twd)
        if junit is None:
            raise TeSummaryError(f"no short test summary in {runner} and no *junit.xml under {twd}")
        block, buckets, totals = parse_junit(junit)
        outcomes = {**buckets, "totals": totals}
        source = str(junit)

    passed = list(outcomes["passed"] or [])
    failed = list(outcomes["failed"] or [])
    errors = list(outcomes["errors"] or [])
    skipped = list(outcomes["skipped"] or [])
    xfailed = list(outcomes["xfailed"] or [])
    xpassed = list(outcomes["xpassed"] or [])
    totals = outcomes["totals"] if isinstance(outcomes["totals"], str) else None
    rc = rc_file if rc_file is not None else rc_log
    metadata = twd / "metadata.yaml"
    command = None
    if metadata.is_file():
        command = f"te --phase test {metadata.name}"
    snippet = "\n".join(block).rstrip() + "\n"
    draft = format_draft(block, upgraded=upgraded)
    return TestSummary(
        twd=str(twd),
        rc=rc,
        outcome=outcome_label(rc=rc, failed=failed, errors=errors, passed=passed),
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        xfailed=xfailed,
        xpassed=xpassed,
        totals=totals,
        snippet=snippet,
        draft=draft,
        source=source,
        command=command,
        running=running,
        upgraded=upgraded,
    )


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--twd",
    type=click.Path(path_type=Path, file_okay=False),
    default=".",
    show_default=True,
    help="twd or campaign directory",
)
@click.option(
    "--log",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="runner.log override",
)
@click.option(
    "--upgraded",
    multiple=True,
    help="Installed NEVRA to put under Upgraded: (repeatable)",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
def cli(twd: Path, log: Path | None, upgraded: tuple[str, ...], as_json: bool) -> None:
    """Print the last pytest short summary from twd (Jira draft snippet).

    Does not post to Jira. Prefers runner.log; falls back to *junit.xml.
    """
    try:
        result = summarize_twd(twd, upgraded=list(upgraded), log=log)
    except (TeSummaryError, ValueError) as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.draft, nl=False)


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="te-test-summary", standalone_mode=False)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
