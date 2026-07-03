#!/usr/bin/env python3
"""Pull Jenkins IdM-CI artifacts and scaffold an @TESTRUNS campaign twd."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ai_tools.jenkins_artifacts import (
    PullResult,
    ca_bundle_from_env,
    jenkins_auth_from_env,
    parse_build_url,
    pull_jenkins_artifacts,
)

METADATA_CANDIDATES = (
    "metadata.mod.yaml",
    "metadata.orig.yaml",
    "config/metadata.yaml",
)

REFERENCE_ARTIFACTS = (
    "runner.log",
    "junit.xml",
    "pytests_junit.xml",
    "pytest-run.rc",
    "mrack.log",
    "artifacts_url.txt",
)


class JenkinsToTestrunError(RuntimeError):
    """Invalid input or missing metadata for campaign setup."""


@dataclass
class TestrunResult:
    """Outcome of jenkins-to-testrun."""

    campaign: str
    twd: Path
    pull: PullResult
    metadata_path: Path
    copied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "campaign": self.campaign,
            "twd": str(self.twd),
            "metadata_path": str(self.metadata_path),
            "copied": self.copied,
            "pull": self.pull.to_dict(),
        }


def git_path_from_env() -> Path:
    return Path(os.environ.get("GIT_PATH", "~/git")).expanduser().resolve()


def slugify_job_part(part: str) -> str:
    part = part.lower()
    part = re.sub(r"[^a-z0-9]+", "-", part)
    return part.strip("-")


def campaign_name_from_build(build_url: str, build_number: int) -> str:
    """Derive a short @TESTRUNS campaign name from a Jenkins build URL."""
    from urllib.parse import urlparse

    path = urlparse(build_url).path.rstrip("/")
    parts = [p for p in path.split("/") if p and p != "job"]
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    slug_parts = parts[-2:] if len(parts) >= 2 else parts
    slug = "-".join(filter(None, (slugify_job_part(p) for p in slug_parts)))
    if not slug:
        slug = "build"
    return f"jenkins-{slug}-{build_number}"


def find_metadata_source(pull_dir: Path) -> Path:
    for rel in METADATA_CANDIDATES:
        path = pull_dir / rel
        if path.is_file():
            return path
    raise JenkinsToTestrunError(
        f"No metadata in {pull_dir} (tried: {', '.join(METADATA_CANDIDATES)})",
    )


def copy_reference_artifacts(pull_dir: Path, twd: Path) -> list[str]:
    copied: list[str] = []
    for rel in REFERENCE_ARTIFACTS:
        src = pull_dir / rel
        if not src.is_file():
            continue
        dest = twd / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(rel)
    logs_src = pull_dir / "logs"
    if logs_src.is_dir():
        logs_dest = twd / "logs"
        if logs_dest.exists():
            shutil.rmtree(logs_dest)
        shutil.copytree(logs_src, logs_dest)
        copied.append("logs/")
    return copied


def jenkins_to_testrun(
    *,
    build_url: str | None = None,
    artifacts_url: str | None = None,
    campaign: str | None = None,
    git_path: Path | None = None,
    pull_output: Path | None = None,
    keep_pull_dir: bool = False,
    force: bool = False,
    copy_references: bool = True,
    auth: tuple[str, str] | None = None,
    ca_bundle: str | None = None,
) -> TestrunResult:
    if not build_url and not artifacts_url:
        raise JenkinsToTestrunError("build_url or artifacts_url is required")

    git_root = (git_path or git_path_from_env()).resolve()
    pull_dir = pull_output
    if pull_dir is None:
        pull_dir = git_root / ".cache" / "jenkins-pull"
        if build_url:
            build = parse_build_url(build_url)
            pull_dir = pull_dir / campaign_name_from_build(
                build.build_url,
                build.build_number,
            )

    pull = pull_jenkins_artifacts(
        build_url=build_url,
        artifacts_url=artifacts_url,
        output_dir=pull_dir,
        get_console=bool(build_url),
        download_artifacts=True,
        decompress_after=True,
        auth=auth,
        ca_bundle=ca_bundle,
    )

    if campaign is None:
        if pull.build_url is None or pull.build_number is None:
            raise JenkinsToTestrunError(
                "campaign name is required when using --artifacts-url without build_url",
            )
        campaign = campaign_name_from_build(pull.build_url, pull.build_number)

    twd = git_root / "@TESTRUNS" / campaign / "twd"
    metadata_dest = twd / "metadata.yaml"
    if metadata_dest.exists() and not force:
        raise JenkinsToTestrunError(
            f"{metadata_dest} already exists; pass --force to overwrite",
        )

    twd.mkdir(parents=True, exist_ok=True)
    metadata_src = find_metadata_source(pull.output_dir)
    shutil.copy2(metadata_src, metadata_dest)

    copied: list[str] = []
    if copy_references:
        copied = copy_reference_artifacts(pull.output_dir, twd)

    if not keep_pull_dir and pull_output is None and pull.output_dir.is_dir():
        shutil.rmtree(pull.output_dir, ignore_errors=True)

    return TestrunResult(
        campaign=campaign,
        twd=twd,
        pull=pull,
        metadata_path=metadata_dest,
        copied=copied,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Jenkins IdM-CI artifacts (with automatic log decompression) "
            "and create an @TESTRUNS campaign twd with metadata.yaml."
        ),
    )
    parser.add_argument(
        "build_url",
        nargs="?",
        help="Jenkins build URL (e.g. https://jenkins…/job/…/123/)",
    )
    parser.add_argument(
        "-c",
        "--campaign",
        help="@TESTRUNS campaign directory name (default: derived from build URL)",
    )
    parser.add_argument(
        "--git-path",
        type=Path,
        help="Git workspace root (default: $GIT_PATH or ~/git)",
    )
    parser.add_argument(
        "-a",
        "--artifacts-url",
        help="Artifact server base URL (skip Jenkins console when build_url omitted)",
    )
    parser.add_argument(
        "--pull-dir",
        type=Path,
        help="Keep pulled artifacts at this path instead of a temp cache dir",
    )
    parser.add_argument(
        "--keep-pull-dir",
        action="store_true",
        help="Do not delete the temporary pull cache directory",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Copy only metadata.yaml (skip runner.log, junit, logs/)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing twd/metadata.yaml",
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
        result = jenkins_to_testrun(
            build_url=args.build_url,
            artifacts_url=args.artifacts_url,
            campaign=args.campaign,
            git_path=args.git_path,
            pull_output=args.pull_dir,
            keep_pull_dir=args.keep_pull_dir or bool(args.pull_dir),
            force=args.force,
            copy_references=not args.metadata_only,
            auth=auth,
            ca_bundle=ca_bundle,
        )
    except JenkinsToTestrunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif not args.quiet:
        print(f"campaign: {result.campaign}")
        print(f"twd: {result.twd}")
        print(f"metadata: {result.metadata_path}")
        for rel in result.copied:
            print(f"copied: {rel}")
        if result.pull.artifacts_url:
            print(f"artifacts: {result.pull.artifacts_url}")
        print()
        print("Next:")
        print(f"  cd {result.twd}")
        print("  te --upto prep metadata.yaml")
        print("  te --phase test metadata.yaml")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
