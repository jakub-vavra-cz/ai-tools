"""Create, list, and delete Jira issue links (POST/DELETE /rest/api/3/issueLink)."""

from __future__ import annotations

import json
import sys
from typing import Any, Literal, TextIO

from jira_cli.api import JiraApiError, JiraClient, print_jira_api_error


def normalize_relationship_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def resolve_link_type(
    link_types: list[dict[str, Any]],
    *,
    type_name: str,
    err: TextIO,
) -> dict[str, Any] | None:
    """Match link type by exact name (case-insensitive)."""
    want = type_name.strip()
    if not want:
        print("jira-cli link: link type name must not be empty.", file=err)
        return None
    matches = [
        lt
        for lt in link_types
        if isinstance(lt.get("name"), str) and lt["name"].strip().lower() == want.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"jira-cli link: ambiguous link type {want!r}.", file=err)
        return None
    names = sorted(
        str(lt.get("name") or "")
        for lt in link_types
        if isinstance(lt.get("name"), str) and str(lt["name"]).strip()
    )
    print(f"jira-cli link: unknown link type {want!r}.", file=err)
    if names:
        print(f"Available types: {', '.join(names)}", file=err)
    return None


def resolve_source_role(
    link_type: dict[str, Any],
    *,
    as_relationship: str,
    err: TextIO,
) -> Literal["inward", "outward"] | None:
    """
    Map ``--as`` (from source toward target) to inward/outward role on the source issue.

    ``as_relationship`` must match the link type's inward or outward label, e.g.
    ``blocks`` or ``is blocked by`` for type Blocks.
    """
    inward = normalize_relationship_label(str(link_type.get("inward") or ""))
    outward = normalize_relationship_label(str(link_type.get("outward") or ""))
    want = normalize_relationship_label(as_relationship)
    if not want:
        print("jira-cli link: --as relationship must not be empty.", file=err)
        return None
    if want == outward:
        return "outward"
    if want == inward:
        return "inward"
    print(
        f"jira-cli link: --as {as_relationship!r} does not match type "
        f"{link_type.get('name')!r} (inward={link_type.get('inward')!r}, "
        f"outward={link_type.get('outward')!r}).",
        file=err,
    )
    return None


def post_keys_for_source_role(
    source_key: str,
    target_key: str,
    *,
    source_role: Literal["inward", "outward"],
) -> tuple[str, str]:
    """
    Return ``(inward_issue_key, outward_issue_key)`` for POST /rest/api/3/issueLink.

    Jira Cloud maps POST ``inwardIssue`` / ``outwardIssue`` to the opposite link-type
    roles on the issue view (verified on redhat.atlassian.net): when source should show
    the outward label toward target (e.g. source *blocks* target), pass
    ``inwardIssue=source`` and ``outwardIssue=target``.
    """
    if source_role == "outward":
        return source_key, target_key
    return target_key, source_key


def build_create_issue_link_payload(
    *,
    link_type_name: str,
    inward_issue_key: str,
    outward_issue_key: str,
    comment: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": {"name": link_type_name.strip()},
        "inwardIssue": {"key": inward_issue_key.strip()},
        "outwardIssue": {"key": outward_issue_key.strip()},
    }
    if comment is not None and comment.strip():
        payload["comment"] = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment.strip()}],
                    }
                ],
            }
        }
    return payload


def summarize_issue_link(link: dict[str, Any], *, perspective_key: str) -> dict[str, Any]:
    """Compact link row for JSON/CLI from one issue's perspective."""
    link_type = link.get("type") if isinstance(link.get("type"), dict) else {}
    other_key: str | None = None
    relationship: str | None = None
    inward = link.get("inwardIssue")
    outward = link.get("outwardIssue")
    if isinstance(outward, dict) and outward.get("key"):
        other_key = str(outward["key"])
        relationship = str(link_type.get("outward") or "")
    elif isinstance(inward, dict) and inward.get("key"):
        other_key = str(inward["key"])
        relationship = str(link_type.get("inward") or "")
    return {
        "id": link.get("id"),
        "type": link_type.get("name"),
        "perspective_issue": perspective_key,
        "other_issue": other_key,
        "relationship": relationship,
        "inward": link_type.get("inward"),
        "outward": link_type.get("outward"),
    }


def fetch_issue_links(client: JiraClient, issue_key: str) -> list[dict[str, Any]]:
    data = client.get_issue(issue_key, fields=["issuelinks"])
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        return []
    links = fields.get("issuelinks")
    if not isinstance(links, list):
        return []
    return [link for link in links if isinstance(link, dict)]


def create_issue_link(
    client: JiraClient,
    *,
    link_type_name: str,
    inward_issue_key: str,
    outward_issue_key: str,
    comment: str | None = None,
    err: TextIO,
) -> dict[str, Any] | None:
    payload = build_create_issue_link_payload(
        link_type_name=link_type_name,
        inward_issue_key=inward_issue_key,
        outward_issue_key=outward_issue_key,
        comment=comment,
    )
    try:
        client.create_issue_link(payload)
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to create issue link")
        return None
    return {
        "ok": True,
        "type": link_type_name,
        "inward_issue": inward_issue_key,
        "outward_issue": outward_issue_key,
        "comment": comment,
    }


