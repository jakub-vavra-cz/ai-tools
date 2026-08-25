#!/usr/bin/env python3
"""Download brewroot binary RPMs for a Fixed in Build NVR into twd/brew-rpms."""

from __future__ import annotations

import json
import os
import platform
import re
import ssl
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin
from urllib.request import Request, urlopen

import click

from ai_tools.clean_twd import require_twd
from ai_tools.nvr import NVR, NvrError, parse_nvr

DEFAULT_BREWROOT = "https://download-01.beak-001.prod.iad2.dc.redhat.com/brewroot/packages"
SKIP_ARCH_DIRS = frozenset({"src", "data"})
DEBUG_SUBSTR = ("debuginfo", "debugsource")
HREF_RE = re.compile(r"""href=["']([^"'#]+)["']""", re.IGNORECASE)
USER_AGENT = "brew-fetch-nvr/0.1"


class BrewFetchError(RuntimeError):
    """Fatal brewroot fetch error."""


@dataclass
class BrewFetchResult:
    """Files downloaded (and skipped) for one NVR."""

    nvr: str
    url: str
    dest: str
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    arches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def brewroot_from_env() -> str:
    return os.environ.get("BREWROOT_PACKAGES") or DEFAULT_BREWROOT


def ca_bundle_from_env() -> str | None:
    return os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")


def default_arch() -> str:
    machine = platform.machine()
    if machine == "amd64":
        return "x86_64"
    return machine or "x86_64"


def is_debug_rpm(name: str) -> bool:
    lower = name.lower()
    return any(token in lower for token in DEBUG_SUBSTR)


def nvr_dir_url(nvr: NVR, base: str) -> str:
    root = base.rstrip("/")
    return f"{root}/{nvr.name}/{nvr.version}/{nvr.release}/"


def list_hrefs(html: str) -> list[str]:
    """Directory-listing hrefs, skipping parent/sort links."""
    found: list[str] = []
    for raw in HREF_RE.findall(html):
        href = unquote(raw.split("?", 1)[0]).strip()
        if href.startswith("./"):
            href = href[2:]
        if not href or href in (".", "..", "../"):
            continue
        if href.startswith("?"):
            continue
        if href.startswith("http://") or href.startswith("https://") or href.startswith("/"):
            trailing = href.endswith("/")
            href = href.rstrip("/").rsplit("/", 1)[-1]
            if trailing and href:
                href += "/"
        if not href or href in (".", ".."):
            continue
        found.append(href)
    return found


def _ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ca_bundle and Path(ca_bundle).is_file():
        ctx.load_verify_locations(ca_bundle)
    return ctx


