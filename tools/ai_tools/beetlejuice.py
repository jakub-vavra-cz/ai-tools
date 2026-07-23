#!/usr/bin/env python3
"""Import Betelgeuse / IdM-CI Polarion XML into Jira RHELTEST.

Subcommands (Betelgeuse-shaped):

* ``test-case`` — Polarion *testcase importer* XML
  (``import-testcase.xml``) → jira-format dumps and/or
  :mod:`ai_tools.import_jira_testcase`
* ``test-run`` — planned (Polarion *test-run importer* XML)

Name is a pun on Betelgeuse.
"""

from __future__ import annotations

import gzip
import json
import re
import ssl
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import click

from ai_tools.dump_polarion_testcase import (
    JIRA_KEY_ORDER,
    ca_bundle_from_env,
    format_key_value,
    polarion_pairs_to_jira,
)
from ai_tools.import_jira_testcase import (
    DEFAULT_ISSUE_TYPE,
    DEFAULT_PROJECT,
    ImportResult,
    JiraConfig,
    JiraError,
    import_testcase,
    jira_config_from_env,
)

GZIP_MAGIC = b"\x1f\x8b"

_HREF_RE = re.compile(
    r'href=["\']([^"\']*import-testcase\.xml)["\']',
    re.IGNORECASE,
)


class BeetlejuiceError(RuntimeError):
    """Parse / download / import error."""


@dataclass
class ParsedTestcaseXml:
    """One Polarion testcase-importer XML document."""

    path: str
    project_id: str
    lookup_method: str
    lookup_field_id: str
    dry_run: bool
    cases: list[dict[str, str]] = field(default_factory=list)


@dataclass
class CaseResult:
    source: str
    test_case_id: str
    summary: str
    dump_path: str | None = None
    import_result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def maybe_decompress(data: bytes) -> bytes:
    """Return *data*, gunzipping when the payload is gzip-compressed."""
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def read_xml_bytes(path: Path) -> bytes:
    return maybe_decompress(path.read_bytes())


def _ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ca_bundle and Path(ca_bundle).is_file():
        ctx.load_verify_locations(ca_bundle)
    return ctx


def download_bytes(url: str, *, timeout: float = 120) -> bytes:
    """HTTP GET returning decompressed body bytes."""
    request = Request(url, headers={"Accept": "*/*"})
    try:
        with urlopen(
            request,
            context=_ssl_context(ca_bundle_from_env()),
            timeout=timeout,
        ) as response:
            return maybe_decompress(response.read())
    except HTTPError as exc:
        raise BeetlejuiceError(
            f"download failed: {exc.code} {exc.reason} for {url}",
        ) from exc
    except URLError as exc:
        raise BeetlejuiceError(f"download failed: {exc.reason} for {url}") from exc


def map_sst_team(value: str) -> str:
    """Map Polarion ``sst_idm_*`` poolteam values to Jira AssignedTeam.

    Example: ``sst_idm_sssd`` → ``rhel-idm-sssd``. Values that already look
    like Jira teams (``rhel-idm-…``) are left unchanged.
    """
    text = value.strip()
    if not text:
        return text
    if text.startswith("rhel-"):
        return text
    if text == "sst_idm":
        return "rhel-idm"
    match = re.fullmatch(r"sst_idm_(.+)", text, flags=re.IGNORECASE)
    if match:
        return f"rhel-idm-{match.group(1).lower()}"
    return text


def _element_text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    # ``itertext`` keeps nested markup text; unescape entities.
    parts = [unescape(t) for t in elem.itertext() if t]
    return "".join(parts).strip()


def _child_markup(elem: ET.Element | None) -> str:
    """Inner XML/text of an element (for HTML-ish description/setup bodies)."""
    if elem is None:
        return ""
    # Prefer serialized children when present (keeps nested tags), else text.
    children = list(elem)
    if not children:
        return unescape((elem.text or "").strip())
    chunks: list[str] = []
    if elem.text and elem.text.strip():
        chunks.append(unescape(elem.text))
    for child in children:
        chunks.append(ET.tostring(child, encoding="unicode"))
        if child.tail and child.tail.strip():
            chunks.append(unescape(child.tail))
    return "".join(chunks).strip()