def create_issue_link_between(
    client: JiraClient,
    *,
    source_key: str,
    target_key: str,
    link_type_name: str,
    as_relationship: str,
    comment: str | None = None,
    err: TextIO,
) -> dict[str, Any] | None:
    try:
        link_types = client.get_issue_link_types()
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to list issue link types")
        return None
    link_type = resolve_link_type(link_types, type_name=link_type_name, err=err)
    if link_type is None:
        return None
    source_role = resolve_source_role(link_type, as_relationship=as_relationship, err=err)
    if source_role is None:
        return None
    inward_key, outward_key = post_keys_for_source_role(
        source_key,
        target_key,
        source_role=source_role,
    )
    resolved_name = str(link_type.get("name") or link_type_name)
    result = create_issue_link(
        client,
        link_type_name=resolved_name,
        inward_issue_key=inward_key,
        outward_issue_key=outward_key,
        comment=comment,
        err=err,
    )
    if result is None:
        return None
    result.update(
        {
            "source_issue": source_key,
            "target_issue": target_key,
            "as": as_relationship,
        }
    )
    return result


def delete_issue_link(client: JiraClient, link_id: str, *, err: TextIO) -> bool:
    raw = link_id.strip()
    if not raw:
        print("jira-cli unlink: link id must not be empty.", file=err)
        return False
    try:
        client.delete_issue_link(raw)
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to delete issue link")
        return False
    return True


def run_link_types(
    client: JiraClient,
    *,
    search: str | None = None,
    as_json: bool = False,
    out: TextIO,
    err: TextIO = sys.stderr,
) -> int:
    try:
        types = client.get_issue_link_types()
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to list issue link types")
        return 1
    if search is not None and search.strip():
        needle = search.strip().lower()
        types = [
            lt
            for lt in types
            if needle in str(lt.get("name") or "").lower()
            or needle in str(lt.get("inward") or "").lower()
            or needle in str(lt.get("outward") or "").lower()
        ]
    if as_json:
        json.dump(types, out, indent=2)
        out.write("\n")
        return 0
    if not types:
        print("No issue link types found.", file=out)
        return 0
    for lt in types:
        name = lt.get("name") or ""
        inward = lt.get("inward") or ""
        outward = lt.get("outward") or ""
        print(f"{name}\tinward={inward}\toutward={outward}", file=out)
    return 0


def run_link_create(
    client: JiraClient,
    *,
    source_key: str | None,
    target_key: str | None,
    link_type_name: str,
    as_relationship: str | None,
    inward_issue_key: str | None,
    outward_issue_key: str | None,
    comment: str | None = None,
    as_json: bool = False,
    out: TextIO,
    err: TextIO = sys.stderr,
) -> int:
    if inward_issue_key is not None and outward_issue_key is not None:
        result = create_issue_link(
            client,
            link_type_name=link_type_name,
            inward_issue_key=inward_issue_key,
            outward_issue_key=outward_issue_key,
            comment=comment,
            err=err,
        )
    else:
        if not source_key or not target_key:
            print(
                "jira-cli link: provide SOURCE TARGET or both --inward and --outward.",
                file=err,
            )
            return 2
        if not as_relationship:
            print(
                "jira-cli link: --as is required when using SOURCE TARGET "
                "(e.g. --as blocks).",
                file=err,
            )
            return 2
        result = create_issue_link_between(
            client,
            source_key=source_key,
            target_key=target_key,
            link_type_name=link_type_name,
            as_relationship=as_relationship,
            comment=comment,
            err=err,
        )
    if result is None:
        return 1
    if as_json:
        json.dump(result, out, indent=2)
        out.write("\n")
        return 0
    print(
        f"Linked {result.get('inward_issue')} / {result.get('outward_issue')} "
        f"({result.get('type')})",
        file=out,
    )
    return 0


def run_link_delete(
    client: JiraClient,
    *,
    link_id: str,
    as_json: bool = False,
    out: TextIO,
    err: TextIO = sys.stderr,
) -> int:
    ok = delete_issue_link(client, link_id, err=err)
    if not ok:
        return 1
    payload = {"ok": True, "link_id": link_id.strip()}
    if as_json:
        json.dump(payload, out, indent=2)
        out.write("\n")
        return 0
    print(f"Deleted issue link {link_id.strip()}", file=out)
    return 0


def run_links_list(
    client: JiraClient,
    *,
    issue_key: str,
    as_json: bool = False,
    out: TextIO,
    err: TextIO = sys.stderr,
) -> int:
    try:
        links = fetch_issue_links(client, issue_key)
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to fetch issue links")
        return 1
    rows = [summarize_issue_link(link, perspective_key=issue_key) for link in links]
    if as_json:
        json.dump({"issue_key": issue_key, "links": rows}, out, indent=2)
        out.write("\n")
        return 0
    if not rows:
        print(f"No links on {issue_key}.", file=out)
        return 0
    for row in rows:
        print(
            f"{row.get('id')}\t{row.get('relationship')}\t{row.get('other_issue')}\t"
            f"type={row.get('type')}",
            file=out,
        )
    return 0
