"""Human-readable and JSON output."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from git_stats.categories import CATEGORY_LABELS


def print_json(data: dict[str, Any], *, out: TextIO = sys.stdout) -> None:
    json.dump(data, out, indent=2)
    print(file=out)


def print_queue(result: dict[str, Any], *, out: TextIO = sys.stdout, quiet: bool = False) -> None:
    if result.get("ok") is False:
        if not quiet:
            print(result.get("error", "unknown error"), file=sys.stderr)
        return

    categories = result.get("categories") or []
    include_all = bool(result.get("include_all"))
    for index, category in enumerate(categories):
        if index:
            print(file=out)
        print(CATEGORY_LABELS.get(category, category), file=out)
        for host in ("github", "gitlab"):
            host_data = result.get(host)
            if not host_data or category not in host_data:
                continue
            print(f"  {host.capitalize()}", file=out)
            items = host_data[category].get("items") or []
            if items:
                for item in items:
                    state = item.get("state")
                    state_part = f"  [{state}]" if include_all and state else ""
                    print(
                        f"    {item['ref']}{state_part}  {item['title']}  {item['url']}",
                        file=out,
                    )
            else:
                print("    (none)", file=out)
            if category == "review_requested":
                drafts = host_data[category].get("drafts") or []
                if not items and drafts:
                    print(f"  {host.capitalize()} (drafts only)", file=out)
                    for item in drafts:
                        print(f"    {item['ref']}  {item['title']}  {item['url']}", file=out)


def print_done(result: dict[str, Any], *, out: TextIO = sys.stdout, quiet: bool = False) -> None:
    if result.get("ok") is False:
        if not quiet:
            print(result.get("error", "unknown error"), file=sys.stderr)
        return

    print(f"Updates — {result.get('date', '')}", file=out)
    for host in ("github", "gitlab"):
        host_data = result.get(host)
        if not host_data:
            continue
        print(f"  {host.capitalize()}", file=out)
        items = host_data.get("items") or []
        if items:
            for item in items:
                detail = item.get("detail")
                detail_part = f"  ({detail})" if detail else ""
                print(
                    f"    {item['action']}  {item['ref']}{detail_part}  {item['title']}  {item['url']}",
                    file=out,
                )
        else:
            print("    (none)", file=out)


def print_host_errors(result: dict[str, Any], *, err: TextIO = sys.stderr) -> None:
    for host in ("github", "gitlab"):
        data = result.get(host) or {}
        if data.get("ok") is False and data.get("error"):
            print(f"{host.capitalize()}: {data['error']}", file=err)
    for item in result.get("errors") or []:
        host = item.get("host", "config")
        message = item.get("message", "")
        print(f"{host}: {message}", file=err)
