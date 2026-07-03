"""git-stats CLI."""

from __future__ import annotations

import argparse
import sys

from git_stats import config
from git_stats.categories import SUBCOMMAND_PRESETS, normalize_categories
from git_stats.dates import default_activity_date, parse_activity_date
from git_stats.done_service import done_fetch
from git_stats.output import print_done, print_host_errors, print_json, print_queue
from git_stats.service import queue_fetch

_HOSTS = frozenset({"github", "gitlab"})


def _resolve_categories(args: argparse.Namespace) -> list[str]:
    if args.categories:
        return normalize_categories(args.categories)
    preset = SUBCOMMAND_PRESETS.get(args.subcommand_preset, None)
    if preset:
        return list(preset)
    return normalize_categories(None)


def _run_done(args: argparse.Namespace) -> int:
    try:
        activity_date = parse_activity_date(args.date)
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 2

    hosts: list[str] | None = None
    if args.host:
        hosts = [args.host]

    result = done_fetch(
        activity_date=activity_date,
        hosts=hosts,
        gitlab_host=args.gitlab_host,
        max_pages=args.max_pages,
    )

    if result.get("ok") is False:
        print(result.get("error", "unknown error"), file=sys.stderr)
        if args.json:
            print_json(result)
        return 2

    if args.json:
        print_json(result)
    elif not args.quiet:
        print_done(result, quiet=args.quiet)

    if not args.json or not args.quiet:
        print_host_errors(result)

    requested_hosts = hosts or ["github", "gitlab"]
    host_failures = [
        name for name in requested_hosts if (result.get(name) or {}).get("ok") is False
    ]
    if host_failures and len(host_failures) == len(requested_hosts):
        return 1
    return 0


def _run(args: argparse.Namespace) -> int:
    try:
        categories = _resolve_categories(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    hosts: list[str] | None = None
    if args.host:
        hosts = [args.host]

    result = queue_fetch(
        categories=categories,
        hosts=hosts,
        github_limit=args.github_limit,
        gitlab_limit=args.gitlab_limit,
        include_drafts=args.include_drafts,
        gitlab_host=args.gitlab_host,
        dirs=args.dirs or None,
        include_all=args.all,
    )

    if result.get("ok") is False:
        print(result.get("error", "unknown error"), file=sys.stderr)
        if args.json:
            print_json(result)
        return 2

    if args.json:
        print_json(result)
    elif not args.quiet:
        print_queue(result, quiet=args.quiet)

    if not args.json or not args.quiet:
        print_host_errors(result)

    requested_hosts = hosts or ["github", "gitlab"]
    host_failures = [
        name for name in requested_hosts if (result.get(name) or {}).get("ok") is False
    ]
    if host_failures and len(host_failures) == len(requested_hosts):
        return 1
    return 0


def _parse_categories(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--categories",
        type=_parse_categories,
        help="comma-separated category ids (overrides subcommand preset)",
    )
    parser.add_argument(
        "--github-limit",
        type=int,
        default=config.default_github_limit(),
        help="max GitHub PRs per category",
    )
    parser.add_argument(
        "--gitlab-limit",
        type=int,
        default=config.default_gitlab_limit(),
        help="max GitLab MRs per category",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        default=config.default_include_drafts(),
        help="include GitLab draft/WIP in review_requested lists",
    )
    parser.add_argument(
        "--gitlab-host",
        default=config.default_gitlab_host(),
        help="GitLab hostname for glab api",
    )
    parser.add_argument(
        "--dir",
        action="append",
        dest="dirs",
        default=[],
        metavar="NAME",
        help="limit repo-scan fallback to top-level GIT_PATH directory (repeatable)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=config.default_include_all(),
        help="include closed and merged PRs/MRs in addition to open",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON on stdout")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress human report")


def _add_done_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--date",
        default=default_activity_date().isoformat(),
        help="activity date in ISO 8601 notation YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=config.default_done_max_pages(),
        help="max event API pages per host (100 events per page)",
    )
    parser.add_argument(
        "--gitlab-host",
        default=config.default_gitlab_host(),
        help="GitLab hostname for glab api",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON on stdout")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress human report")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git-stats",
        description="GitHub/GitLab PR/MR review and authored queues",
    )
    parser.add_argument(
        "tail",
        nargs="*",
        help="optional: reviews | authored [changes-requested|no-reviewer] | done | github | gitlab",
    )
    _add_common_options(parser)
    parser.set_defaults(subcommand_preset="", host=None, func=_run)
    return parser


def _resolve_tail(tail: list[str]) -> tuple[str, str | None]:
    preset = ""
    host: str | None = None
    idx = 0
    if tail:
        first = tail[0].lower()
        if first == "reviews":
            preset = "reviews"
            idx = 1
        elif first == "done":
            preset = "done"
            idx = 1
        elif first == "authored":
            idx = 1
            if len(tail) > 1 and tail[1].lower() in {
                "changes-requested",
                "changes_requested",
                "no-reviewer",
                "no_reviewer",
            }:
                second = tail[1].lower().replace("_", "-")
                preset = f"authored/{second}"
                idx = 2
            else:
                preset = "authored"
    if idx < len(tail):
        maybe_host = tail[idx].lower()
        if maybe_host in _HOSTS:
            host = maybe_host
    return preset, host


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    host: str | None = None
    preset = ""
    if argv and argv[0] not in ("-h", "--help") and not argv[0].startswith("-"):
        preset, host = _resolve_tail(argv)
        consumed = 1
        if preset == "reviews":
            consumed = 1
        elif preset == "done":
            consumed = 1
        elif preset.startswith("authored"):
            consumed = 2 if "/" in preset else 1
        if host is not None:
            consumed += 1
        argv = argv[consumed:]

    if preset == "done":
        parser = argparse.ArgumentParser(
            prog="git-stats done",
            description="GitHub/GitLab updates for a calendar day",
        )
        _add_done_options(parser)
        parser.set_defaults(host=host, func=_run_done)
        args = parser.parse_args(argv)
        return args.func(args)

    parser = build_parser()
    args = parser.parse_args(argv)
    args.subcommand_preset = preset
    args.host = host
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
