#!/usr/bin/env python3
"""Query Red Hat Bugzilla via the REST API."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

import click

DEFAULT_HOST = "https://bugzilla.redhat.com"
DEFAULT_FIELDS = (
    "id",
    "summary",
    "status",
    "resolution",
    "product",
    "component",
    "assigned_to",
    "creator",
    "creation_time",
    "last_change_time",
    "url",
    "keywords",
)


class BugzillaError(RuntimeError):
    """Configuration or API failure."""


@dataclass(frozen=True)
class BugzillaConfig:
    """Connection settings from the environment."""

    host: str
    api_token: str
    username: str | None = None

    @property
    def rest_base(self) -> str:
        return urljoin(self.host.rstrip("/") + "/", "rest/")


@dataclass
class BugRecord:
    """Normalized bug payload for display and JSON output."""

    id: int
    summary: str
    status: str
    resolution: str | None = None
    product: str | None = None
    component: str | list[str] | None = None
    assigned_to: str | None = None
    creator: str | None = None
    creation_time: str | None = None
    last_change_time: str | None = None
    url: str | None = None
    keywords: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, payload: dict[str, Any], *, host: str) -> BugRecord:
        bug_id = int(payload["id"])
        url = payload.get("url") or f"{host.rstrip('/')}/show_bug.cgi?id={bug_id}"
        keywords = payload.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        return cls(
            id=bug_id,
            summary=str(payload.get("summary") or ""),
            status=str(payload.get("status") or ""),
            resolution=payload.get("resolution"),
            product=payload.get("product"),
            component=payload.get("component"),
            assigned_to=payload.get("assigned_to"),
            creator=payload.get("creator"),
            creation_time=payload.get("creation_time"),
            last_change_time=payload.get("last_change_time"),
            url=url,
            keywords=list(keywords),
            raw=payload,
        )

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        if include_raw:
            data["raw"] = self.raw
        return data


def normalize_host(host: str) -> str:
    """Return an https base URL without a trailing slash."""
    value = host.strip()
    if not value:
        raise BugzillaError("BUGZILLA_HOST is empty")
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = f"https://{value}"
    return value.rstrip("/")


def config_from_env() -> BugzillaConfig:
    """Load Bugzilla settings from BUGZILLA_* environment variables."""
    token = os.environ.get("BUGZILLA_API_TOKEN", "").strip()
    if not token:
        raise BugzillaError("BUGZILLA_API_TOKEN is not set")

    host_raw = os.environ.get("BUGZILLA_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    username = os.environ.get("BUGZILLA_USERNAME", "").strip() or None
    return BugzillaConfig(
        host=normalize_host(host_raw),
        api_token=token,
        username=username,
    )


def parse_bug_ids(values: tuple[str, ...]) -> list[int]:
    """Parse bug IDs from CLI args and comma-separated tokens."""
    ids: list[int] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise BugzillaError(f"Invalid bug id: {part}")
            ids.append(int(part))
    if not ids:
        raise BugzillaError("At least one bug id is required")
    return ids


def _http_json(
    url: str,
    *,
    api_token: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if params:
        query = urlencode(params, doseq=True)
        url = f"{url}?{query}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "User-Agent": "ai-tools-bugzilla/1.0",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = body
        try:
            payload = json.loads(body)
            message = payload.get("message") or payload.get("error") or body
        except json.JSONDecodeError:
            pass
        raise BugzillaError(f"HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise BugzillaError(f"Request failed: {exc.reason}") from exc


class BugzillaClient:
    """Thin Bugzilla REST client."""

    def __init__(self, config: BugzillaConfig) -> None:
        self.config = config

    def get_bugs(
        self,
        bug_ids: list[int],
        *,
        include_fields: list[str] | None = None,
    ) -> list[BugRecord]:
        """Fetch bugs by numeric id."""
        fields = include_fields or list(DEFAULT_FIELDS)
        params: dict[str, Any] = {"include_fields": ",".join(fields)}
        for bug_id in bug_ids:
            params.setdefault("id", []).append(bug_id)

        data = _http_json(
            urljoin(self.config.rest_base, "bug"),
            api_token=self.config.api_token,
            params=params,
        )
        bugs = data.get("bugs") or []
        found = {int(item["id"]) for item in bugs}
        missing = [bug_id for bug_id in bug_ids if bug_id not in found]
        if missing:
            raise BugzillaError(f"Bug(s) not found: {', '.join(map(str, missing))}")
        by_id = {int(item["id"]): BugRecord.from_api(item, host=self.config.host) for item in bugs}
        return [by_id[bug_id] for bug_id in bug_ids]

    def search_bugs(
        self,
        *,
        product: str | None = None,
        component: str | None = None,
        status: str | None = None,
        summary: str | None = None,
        assigned_to: str | None = None,
        creator: str | None = None,
        quicksearch: str | None = None,
        limit: int = 20,
        offset: int = 0,
        include_fields: list[str] | None = None,
    ) -> list[BugRecord]:
        """Search bugs with REST query parameters."""
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        fields = include_fields or list(DEFAULT_FIELDS)
        params["include_fields"] = ",".join(fields)

        if product:
            params["product"] = product
        if component:
            params["component"] = component
        if status:
            params["status"] = status
        if summary:
            params["summary"] = summary
        if assigned_to:
            params["assigned_to"] = assigned_to
        if creator:
            params["creator"] = creator
        if quicksearch:
            params["quicksearch"] = quicksearch

        if len(params) <= 3:
            raise BugzillaError(
                "At least one search filter is required "
                "(product, component, status, summary, assigned_to, creator, quicksearch)"
            )

        data = _http_json(
            urljoin(self.config.rest_base, "bug"),
            api_token=self.config.api_token,
            params=params,
        )
        return [BugRecord.from_api(item, host=self.config.host) for item in data.get("bugs") or []]


def format_bug(bug: BugRecord) -> str:
    """Human-readable single-bug summary."""
    resolution = f"/{bug.resolution}" if bug.resolution else ""
    component = bug.component
    if isinstance(component, list):
        component = ", ".join(component)
    lines = [
        f"BZ {bug.id} [{bug.status}{resolution}] {component or ''}".rstrip(),
        f"  {bug.summary}",
    ]
    if bug.assigned_to:
        lines.append(f"  assigned_to: {bug.assigned_to}")
    if bug.url:
        lines.append(f"  url: {bug.url}")
    return "\n".join(lines)


def print_bugs(
    bugs: list[BugRecord],
    *,
    as_json: bool = False,
    include_raw: bool = False,
) -> None:
    if as_json:
        payload = [bug.to_dict(include_raw=include_raw) for bug in bugs]
        click.echo(json.dumps(payload if len(payload) != 1 else payload[0], indent=2))
        return
    for index, bug in enumerate(bugs):
        if index:
            click.echo()
        click.echo(format_bug(bug))


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Query Bugzilla using BUGZILLA_API_TOKEN, BUGZILLA_HOST, BUGZILLA_USERNAME."""


