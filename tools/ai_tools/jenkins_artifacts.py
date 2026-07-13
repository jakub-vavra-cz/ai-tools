#!/usr/bin/env python3
"""Fetch Jenkins console output and IdM-CI job artifacts from the artifact server."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import re
import ssl
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

GZIP_MAGIC = b"\x1f\x8b"

RD_JR_ARTIFACTS_URL_RE = re.compile(
    r"RD_JR_ARTIFACTS_URL=(https?://\S+)",
)
ARTIFACTS_URL_FALLBACK_RE = re.compile(
    r"Artifacts url: (https?://\S+)",
)

DEFAULT_ARTIFACT_PATHS = (
    "metadata.mod.yaml",
    "metadata.orig.yaml",
    "config/metadata.yaml",
    "pytest-run.rc",
    "junit.xml",
    "pytests_junit.xml",
    "runner.log",
    "mrack.log",
    "artifacts.html",
    "config/test.inventory.yaml",
    "config/pytest-mh.yaml",
    "logs/pytests_pytest-run.log",
    "logs/pytest-run.log",
)


@dataclass(frozen=True)
class JenkinsBuild:
    build_url: str
    build_number: int


@dataclass
class PullResult:
    build_url: str | None
    build_number: int | None
    artifacts_url: str | None
    output_dir: Path
    console_path: Path | None = None
    downloaded: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["output_dir"] = str(self.output_dir)
        if self.console_path is not None:
            data["console_path"] = str(self.console_path)
        return data


def parse_build_url(url: str) -> JenkinsBuild:
    """Parse a Jenkins build URL into base URL and build number."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Not an http(s) URL: {url}")
    path = parsed.path.rstrip("/")
    if not path:
        raise ValueError(f"Missing job path in URL: {url}")
    build_part = path.rsplit("/", 1)[-1]
    if not build_part.isdigit():
        raise ValueError(
            f"URL must end with a numeric build number, got: {build_part!r}",
        )
    build_number = int(build_part)
    job_path = path.rsplit("/", 1)[0]
    build_url = f"{parsed.scheme}://{parsed.netloc}{job_path}/{build_number}/"
    return JenkinsBuild(build_url=build_url, build_number=build_number)


def normalize_artifacts_url(url: str) -> str:
    url = url.strip()
    if not url.endswith("/"):
        url += "/"
    return url


def extract_artifacts_url(console_text: str) -> str | None:
    """Return RD_JR_ARTIFACTS_URL from Jenkins console output."""
    matches = RD_JR_ARTIFACTS_URL_RE.findall(console_text)
    if matches:
        return normalize_artifacts_url(matches[-1])
    matches = ARTIFACTS_URL_FALLBACK_RE.findall(console_text)
    if matches:
        return normalize_artifacts_url(matches[-1])
    return None


def jenkins_auth_from_env() -> tuple[str, str] | None:
    username = os.environ.get("JENKINS_USERNAME")
    password = os.environ.get("JENKINS_PASSWORD")
    if username and password:
        return username, password
    return None


def ca_bundle_from_env() -> str | None:
    return os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")


def _ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ca_bundle and Path(ca_bundle).is_file():
        ctx.load_verify_locations(ca_bundle)
    return ctx


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def fetch_bytes(
    url: str,
    *,
    auth: tuple[str, str] | None = None,
    ca_bundle: str | None = None,
    timeout: float = 120,
) -> bytes | None:
    headers: dict[str, str] = {}
    if auth is not None:
        headers["Authorization"] = _basic_auth_header(*auth)
    request = Request(url, headers=headers)
    try:
        with urlopen(
            request,
            context=_ssl_context(ca_bundle),
            timeout=timeout,
        ) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except URLError as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


def fetch_console(
    build: JenkinsBuild,
    *,
    auth: tuple[str, str] | None = None,
    ca_bundle: str | None = None,
) -> str:
    console_url = urljoin(build.build_url, "consoleText")
    data = fetch_bytes(console_url, auth=auth, ca_bundle=ca_bundle)
    if data is None:
        raise RuntimeError(f"Console not found: {console_url}")
    return data.decode("utf-8", errors="replace")


def _looks_like_html(data: bytes) -> bool:
    start = data.lstrip()[:32].lower()
    return start.startswith(b"<html") or start.startswith(b"<!doctype")


