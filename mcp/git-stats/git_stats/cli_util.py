"""Subprocess helpers for gh and glab."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

SUBPROCESS_TIMEOUT = 30


@dataclass
class CliResult:
    ok: bool
    command: list[str]
    cwd: str
    stdout: str
    stderr: str
    returncode: int


def which(name: str) -> str | None:
    return shutil.which(name)


def run_cmd(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = SUBPROCESS_TIMEOUT,
) -> CliResult:
    cmd = list(args)
    workdir = str(cwd) if cwd else "."
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return CliResult(
            ok=False,
            command=cmd,
            cwd=workdir,
            stdout=exc.stdout or "",
            stderr=f"timeout after {timeout}s",
            returncode=-1,
        )
    except OSError as exc:
        return CliResult(
            ok=False,
            command=cmd,
            cwd=workdir,
            stdout="",
            stderr=str(exc),
            returncode=-1,
        )
    return CliResult(
        ok=proc.returncode == 0,
        command=cmd,
        cwd=workdir,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )


def parse_json_stdout(result: CliResult) -> Any | None:
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_json_cmd(
    base_args: Sequence[str],
    *,
    cwd: Path | None = None,
    json_fields: str | None = None,
) -> tuple[CliResult, Any | None]:
    flags = ("--json",)
    if json_fields:
        for flag in flags:
            result = run_cmd([*base_args, flag, json_fields], cwd=cwd)
            if result.ok:
                parsed = parse_json_stdout(result)
                if parsed is not None:
                    return result, parsed
        result = run_cmd([*base_args, "--output", "json"], cwd=cwd)
        if result.ok:
            return result, parse_json_stdout(result)
        return result, None

    for flag in flags:
        result = run_cmd([*base_args, flag], cwd=cwd)
        if result.ok:
            parsed = parse_json_stdout(result)
            if parsed is not None:
                return result, parsed
    result = run_cmd([*base_args, "--output", "json"], cwd=cwd)
    return result, parse_json_stdout(result) if result.ok else None