def fetch_bytes(url: str, *, ca_bundle: str | None = None, timeout: float = 120) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, context=_ssl_context(ca_bundle), timeout=timeout) as resp:
            return resp.read()
    except HTTPError as exc:
        if exc.code == 404:
            raise BrewFetchError(f"not found: {url}") from exc
        raise BrewFetchError(f"HTTP {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise BrewFetchError(f"failed to fetch {url}: {exc}") from exc


def fetch_text(url: str, *, ca_bundle: str | None = None) -> str:
    return fetch_bytes(url, ca_bundle=ca_bundle).decode("utf-8", errors="replace")


def select_arch_dirs(entries: list[str], arches: list[str]) -> list[str]:
    """Keep requested arch dirs plus noarch; drop src/data."""
    wanted = {arch.rstrip("/") for arch in arches}
    wanted.add("noarch")
    dirs: list[str] = []
    for entry in entries:
        if not entry.endswith("/"):
            continue
        name = entry.rstrip("/")
        if name in SKIP_ARCH_DIRS:
            continue
        if name in wanted:
            dirs.append(name)
    return dirs


def rpm_names_from_listing(entries: list[str]) -> tuple[list[str], list[str]]:
    """Split listing into keep vs debuginfo/debugsource skip lists."""
    keep: list[str] = []
    skipped: list[str] = []
    for entry in entries:
        if entry.endswith("/") or not entry.endswith(".rpm"):
            continue
        name = entry.rsplit("/", 1)[-1]
        if is_debug_rpm(name):
            skipped.append(name)
        else:
            keep.append(name)
    return keep, skipped


def download_rpm(
    url: str,
    dest: Path,
    *,
    ca_bundle: str | None = None,
    force: bool = False,
) -> bool:
    """Write url to dest. Skip when dest exists unless force. True if written."""
    if dest.is_file() and not force:
        return False
    data = fetch_bytes(url, ca_bundle=ca_bundle)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return True


def fetch_nvr(
    nvr: str,
    *,
    dest: Path,
    arches: list[str] | None = None,
    base_url: str | None = None,
    ca_bundle: str | None = None,
    force: bool = False,
) -> BrewFetchResult:
    """Download binary RPMs for *nvr* into dest (client arch + noarch)."""
    parsed = parse_nvr(nvr)
    base = (base_url or brewroot_from_env()).rstrip("/")
    root_url = nvr_dir_url(parsed, base)
    arch_list = list(arches) if arches else [default_arch()]
    html = fetch_text(root_url, ca_bundle=ca_bundle)
    arch_dirs = select_arch_dirs(list_hrefs(html), arch_list)
    if not arch_dirs:
        raise BrewFetchError(f"no matching arch dirs at {root_url} (wanted {arch_list}+noarch)")

    dest = dest.expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    skipped: list[str] = []
    for arch in arch_dirs:
        listing_url = urljoin(root_url, f"{arch}/")
        names, skip = rpm_names_from_listing(
            list_hrefs(fetch_text(listing_url, ca_bundle=ca_bundle))
        )
        skipped.extend(skip)
        for name in names:
            path = dest / name
            wrote = download_rpm(
                urljoin(listing_url, name),
                path,
                ca_bundle=ca_bundle,
                force=force,
            )
            if wrote or path.is_file():
                downloaded.append(name)

    return BrewFetchResult(
        nvr=parsed.nvr,
        url=root_url,
        dest=str(dest),
        downloaded=sorted(set(downloaded)),
        skipped=sorted(set(skipped)),
        arches=arch_dirs,
    )


def resolve_dest(twd: Path | None, dest: Path | None) -> Path:
    if dest is not None:
        return dest.expanduser().resolve()
    if twd is None:
        raise BrewFetchError("pass --twd or --dest")
    return require_twd(twd) / "brew-rpms"


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("nvr")
@click.option(
    "--twd",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="twd or campaign; dest defaults to <twd>/brew-rpms",
)
@click.option(
    "--dest",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Directory to write RPMs (default: <twd>/brew-rpms)",
)
@click.option(
    "--arch",
    "arches",
    multiple=True,
    help="Arch dir to fetch (repeatable; default: this machine, plus noarch)",
)
@click.option(
    "--base-url",
    default=None,
    help=f"Brew packages root (default: $BREWROOT_PACKAGES or {DEFAULT_BREWROOT})",
)
@click.option("--force", is_flag=True, help="Re-download even if the file exists")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
def cli(
    nvr: str,
    twd: Path | None,
    dest: Path | None,
    arches: tuple[str, ...],
    base_url: str | None,
    force: bool,
    as_json: bool,
) -> None:
    """Download brewroot RPMs for NVR (client arch + noarch).

    Skips src/, data/, *debuginfo*, *debugsource*. Writes twd/brew-rpms/.
    """
    try:
        out = fetch_nvr(
            nvr,
            dest=resolve_dest(twd, dest),
            arches=list(arches) if arches else None,
            base_url=base_url,
            ca_bundle=ca_bundle_from_env(),
            force=force,
        )
    except (BrewFetchError, NvrError, ValueError) as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 1 if isinstance(exc, BrewFetchError) else 2
        raise err from exc

    if as_json:
        click.echo(json.dumps(out.to_dict(), indent=2))
    else:
        click.echo(f"nvr: {out.nvr}")
        click.echo(f"url: {out.url}")
        click.echo(f"dest: {out.dest}")
        click.echo(f"arches: {', '.join(out.arches)}")
        click.echo(f"downloaded: {len(out.downloaded)}")
        for name in out.downloaded:
            click.echo(f"  {name}")
        if out.skipped:
            click.echo(f"skipped: {len(out.skipped)}")
            for name in out.skipped:
                click.echo(f"  {name}")


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="brew-fetch-nvr", standalone_mode=False)
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
