#!/usr/bin/env python3
"""Query or install RPMs on IdM-CI twd inventory hosts (default group: client)."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click

from ai_tools.brew_fetch_nvr import is_debug_rpm
from ai_tools.clean_twd import require_twd
from ai_tools.nvr import NvrError, nvr_relation, parse_nvr

DEFAULT_HOSTS = "client"
DEFAULT_INVENTORY = "config/test.inventory.yaml"
DEFAULT_REMOTE_DIR = "/root/brew-rpms"
RPM_QF = r"%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n"


class TwdRpmError(RuntimeError):
    """Fatal ansible / inventory / RPM error."""


@dataclass
class HostModuleResult:
    """One host's ansible module result."""

    host: str
    rc: int | None = None
    stdout: str = ""
    stderr: str = ""
    failed: bool = False
    unreachable: bool = False
    changed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QueryHost:
    """rpm -q vs wanted NVR on one inventory host."""

    host: str
    relation: str
    installed: str | None
    packages: list[str] = field(default_factory=list)
    rc: int | None = None
    unreachable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QueryResult:
    twd: str
    hosts: str
    nvr: str
    inventory: str
    results: list[QueryHost] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "twd": self.twd,
            "hosts": self.hosts,
            "nvr": self.nvr,
            "inventory": self.inventory,
            "results": [item.to_dict() for item in self.results],
        }


@dataclass
class InstallResult:
    twd: str
    hosts: str
    inventory: str
    rpm_dir: str
    remote_dir: str
    rpms: list[str] = field(default_factory=list)
    copy: list[HostModuleResult] = field(default_factory=list)
    install: list[HostModuleResult] = field(default_factory=list)
    dry_run: bool = False
    argv: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "twd": self.twd,
            "hosts": self.hosts,
            "inventory": self.inventory,
            "rpm_dir": self.rpm_dir,
            "remote_dir": self.remote_dir,
            "rpms": self.rpms,
            "copy": [item.to_dict() for item in self.copy],
            "install": [item.to_dict() for item in self.install],
            "dry_run": self.dry_run,
            "argv": self.argv,
        }


def default_inventory(twd: Path) -> Path:
    return twd / DEFAULT_INVENTORY


def list_rpm_files(rpm_dir: Path) -> list[Path]:
    if not rpm_dir.is_dir():
        raise TwdRpmError(f"rpm dir not found: {rpm_dir}")
    rpms = sorted(
        path for path in rpm_dir.glob("*.rpm") if path.is_file() and not is_debug_rpm(path.name)
    )
    if not rpms:
        raise TwdRpmError(f"no binary RPMs in {rpm_dir}")
    return rpms


def ansible_cmd(
    inventory: Path,
    hosts: str,
    module: str,
    args: str,
    *,
    become: bool = True,
) -> list[str]:
    """Build an ansible ad-hoc command. *hosts* is a group or host pattern."""
    cmd = ["ansible", "-i", str(inventory), hosts]
    if become:
        cmd.append("-b")
    cmd.extend(["-m", module, "-a", args])
    return cmd


def parse_ansible_json(stdout: str) -> dict:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start < 0 or end < start:
        raise TwdRpmError(f"ansible did not emit JSON:\n{stdout}")
    try:
        payload = json.loads(stdout[start : end + 1])
    except json.JSONDecodeError as exc:
        raise TwdRpmError(f"ansible JSON parse failed: {exc}\n{stdout}") from exc
    if not isinstance(payload, dict):
        raise TwdRpmError("ansible JSON was not an object")
    return payload


def iter_host_results(payload: dict) -> list[HostModuleResult]:
    results: list[HostModuleResult] = []
    for play in payload.get("plays") or []:
        for task in play.get("tasks") or []:
            hosts = task.get("hosts") or {}
            for host, data in hosts.items():
                if not isinstance(data, dict):
                    continue
                results.append(
                    HostModuleResult(
                        host=host,
                        rc=data.get("rc"),
                        stdout=data.get("stdout") or "",
                        stderr=data.get("stderr") or "",
                        failed=bool(data.get("failed")),
                        unreachable=bool(data.get("unreachable")),
                        changed=bool(data.get("changed")),
                    )
                )
    return results