def _write_payload(data: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if data[:2] == GZIP_MAGIC:
        data = gzip.decompress(data)
    dest.write_bytes(data)


def download_artifact(
    artifacts_url: str,
    relpath: str,
    dest: Path,
    *,
    ca_bundle: str | None = None,
) -> bool:
    """Download one artifact file. Returns True when saved."""
    base = normalize_artifacts_url(artifacts_url)
    relpath = relpath.lstrip("/")

    # S3 artifact server stores gzip at the plain path; legacy uploads may use .gz.
    for suffix in ("", ".gz"):
        url = urljoin(base, f"{relpath}{suffix}")
        data = fetch_bytes(url, ca_bundle=ca_bundle)
        if data is None or _looks_like_html(data):
            continue
        _write_payload(data, dest)
        return True
    return False


def default_output_dir(build: JenkinsBuild | None, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    if build is not None:
        return Path.cwd() / f"jenkins-artifacts-{build.build_number}"
    return Path.cwd() / "jenkins-artifacts"


def pull_jenkins_artifacts(
    *,
    build_url: str | None = None,
    artifacts_url: str | None = None,
    output_dir: Path | None = None,
    artifact_paths: list[str] | None = None,
    get_console: bool = True,
    download_artifacts: bool = True,
    auth: tuple[str, str] | None = None,
    ca_bundle: str | None = None,
) -> PullResult:
    build: JenkinsBuild | None = None
    if build_url:
        build = parse_build_url(build_url)

    out = default_output_dir(build, output_dir)
    out.mkdir(parents=True, exist_ok=True)

    result = PullResult(
        build_url=build.build_url if build else None,
        build_number=build.build_number if build else None,
        artifacts_url=None,
        output_dir=out,
    )

    console_text: str | None = None
    if get_console:
        if build is None:
            raise ValueError("build_url is required to fetch console output")
        console_text = fetch_console(build, auth=auth, ca_bundle=ca_bundle)
        console_path = out / "console.txt"
        console_path.write_text(console_text, encoding="utf-8")
        result.console_path = console_path

    if artifacts_url:
        result.artifacts_url = normalize_artifacts_url(artifacts_url)
    elif console_text is not None:
        result.artifacts_url = extract_artifacts_url(console_text)

    if result.artifacts_url:
        (out / "artifacts_url.txt").write_text(
            result.artifacts_url + "\n",
            encoding="utf-8",
        )

    if download_artifacts and result.artifacts_url:
        paths = artifact_paths or list(DEFAULT_ARTIFACT_PATHS)
        for relpath in paths:
            dest = out / relpath
            if download_artifact(result.artifacts_url, relpath, dest, ca_bundle=ca_bundle):
                result.downloaded.append(relpath)
            else:
                result.missing.append(relpath)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Jenkins console output for an IdM-CI build, extract "
            "RD_JR_ARTIFACTS_URL, and download diagnostic twd artifacts."
        ),
    )
    parser.add_argument(
        "build_url",
        nargs="?",
        help="Jenkins build URL (e.g. https://jenkins…/job/…/123/)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Directory for console and artifacts (default: ./jenkins-artifacts-N)",
    )
    parser.add_argument(
        "-a",
        "--artifacts-url",
        help="Artifact server base URL; skip Jenkins when used without build_url",
    )
    parser.add_argument(
        "--console-only",
        action="store_true",
        help="Fetch console output only; do not download artifacts",
    )
    parser.add_argument(
        "--url-only",
        action="store_true",
        help="Print artifacts URL and exit (requires build_url)",
    )
    parser.add_argument(
        "-f",
        "--file",
        action="append",
        dest="files",
        metavar="PATH",
        help="Artifact relative path to download (repeatable; overrides defaults)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result summary as JSON",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.build_url and not args.artifacts_url:
        print("error: provide build_url and/or --artifacts-url", file=sys.stderr)
        return 1

    auth = jenkins_auth_from_env()
    ca_bundle = ca_bundle_from_env()

    if args.build_url and auth is None:
        print(
            "error: set JENKINS_USERNAME and JENKINS_PASSWORD to fetch console",
            file=sys.stderr,
        )
        return 1

    try:
        if args.url_only:
            if not args.build_url:
                print("error: --url-only requires build_url", file=sys.stderr)
                return 1
            build = parse_build_url(args.build_url)
            console_text = fetch_console(build, auth=auth, ca_bundle=ca_bundle)
            artifacts_url = extract_artifacts_url(console_text)
            if not artifacts_url:
                print(
                    "error: RD_JR_ARTIFACTS_URL not found in console",
                    file=sys.stderr,
                )
                return 1
            print(artifacts_url)
            return 0

        result = pull_jenkins_artifacts(
            build_url=args.build_url,
            artifacts_url=args.artifacts_url,
            output_dir=args.output_dir,
            artifact_paths=args.files,
            get_console=bool(args.build_url),
            download_artifacts=not args.console_only,
            auth=auth,
            ca_bundle=ca_bundle,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif not args.quiet:
        if result.console_path:
            print(f"console: {result.console_path}")
        if result.artifacts_url:
            print(f"artifacts: {result.artifacts_url}")
        for path in result.downloaded:
            print(f"downloaded: {path}")
        for path in result.missing:
            print(f"missing: {path}")

    if args.build_url and not args.console_only and not result.artifacts_url:
        print("error: RD_JR_ARTIFACTS_URL not found in console", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