def _custom_fields(testcase: ET.Element) -> dict[str, str]:
    fields: dict[str, str] = {}
    for cf in testcase.findall("./custom-fields/custom-field"):
        field_id = (cf.get("id") or "").strip()
        if not field_id:
            continue
        content = cf.get("content")
        if content is None:
            content = _element_text(cf)
        fields[field_id] = unescape(content).strip()
    return fields


def _hyperlinks(testcase: ET.Element) -> str:
    """Flatten hyperlinks to dump format ``role|uri,...``."""
    parts: list[str] = []
    for link in testcase.findall("./hyperlinks/hyperlink"):
        role = (link.get("role-id") or "").strip()
        uri = (link.get("uri") or "").strip()
        if not uri:
            continue
        if role:
            parts.append(f"{role}|{uri}")
        else:
            parts.append(uri)
    return ",".join(parts)


def _teststeps_to_pairs(testcase: ET.Element) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for index, step in enumerate(testcase.findall("./test-steps/test-step"), start=1):
        for col in step.findall("./test-step-column"):
            col_id = (col.get("id") or "").strip()
            if not col_id:
                continue
            # Columns often store HTML with escaped tags in the attribute-less
            # text node (``&lt;p&gt;...``); ElementTree already unescapes once.
            value = _child_markup(col) or _element_text(col)
            if not value:
                continue
            pairs[f"teststep.{index}.{col_id}"] = value
    return pairs


def _linked_work_items(testcase: ET.Element) -> str:
    """Serialize linked-work-items for description metadata."""
    parts: list[str] = []
    for item in testcase.findall("./linked-work-items/linked-work-item"):
        wid = (item.get("workitem-id") or "").strip()
        if not wid:
            continue
        role = (item.get("role-id") or "").strip()
        method = (item.get("lookup-method") or "").strip()
        bits = [wid]
        if role:
            bits.append(f"role={role}")
        if method:
            bits.append(f"lookup={method}")
        parts.append("|".join(bits))
    return ",".join(parts)


def testcase_element_to_pairs(
    testcase: ET.Element,
    *,
    project_id: str,
    map_team: bool = True,
    team_override: str = "",
) -> dict[str, str]:
    """Map one ``<testcase>`` element to Polarion-style key/value pairs."""
    case_id = (testcase.get("id") or "").strip()
    status = (testcase.get("status-id") or testcase.get("status") or "").strip()
    title = _element_text(testcase.find("title")) or case_id
    description = _child_markup(testcase.find("description"))
    custom = _custom_fields(testcase)

    pairs: dict[str, str] = {
        "project_id": project_id,
        "title": title,
        "type": "testcase",
    }
    if description:
        pairs["description"] = description
    if status:
        pairs["status"] = status

    # Lookup id → testCaseID (Jira customfield_10591 / dump ``ID``).
    # Prefer an explicit custom-field; otherwise use ``@id``.
    test_case_id = custom.pop("testCaseID", "").strip() or case_id
    if test_case_id:
        pairs["testCaseID"] = test_case_id

    for key, value in custom.items():
        if not value:
            continue
        pairs[key] = value

    if team_override.strip():
        pairs["subsystemteam"] = team_override.strip()
    elif map_team and pairs.get("subsystemteam"):
        pairs["subsystemteam"] = map_sst_team(pairs["subsystemteam"])

    hyperlinks = _hyperlinks(testcase)
    if hyperlinks:
        pairs["hyperlinks"] = hyperlinks

    pairs.update(_teststeps_to_pairs(testcase))

    linked = _linked_work_items(testcase)
    if linked:
        pairs["linked-work-items"] = linked

    return pairs