def run_ansible(cmd: list[str], *, timeout: float = 300) -> list[HostModuleResult]:
    env = os.environ.copy()
    env["ANSIBLE_STDOUT_CALLBACK"] = "json"
    env["ANSIBLE_LOAD_CALLBACK_PLUGINS"] = "1"
    env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise TwdRpmError("ansible not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise TwdRpmError(f"ansible timed out: {' '.join(cmd)}") from exc
    stdout = proc.stdout or ""
    if not stdout.strip():
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        raise TwdRpmError(f"ansible failed: {err}")
    try:
        payload = parse_ansible_json(stdout)
    except TwdRpmError:
        err = (proc.stderr or stdout).strip()
        raise TwdRpmError(f"ansible failed: {err}") from None
    return iter_host_results(payload)


def query_rpms(
    twd: Path,
    nvr: str,
    *,
    hosts: str = DEFAULT_HOSTS,
    inventory: Path | None = None,
    packages: list[str] | None = None,
    become: bool = True,
    runner=run_ansible,
) -> QueryResult:
    """rpm -q on *hosts* (default client) and compare to *nvr*."""
    twd = require_twd(twd)
    wanted = parse_nvr(nvr)
    inv = (inventory or default_inventory(twd)).expanduser().resolve()
    if not inv.is_file():
        raise TwdRpmError(f"inventory not found (run te --upto prep): {inv}")
    names = list(packages) if packages else [wanted.name]
    if wanted.name not in names:
        names.insert(0, wanted.name)
    args = f"rpm -q --qf '{RPM_QF}' " + " ".join(names)
    cmd = ansible_cmd(inv, hosts, "shell", args, become=become)
    raw = runner(cmd)
    results: list[QueryHost] = []
    for item in raw:
        lines = [line.strip() for line in item.stdout.splitlines() if line.strip()]
        installed_lines = [line for line in lines if "is not installed" not in line]
        primary = next(
            (line for line in installed_lines if line.startswith(wanted.name + "-")), None
        )
        if primary is None and installed_lines:
            primary = installed_lines[0]
        relation = "missing"
        if item.unreachable:
            relation = "missing"
        else:
            relation = nvr_relation(primary, wanted.nvr)
        results.append(
            QueryHost(
                host=item.host,
                relation=relation,
                installed=primary,
                packages=installed_lines,
                rc=item.rc,
                unreachable=item.unreachable,
            )
        )
    return QueryResult(
        twd=str(twd),
        hosts=hosts,
        nvr=wanted.nvr,
        inventory=str(inv),
        results=results,
    )


def install_rpms(
    twd: Path,
    *,
    hosts: str = DEFAULT_HOSTS,
    inventory: Path | None = None,
    rpm_dir: Path | None = None,
    remote_dir: str = DEFAULT_REMOTE_DIR,
    become: bool = True,
    dry_run: bool = False,
    runner=run_ansible,
) -> InstallResult:
    """Copy brew-rpms/ and dnf install on *hosts* (default client)."""
    twd = require_twd(twd)
    inv = (inventory or default_inventory(twd)).expanduser().resolve()
    if not inv.is_file():
        raise TwdRpmError(f"inventory not found (run te --upto prep): {inv}")
    local = (rpm_dir or (twd / "brew-rpms")).expanduser().resolve()
    rpms = list_rpm_files(local)
    src = str(local) + "/"
    dest = remote_dir.rstrip("/") + "/"
    copy_cmd = ansible_cmd(
        inv,
        hosts,
        "copy",
        f"src={src} dest={dest}",
        become=become,
    )
    install_cmd = ansible_cmd(
        inv,
        hosts,
        "shell",
        f"dnf install -y {dest}*.rpm",
        become=become,
    )
    result = InstallResult(
        twd=str(twd),
        hosts=hosts,
        inventory=str(inv),
        rpm_dir=str(local),
        remote_dir=dest,
        rpms=[path.name for path in rpms],
        dry_run=dry_run,
        argv=[copy_cmd, install_cmd],
    )
    if dry_run:
        return result
    result.copy = runner(copy_cmd)
    if any(item.failed or item.unreachable for item in result.copy):
        raise TwdRpmError("ansible copy failed; see --json copy results")
    result.install = runner(install_cmd)
    if any(item.failed or item.unreachable for item in result.install):
        raise TwdRpmError("dnf install failed; see --json install results")
    return result


def _twd_rpm_options(fn):
    fn = click.option(
        "--json",
        "as_json",
        is_flag=True,
        help="Emit machine-readable JSON",
    )(fn)
    fn = click.option(
        "--become/--no-become",
        default=True,
        show_default=True,
        help="ansible -b (root)",
    )(fn)
    fn = click.option(
        "-i",
        "--inventory",
        type=click.Path(path_type=Path, dir_okay=False),
        default=None,
        help="Ansible inventory (default: <twd>/config/test.inventory.yaml)",
    )(fn)
    fn = click.option(
        "--hosts",
        "--limit",
        default=DEFAULT_HOSTS,
        show_default=True,
        help="Ansible group or host pattern (client, ipa, dns, all, …)",
    )(fn)
    fn = click.option(
        "--twd",
        type=click.Path(path_type=Path, file_okay=False),
        default=".",
        show_default=True,
        help="twd or campaign directory",
    )(fn)
    return fn


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Query or install RPMs on twd inventory hosts.

    --hosts defaults to the client group. Pass ipa, dns, or a host pattern
    to target other machines.
    """


@cli.command("query")
@_twd_rpm_options
@click.option("--nvr", required=True, help="Wanted NVR (Fixed in Build)")
@click.option(
    "--package",
    "packages",
    multiple=True,
    help="Extra rpm -q names (default: NVR name)",
)
def query_cmd(
    twd: Path,
    hosts: str,
    inventory: Path | None,
    become: bool,
    as_json: bool,
    nvr: str,
    packages: tuple[str, ...],
) -> None:
    """Compare installed RPM to NVR on --hosts (older/same/newer/missing)."""
    try:
        result = query_rpms(
            twd,
            nvr,
            hosts=hosts,
            inventory=inventory,
            packages=list(packages) or None,
            become=become,
        )
    except (TwdRpmError, NvrError, ValueError) as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 1 if isinstance(exc, TwdRpmError) else 2
        raise err from exc
    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return
    for item in result.results:
        installed = item.installed or "(not installed)"
        click.echo(f"{item.host}: {item.relation}  {installed}")


@cli.command("install")
@_twd_rpm_options
@click.option(
    "--rpm-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Local RPM dir (default: <twd>/brew-rpms)",
)
@click.option(
    "--remote-dir",
    default=DEFAULT_REMOTE_DIR,
    show_default=True,
    help="Remote directory to copy RPMs into",
)
@click.option("-n", "--dry-run", is_flag=True, help="Print ansible commands only")
def install_cmd(
    twd: Path,
    hosts: str,
    inventory: Path | None,
    become: bool,
    as_json: bool,
    rpm_dir: Path | None,
    remote_dir: str,
    dry_run: bool,
) -> None:
    """Copy brew-rpms and dnf install on --hosts (default: client)."""
    try:
        result = install_rpms(
            twd,
            hosts=hosts,
            inventory=inventory,
            rpm_dir=rpm_dir,
            remote_dir=remote_dir,
            become=become,
            dry_run=dry_run,
        )
    except (TwdRpmError, ValueError) as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 1 if isinstance(exc, TwdRpmError) else 2
        raise err from exc
    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return
    if result.dry_run:
        for argv in result.argv:
            click.echo(" ".join(argv))
        return
    click.echo(f"hosts: {result.hosts}")
    click.echo(f"rpms: {len(result.rpms)}")
    for name in result.rpms:
        click.echo(f"  {name}")
    click.echo("install: ok")


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="twd-rpm", standalone_mode=False)
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
