"""worklog CLI."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from worklog import config
from worklog.output import print_activity, print_json
from worklog.service import last_workday_result, workspace_activity

_UNSET = object()


def _add_scan_parser(sub: argparse.ArgumentParser, *, include_workday: bool) -> None:
    sub.add_argument(
        "workspaces",
        nargs="*",
        metavar="WORKSPACE",
        help="workspace root (repeatable; default: GIT_PATH or ~/git)",
    )
    if include_workday:
        sub.add_argument(
            "--date",
            "--workday",
            dest="activity_date",
            metavar="DATE",
            help="activity date in ISO 8601 notation YYYY-MM-DD (default: last workday)",
        )
    sub.add_argument(
        "--max-repos",
        type=int,
        default=config.default_max_repos(),
        help="global cap on active repos deep-scanned",
    )
    sub.add_argument(
        "--max-files",
        type=int,
        default=config.default_max_files(),
        help="max files returned per repo",
    )
    sub.add_argument(
        "--max-commits",
        type=int,
        default=config.default_max_commits(),
        help="max commits per repo (0 = skip git)",
    )
    sub.add_argument(
        "--recent-repos",
        type=int,
        default=config.default_recent_repos(),
        help="recent top-level dirs per workspace for fallback",
    )
    sub.add_argument(
        "--include-scratch",
        action="store_true",
        default=config.default_include_scratch(),
        help="include @* scratch directories",
    )
    sub.add_argument("--json", action="store_true", help="emit JSON on stdout")
    sub.add_argument("-q", "--quiet", action="store_true", help="suppress human report on stdout")


def _run_scan(args: argparse.Namespace, *, workday: date | str | None | object = _UNSET) -> int:
    resolved_workday: date | str | None
    if workday is _UNSET:
        resolved_workday = getattr(args, "activity_date", None)
    else:
        resolved_workday = workday  # type: ignore[assignment]

    result = workspace_activity(
        workspaces=args.workspaces or None,
        workday=resolved_workday,
        max_repos=args.max_repos,
        max_files_per_repo=args.max_files,
        max_commits_per_repo=args.max_commits,
        recent_repos_count=args.recent_repos,
        include_scratch_dirs=args.include_scratch,
    )

    if result.get("ok") is False:
        print(result.get("error", "unknown error"), file=sys.stderr)
        if args.json:
            print_json(result)
        return 2

    if not result.get("workspaces"):
        print("no valid workspace directories", file=sys.stderr)
        return 2

    if args.json:
        print_json(result)
    else:
        print_activity(result, quiet=args.quiet)

    if result.get("errors"):
        for err in result["errors"]:
            print(
                f"worklog: skipped {err.get('workspace')}: {err.get('message')}",
                file=sys.stderr,
            )

    return 0


def _cmd_activity(args: argparse.Namespace) -> int:
    return _run_scan(args)


def _cmd_today(args: argparse.Namespace) -> int:
    return _run_scan(args, workday=date.today().isoformat())


def _cmd_last_workday(args: argparse.Namespace) -> int:
    try:
        ref: date | str | None = args.reference_date
        result = last_workday_result(reference_date=ref)
    except ValueError as exc:
        print(f"invalid reference date: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print_json(result)
    else:
        print(result["workday"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worklog",
        description="Git workspace activity for daily agendas",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    activity = sub.add_parser(
        "activity",
        help="scan workspace activity for a workday (default: last Mon–Fri workday)",
    )
    _add_scan_parser(activity, include_workday=True)
    activity.set_defaults(func=_cmd_activity)

    today = sub.add_parser(
        "today",
        help="scan workspace activity for today (same options as activity)",
    )
    _add_scan_parser(today, include_workday=False)
    today.set_defaults(func=_cmd_today)

    last_day = sub.add_parser("last-workday", help="print previous Mon–Fri date")
    last_day.add_argument(
        "--reference-date",
        metavar="DATE",
        help="ISO date to measure from (default: today)",
    )
    last_day.add_argument("--json", action="store_true")
    last_day.set_defaults(func=_cmd_last_workday)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