def parse_testcase_xml(
    data: bytes | str,
    *,
    source: str = "",
    map_team: bool = True,
    team_override: str = "",
) -> ParsedTestcaseXml:
    """Parse Polarion testcase-importer XML into Polarion-style pair dicts."""
    if isinstance(data, bytes):
        data = maybe_decompress(data).decode("utf-8")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BeetlejuiceError(f"invalid XML in {source or '<input>'}: {exc}") from exc

    tag = root.tag.split("}", 1)[-1]
    if tag != "testcases":
        raise BeetlejuiceError(
            f"expected root <testcases>, got <{tag}> in {source or '<input>'}",
        )

    props = {
        (p.get("name") or "").strip(): (p.get("value") or "").strip()
        for p in root.findall("./properties/property")
        if (p.get("name") or "").strip()
    }
    project_id = (root.get("project-id") or props.get("polarion-project-id") or "").strip()
    lookup_method = props.get("lookup-method", "").strip() or "name"
    lookup_field_id = (
        props.get(
            "polarion-custom-lookup-method-field-id",
            "",
        ).strip()
        or "testCaseID"
    )
    dry_raw = props.get("dry-run", "false").strip().lower()
    dry_run = dry_raw in {"1", "true", "yes"}

    cases: list[dict[str, str]] = []
    for testcase in root.findall("testcase"):
        cases.append(
            testcase_element_to_pairs(
                testcase,
                project_id=project_id,
                map_team=map_team,
                team_override=team_override,
            )
        )

    return ParsedTestcaseXml(
        path=source,
        project_id=project_id,
        lookup_method=lookup_method,
        lookup_field_id=lookup_field_id,
        dry_run=dry_run,
        cases=cases,
    )


def pairs_to_jira_dump(pairs: dict[str, str]) -> dict[str, str]:
    """Convert Polarion-style pairs to jira-format dump keys."""
    return polarion_pairs_to_jira(pairs, polarion_url="")


def dump_filename_for_id(work_item_id: str) -> str:
    """Filesystem-safe name derived from testCaseID."""
    cleaned = re.sub(r"[^\w.\-]+", "_", work_item_id, flags=re.UNICODE)
    cleaned = cleaned.strip("._") or "testcase"
    return f"{cleaned[:200]}.properties"


def write_jira_dump(dump: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        format_key_value(dump, key_order=JIRA_KEY_ORDER),
        encoding="utf-8",
    )


def find_local_testcase_xmls(path: Path) -> list[Path]:
    """Resolve a file or directory to one or more ``*import-testcase.xml`` paths."""
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise BeetlejuiceError(f"path not found: {path}")

    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in ("import-testcase.xml", "*import-testcase.xml"):
        for match in sorted(path.glob(pattern)):
            if match.is_file() and match not in seen:
                found.append(match)
                seen.add(match)
        for match in sorted(path.rglob(pattern)):
            if match.is_file() and match not in seen:
                found.append(match)
                seen.add(match)
    if not found:
        raise BeetlejuiceError(
            f"no *import-testcase.xml under {path}",
        )
    return found