@main.command("config")
def config_cmd() -> None:
    """Show resolved Bugzilla connection settings."""
    try:
        config = config_from_env()
    except BugzillaError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"host={config.host}")
    click.echo(f"rest_base={config.rest_base}")
    click.echo(f"username={config.username or ''}")
    click.echo("api_token=set" if config.api_token else "api_token=")


@main.command("get")
@click.argument("bug_ids", nargs=-1, required=True)
@click.option(
    "--field",
    "fields",
    multiple=True,
    help="Extra REST include_fields (repeatable). Defaults to a useful summary set.",
)
@click.option("--json", "as_json", is_flag=True, help="Print JSON.")
@click.option("--raw", "include_raw", is_flag=True, help="Include full REST payload in JSON.")
def get_cmd(
    bug_ids: tuple[str, ...],
    fields: tuple[str, ...],
    as_json: bool,
    include_raw: bool,
) -> None:
    """Fetch one or more bugs by id."""
    try:
        config = config_from_env()
        ids = parse_bug_ids(bug_ids)
        include_fields = list(fields) if fields else list(DEFAULT_FIELDS)
        client = BugzillaClient(config)
        bugs = client.get_bugs(ids, include_fields=include_fields)
    except BugzillaError as exc:
        raise click.ClickException(str(exc)) from exc

    print_bugs(bugs, as_json=as_json, include_raw=include_raw)


@main.command("search")
@click.option("--product", help="Product name filter.")
@click.option("--component", help="Component name filter.")
@click.option("--status", help="Status filter, e.g. NEW or CLOSED.")
@click.option("--summary", help="Summary substring filter.")
@click.option("--assigned-to", "assigned_to", help="Assigned user email/login.")
@click.option(
    "--mine",
    is_flag=True,
    help="Filter bugs assigned to BUGZILLA_USERNAME.",
)
@click.option("--creator", help="Creator email/login.")
@click.option("--quicksearch", help="Bugzilla quicksearch string.")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, 500))
@click.option("--offset", default=0, show_default=True, type=click.IntRange(0))
@click.option("--field", "fields", multiple=True, help="Extra REST include_fields.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON.")
@click.option("--raw", "include_raw", is_flag=True, help="Include full REST payload in JSON.")
def search_cmd(
    product: str | None,
    component: str | None,
    status: str | None,
    summary: str | None,
    assigned_to: str | None,
    mine: bool,
    creator: str | None,
    quicksearch: str | None,
    limit: int,
    offset: int,
    fields: tuple[str, ...],
    as_json: bool,
    include_raw: bool,
) -> None:
    """Search bugs with REST filters."""
    try:
        config = config_from_env()
        if mine:
            if not config.username:
                raise BugzillaError("BUGZILLA_USERNAME is required with --mine")
            assigned_to = config.username
        include_fields = list(fields) if fields else list(DEFAULT_FIELDS)
        client = BugzillaClient(config)
        bugs = client.search_bugs(
            product=product,
            component=component,
            status=status,
            summary=summary,
            assigned_to=assigned_to,
            creator=creator,
            quicksearch=quicksearch,
            limit=limit,
            offset=offset,
            include_fields=include_fields,
        )
    except BugzillaError as exc:
        raise click.ClickException(str(exc)) from exc

    if not bugs and not as_json:
        click.echo("No bugs matched.", err=True)
        sys.exit(1)
    print_bugs(bugs, as_json=as_json, include_raw=include_raw)


if __name__ == "__main__":
    main(standalone_mode=True)