def parse_directory_index_for_testcase_xmls(html: str, base_url: str) -> list[str]:
    """Extract ``*import-testcase.xml`` hrefs from an artifacts directory listing."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _HREF_RE.finditer(html):
        href = match.group(1).strip()
        if href.startswith("?") or href.startswith("#"):
            continue
        full = urljoin(base_url if base_url.endswith("/") else base_url + "/", href)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def resolve_inputs(target: str) -> list[tuple[str, bytes]]:
    """Return ``[(source_label, xml_bytes), ...]`` for a local path or URL."""
    parsed = urlparse(target)
    if parsed.scheme in {"http", "https"}:
        url = target.strip()
        if url.rstrip("/").endswith(".xml") or "import-testcase.xml" in url:
            return [(url, download_bytes(url))]
        # Treat as polarion/ directory listing.
        listing_url = url if url.endswith("/") else url + "/"
        html = download_bytes(listing_url).decode("utf-8", errors="replace")
        xml_urls = parse_directory_index_for_testcase_xmls(html, listing_url)
        if not xml_urls:
            # Fall back to the conventional filename.
            fallback = urljoin(listing_url, "import-testcase.xml")
            return [(fallback, download_bytes(fallback))]
        results: list[tuple[str, bytes]] = []
        for xml_url in xml_urls:
            results.append((xml_url, download_bytes(xml_url)))
        return results

    path = Path(target).expanduser()
    return [(str(p), read_xml_bytes(p)) for p in find_local_testcase_xmls(path)]


def apply_dump_overrides(
    dump: dict[str, str],
    *,
    tier: str = "",
    architecture: str = "",
    labels_extra: str = "",
) -> dict[str, str]:
    out = dict(dump)
    if tier.strip():
        out["Tier"] = tier.strip()
    if architecture.strip():
        out["Architecture"] = architecture.strip()
    if labels_extra.strip():
        existing = out.get("labels", "")
        merged = [part.strip() for part in f"{existing},{labels_extra}".split(",") if part.strip()]
        # Preserve order, unique.
        seen: list[str] = []
        for label in merged:
            if label not in seen:
                seen.append(label)
        out["labels"] = ",".join(seen)
    return out


def process_cases(
    documents: list[ParsedTestcaseXml],
    *,
    output_dir: Path | None,
    do_import: bool,
    jira_config: JiraConfig | None,
    project_key: str,
    issue_type: str,
    dry_run: bool,
    skip_assignee: bool,
    skip_components: bool,
    tier: str = "",
    architecture: str = "",
    labels_extra: str = "",
    limit: int | None = None,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    count = 0
    for doc in documents:
        for pairs in doc.cases:
            if limit is not None and count >= limit:
                return results
            count += 1
            test_case_id = pairs.get("testCaseID") or pairs.get("title") or f"case-{count}"
            try:
                dump = apply_dump_overrides(
                    pairs_to_jira_dump(pairs),
                    tier=tier,
                    architecture=architecture,
                    labels_extra=labels_extra,
                )
                if not dump.get("summary", "").strip():
                    raise BeetlejuiceError("mapped dump is missing summary")

                dump_path: Path | None = None
                if output_dir is not None:
                    dump_path = output_dir / dump_filename_for_id(test_case_id)
                    write_jira_dump(dump, dump_path)

                import_payload: dict[str, Any] | None = None
                if do_import:
                    if jira_config is None:
                        raise BeetlejuiceError("Jira config required for --import")
                    result: ImportResult = import_testcase(
                        dump,
                        config=jira_config,
                        project_key=project_key,
                        issue_type=issue_type,
                        dry_run=dry_run,
                        skip_assignee=skip_assignee,
                        skip_components=skip_components,
                    )
                    import_payload = result.to_dict()

                results.append(
                    CaseResult(
                        source=doc.path,
                        test_case_id=test_case_id,
                        summary=dump.get("summary", ""),
                        dump_path=str(dump_path) if dump_path else None,
                        import_result=import_payload,
                    )
                )
            except (BeetlejuiceError, JiraError, ValueError, OSError) as exc:
                results.append(
                    CaseResult(
                        source=doc.path,
                        test_case_id=test_case_id,
                        summary=pairs.get("title", ""),
                        error=str(exc),
                    )
                )
    return results


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
)
def cli() -> None:
    """Import Betelgeuse / IdM-CI Polarion XML into Jira RHELTEST.

    Subcommands mirror Betelgeuse: test-case (implemented) and test-run
    (planned).
    """


@cli.command("test-case")
@click.argument("target")
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Write one jira-format key=value dump per testcase into this directory",
)
@click.option(
    "--import",
    "do_import",
    is_flag=True,
    help=(
        "Create/update Jira Test Cases "
        "(requires JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN)"
    ),
)
@click.option(
    "-P",
    "--project",
    default=DEFAULT_PROJECT,
    show_default=True,
    help="Jira project key",
)
@click.option(
    "--issue-type",
    default=DEFAULT_ISSUE_TYPE,
    show_default=True,
    help="Issue type name",
)
@click.option(
    "-n",
    "--dry-run",
    is_flag=True,
    help="With --import, search and report without creating/updating",
)
@click.option(
    "--skip-assignee",
    is_flag=True,
    help="Do not set assignee on import",
)
@click.option(
    "--skip-components",
    is_flag=True,
    help="Do not set components on import",
)
@click.option(
    "--team",
    default="",
    help="Override subsystemteam / AssignedTeam for all cases",
)
@click.option(
    "--no-map-sst-team",
    is_flag=True,
    help="Do not map Polarion sst_idm_* values to rhel-idm-* AssignedTeam",
)
@click.option(
    "--tier",
    default="",
    help="Set Jira Tier (0–3) on all dumps/imports",
)
@click.option(
    "--architecture",
    default="",
    help="Set Jira Architecture (comma-separated) on all dumps/imports",
)
@click.option(
    "--label",
    multiple=True,
    help="Extra label to add (repeatable)",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Process at most N testcases (useful for dry-runs)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print results as JSON",
)
def test_case_cmd(
    target: str,
    output: Path | None,
    do_import: bool,
    project: str,
    issue_type: str,
    dry_run: bool,
    skip_assignee: bool,
    skip_components: bool,
    team: str,
    no_map_sst_team: bool,
    tier: str,
    architecture: str,
    label: tuple[str, ...],
    limit: int | None,
    as_json: bool,
) -> None:
    """Read import-testcase.xml and dump and/or push Test Cases to Jira.

    TARGET is a local import-testcase.xml, a directory containing them, or an
    http(s) URL to the XML / polarion/ artifacts directory.
    """
    if output is None and not do_import:
        raise click.UsageError(
            "specify -o/--output and/or --import (nothing to do otherwise)",
        )

    try:
        inputs = resolve_inputs(target)
        documents = [
            parse_testcase_xml(
                data,
                source=label_src,
                map_team=not no_map_sst_team,
                team_override=team,
            )
            for label_src, data in inputs
        ]
        if not any(doc.cases for doc in documents):
            raise BeetlejuiceError("no <testcase> elements found")

        jira_config: JiraConfig | None = None
        if do_import:
            jira_config = jira_config_from_env()

        results = process_cases(
            documents,
            output_dir=output,
            do_import=do_import,
            jira_config=jira_config,
            project_key=project,
            issue_type=issue_type,
            dry_run=dry_run,
            skip_assignee=skip_assignee,
            skip_components=skip_components,
            tier=tier,
            architecture=architecture,
            labels_extra=",".join(label),
            limit=limit,
        )
    except (BeetlejuiceError, JiraError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    errors = [r for r in results if r.error]
    if as_json:
        click.echo(
            json.dumps(
                {
                    "documents": len(documents),
                    "cases": len(results),
                    "errors": len(errors),
                    "results": [r.to_dict() for r in results],
                },
                indent=2,
            )
        )
    else:
        total_in = sum(len(d.cases) for d in documents)
        click.echo(
            f"parsed {len(documents)} XML file(s), {total_in} testcase(s); "
            f"processed {len(results)} (errors={len(errors)})"
        )
        for result in results:
            if result.error:
                click.echo(
                    f"error: {result.test_case_id}: {result.error}",
                    err=True,
                )
                continue
            bits = [result.test_case_id, result.summary]
            if result.dump_path:
                bits.append(f"dump={result.dump_path}")
            if result.import_result:
                action = result.import_result.get("action")
                key = result.import_result.get("issue_key") or "(new)"
                bits.append(f"{action}:{key}")
                browse = result.import_result.get("browse_url")
                if browse:
                    bits.append(browse)
            click.echo(" | ".join(bits))

    if errors:
        raise SystemExit(1)


@cli.command("test-run")
def test_run_cmd() -> None:
    """Import Polarion test-run XML into Jira (not implemented yet)."""
    raise click.ClickException(
        "beetlejuice test-run is not implemented yet "
        "(use test-case for import-testcase.xml)",
    )


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="beetlejuice", standalone_mode=False)
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
