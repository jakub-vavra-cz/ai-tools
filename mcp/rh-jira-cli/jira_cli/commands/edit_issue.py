"""Edit issue: summary, description, story points, sprint, comments, transition."""

from __future__ import annotations

import json
import re
import sys
from typing import Any, TextIO

from jira_cli.api import (
    JiraClient,
    JiraApiError,
    description_plain_text_to_adf,
    print_jira_api_error,
    project_key_from_issue,
    user_account_ref_from_email,
    user_account_ref_list_from_email,
)
from jira_cli import sprint_cache
from jira_cli.config import Settings
from jira_cli.custom_fields import find_custom_field_id_by_exact_display_name
from jira_cli.commands.show_issue import _fields_description_to_plain_text

_STORY_POINTS_LABEL = "Story Points"

# Display names aligned with ``show --short`` (custom fields).
_CF_SEVERITY = "Severity"
_CF_DEVELOPER = "Developer"
_CF_QA_CONTACT = "QA Contact"
_CF_DOC_CONTACT = "Doc Contact"
_CF_CONTRIBUTORS = "Contributors"
_CF_PRELIMINARY_TESTING = "Preliminary Testing"
_CF_FIXED_IN_BUILD = "Fixed in Build"
_CF_TEST_COVERAGE = "Test Coverage"
_CF_TEST_LINK = "Test Link"
_CF_GIT_PULL_REQUEST = "Git Pull Request"
_CF_ASSIGNED_TEAM = "AssignedTeam"


def resolve_story_points_field_id(client: JiraClient) -> str | None:
    """
    Custom field whose name is exactly "Story Points" (GET /rest/api/3/field).
    """
    try:
        fields = client.get_fields()
    except JiraApiError:
        return None
    return find_custom_field_id_by_exact_display_name(fields, _STORY_POINTS_LABEL)


def resolve_custom_field_key_by_display_name(client: JiraClient, display_name: str) -> str | None:
    """Return ``customfield_*`` id for a custom field with exact display ``name`` (GET /rest/api/3/field)."""
    try:
        fields = client.get_fields()
    except JiraApiError:
        return None
    return find_custom_field_id_by_exact_display_name(fields, display_name)


def custom_field_key_from_settings(
    env_id: str | None,
    display_name: str,
    client: JiraClient,
) -> str | None:
    """Prefer ``JIRA_*_FIELD_ID``-style env (numeric or ``customfield_*``), else resolve by display name."""
    if env_id and isinstance(env_id, str) and env_id.strip():
        fid = env_id.strip()
        if fid.startswith("customfield_"):
            return fid
        if fid.isdigit():
            return f"customfield_{fid}"
    return resolve_custom_field_key_by_display_name(client, display_name)


def _field_def_by_id(all_fields: list[dict[str, Any]], field_id: str) -> dict[str, Any] | None:
    for f in all_fields:
        if f.get("id") == field_id:
            return f
    return None


def _custom_field_needs_adf(field_def: dict[str, Any]) -> bool:
    """Paragraph-style custom fields (e.g. Git Pull Request on Red Hat Jira) require ADF."""
    name = (field_def.get("name") or "").strip()
    if name == _CF_GIT_PULL_REQUEST:
        return True
    clauses = field_def.get("clauseNames")
    if isinstance(clauses, list):
        for c in clauses:
            if isinstance(c, str) and c.endswith("[Paragraph]"):
                return True
    return False


def _coerce_custom_field_value(
    field_def: dict[str, Any] | None,
    raw: str,
    *,
    client: JiraClient,
    err: TextIO,
) -> Any | None:
    """Build REST ``fields`` value for a custom field from a CLI string (non-empty)."""
    raw = raw.strip()
    if not field_def:
        return raw
    schema = field_def.get("schema") or {}
    typ = (schema.get("type") or "").lower()
    custom = str(schema.get("custom", "")).lower()
    items = schema.get("items")

    if typ == "user" or "userpicker" in custom:
        if not raw:
            return None
        return user_account_ref_from_email(client, raw, err)

    if typ == "array":
        if items == "user" or (isinstance(items, str) and "user" in items.lower()):
            if not raw:
                return None
            return user_account_ref_list_from_email(client, raw, err)
        return raw

    if (
        typ == "option"
        or "select" in custom
        or "radiobuttons" in custom
        or "option-with-child" in custom
    ):
        return {"value": raw}

    if typ in ("string", "date", "datetime"):
        if typ == "string" and _custom_field_needs_adf(field_def):
            return description_plain_text_to_adf(raw)
        return raw
    if typ in ("number", "float", "integer"):
        try:
            return float(raw) if "." in raw else int(raw)
        except ValueError:
            return raw

    return raw


def resolve_transition_id(
    client: JiraClient,
    issue_key: str,
    transition_name_or_id: str,
) -> str:
    tid = transition_name_or_id.strip()
    if tid.isdigit():
        return tid
    data = client.get_transitions(issue_key)
    transitions = data.get("transitions") or []
    matches = [t for t in transitions if (t.get("name") or "").lower() == tid.lower()]
    if len(matches) == 1:
        return str(matches[0]["id"])
    partial = [t for t in transitions if tid.lower() in (t.get("name") or "").lower()]
    if len(partial) == 1:
        return str(partial[0]["id"])
    if not partial:
        raise SystemExit(
            f"No transition matching {transition_name_or_id!r}. "
            f"Use: jira-cli transitions {issue_key}",
        )
    names = ", ".join(t.get("name", "") for t in partial)
    raise SystemExit(f"Ambiguous transition {transition_name_or_id!r}. Matches: {names}")


def match_named_sprint_in_list(
    sprints: list[dict[str, Any]],
    sprint_name_or_id: str,
) -> int | None:
    """
    Return sprint id if exactly one sprint name matches (exact, else unique substring).

    Returns ``None`` if there are no matches. Raises ``SystemExit`` if multiple matches.
    """
    raw = sprint_name_or_id.strip()
    if not sprints:
        return None
    matches = [s for s in sprints if (s.get("name") or "").lower() == raw.lower()]
    if len(matches) > 1:
        names = ", ".join(f"{s.get('name')} (id={s.get('id')})" for s in matches)
        raise SystemExit(f"Ambiguous sprint {sprint_name_or_id!r}. Matches: {names}")
    if len(matches) == 1:
        return int(matches[0]["id"])
    partial = [s for s in sprints if raw.lower() in (s.get("name") or "").lower()]
    if len(partial) > 1:
        names = ", ".join(s.get("name", "") for s in partial)
        raise SystemExit(f"Ambiguous sprint {sprint_name_or_id!r}. Matches: {names}")
    if len(partial) == 1:
        return int(partial[0]["id"])
    return None


def _pick_sprint_id_from_named_sprints(
    sprints: list[dict[str, Any]],
    sprint_name_or_id: str,
    *,
    scope_hint: str,
) -> int:
    """
    Resolve a non-numeric sprint query against an already-loaded sprint list.

    ``scope_hint`` appears in errors (e.g. ``project PROJ`` or ``all Scrum boards``).
    """
    if not sprints:
        raise SystemExit(
            f"No sprints in {scope_hint}. "
            f"Try: jira-cli sprints <KEY> --state future,active,closed or use a numeric sprint id.",
        )
    sid = match_named_sprint_in_list(sprints, sprint_name_or_id)
    if sid is None:
        raise SystemExit(
            f"No sprint matching {sprint_name_or_id!r} in {scope_hint}. "
            f"Try a numeric id from jira-cli sprints <KEY>, or pass --sprint-project to narrow by project.",
        )
    return sid


def resolve_sprint_id_for_project(
    client: JiraClient,
    project_key: str,
    sprint_name_or_id: str,
    *,
    refresh_sprint_cache: bool = False,
) -> int:
    """Resolve sprint id or name for a project key (used by ``new`` before an issue key exists)."""
    raw = sprint_name_or_id.strip()
    if raw.isdigit():
        return int(raw)
    proj = project_key.strip().upper()
    refresh_attempts = [True] if refresh_sprint_cache else [False, True]
    for refresh in refresh_attempts:
        sprints = client.all_sprints_for_project(proj, refresh_cache=refresh)
        if not sprints:
            raise SystemExit(
                f"No boards or no matching sprints for project {proj}. "
                f"Try: jira-cli sprints {proj} --state future,active,closed",
            )
        sid = match_named_sprint_in_list(sprints, sprint_name_or_id)
        if sid is not None:
            return sid
    return _pick_sprint_id_from_named_sprints(
        sprints,
        sprint_name_or_id,
        scope_hint=f"project {proj}",
    )


def resolve_sprint_id_without_project(
    client: JiraClient,
    sprint_name_or_id: str,
    *,
    refresh_sprint_cache: bool = False,
) -> int:
    """
    Resolve sprint id or name by scanning every Scrum board visible to the user.

    Slower than ``resolve_sprint_id_for_project``; pass ``--sprint-project`` when you know
    the project. When ``JIRA_SPRINT_CACHE`` is enabled, uses merged per-project cache and/or
    ``all_projects_merged_*`` first; refetches from the API when ``refresh_sprint_cache`` is
    true or when the sprint name is not found in cache (ambiguous names still error without
    a live refetch).
    """
    raw = sprint_name_or_id.strip()
    if raw.isdigit():
        return int(raw)
    st = "future,active,closed"
    if not refresh_sprint_cache and sprint_cache.is_enabled():
        union = sprint_cache.load_all_projects_sprints_union(st)
        if union:
            sid = match_named_sprint_in_list(union, sprint_name_or_id)
            if sid is not None:
                return sid
    sprints, boards_payload = client.all_sprints_from_all_scrum_boards(state=st)
    if sprint_cache.is_enabled():
        sprint_cache.save_all_projects_merged(st, sprints, boards_payload)
    if not sprints:
        raise SystemExit(
            "No sprints found on any Scrum board. "
            "Try: jira-cli sprints <KEY> --state future,active,closed or use a numeric sprint id.",
        )
    return _pick_sprint_id_from_named_sprints(
        sprints,
        sprint_name_or_id,
        scope_hint="all Scrum boards",
    )


def resolve_sprint_id(
    client: JiraClient,
    _settings: Settings,
    issue_key: str,
    sprint_name_or_id: str,
    *,
    refresh_sprint_cache: bool = False,
) -> int:
    return resolve_sprint_id_for_project(
        client,
        project_key_from_issue(issue_key),
        sprint_name_or_id,
        refresh_sprint_cache=refresh_sprint_cache,
    )


def _reject_user_field_clear_conflict(
    clear: bool,
    email: str | None,
    *,
    clear_flag: str,
    email_flag: str,
    err: TextIO,
) -> int:
    if clear and email is not None and str(email).strip():
        print(
            f"jira-cli edit: cannot use {clear_flag} together with {email_flag}.",
            file=err,
        )
        return 2
    return 0


def _clear_custom_field(
    batch_fields: dict[str, Any],
    display_name: str,
    env_key: str | None,
    client: JiraClient,
    err: TextIO,
) -> int:
    key = custom_field_key_from_settings(env_key, display_name, client)
    if not key:
        print(
            f'No custom field named "{display_name}" (and no matching JIRA_*_FIELD_ID).',
            file=err,
        )
        return 2
    batch_fields[key] = None
    return 0


def apply_common_field_updates_to_dict(
    client: JiraClient,
    settings: Settings,
    batch_fields: dict[str, Any],
    *,
    story_points: Any | None = None,
    assignee_email: str | None = None,
    assignee_clear: bool = False,
    reporter_email: str | None = None,
    reporter_clear: bool = False,
    priority_name: str | None = None,
    issuetype_name: str | None = None,
    duedate: str | None = None,
    clear_due: bool = False,
    severity: str | None = None,
    team: str | None = None,
    preliminary_testing: str | None = None,
    test_coverage: str | None = None,
    fixed_in_build: str | None = None,
    test_link: str | None = None,
    git_pull_request: str | None = None,
    developer_email: str | None = None,
    developer_clear: bool = False,
    qa_contact_email: str | None = None,
    qa_contact_clear: bool = False,
    doc_contact_email: str | None = None,
    doc_contact_clear: bool = False,
    contributors_emails: str | None = None,
    contributors_clear: bool = False,
    err: TextIO,
) -> int:
    """
    Mutate ``batch_fields`` with story points, assignee, reporter, priority, type, due date,
    and custom fields (same rules as ``apply_edit``). Used by ``edit`` and ``new``.
    """
    need_meta = any(
        [
            severity,
            team,
            preliminary_testing,
            test_coverage,
            fixed_in_build,
            test_link,
            git_pull_request,
            developer_email,
            qa_contact_email,
            doc_contact_email,
            contributors_emails,
        ]
    )
    all_field_defs: list[dict[str, Any]] | None = None
    if need_meta:
        try:
            all_field_defs = client.get_fields()
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to load fields")
            return 1

    if story_points is not None:
        sp_field = resolve_story_points_field_id(client)
        if not sp_field:
            print(
                f'No custom field named "{_STORY_POINTS_LABEL}" found (GET /rest/api/3/field).',
                file=err,
            )
            return 2
        batch_fields[sp_field] = story_points

    rc = _reject_user_field_clear_conflict(
        assignee_clear,
        assignee_email,
        clear_flag="--assignee-clear",
        email_flag="--assignee-email",
        err=err,
    )
    if rc != 0:
        return rc
    if assignee_clear:
        batch_fields["assignee"] = None
    elif assignee_email is not None:
        ap = user_account_ref_from_email(client, assignee_email, err)
        if ap is None:
            return 2
        batch_fields["assignee"] = ap

    rc = _reject_user_field_clear_conflict(
        reporter_clear,
        reporter_email,
        clear_flag="--reporter-clear",
        email_flag="--reporter-email",
        err=err,
    )
    if rc != 0:
        return rc
    if reporter_clear:
        batch_fields["reporter"] = None
    elif reporter_email is not None:
        rp = user_account_ref_from_email(client, reporter_email, err)
        if rp is None:
            return 2
        batch_fields["reporter"] = rp

    if priority_name is not None and priority_name.strip():
        batch_fields["priority"] = {"name": priority_name.strip()}

    if issuetype_name is not None and issuetype_name.strip():
        batch_fields["issuetype"] = {"name": issuetype_name.strip()}

    if clear_due and duedate is not None and str(duedate).strip():
        print("Use either --clear-due or --due, not both.", file=err)
        return 2
    if clear_due:
        batch_fields["duedate"] = None
    elif duedate is not None:
        ds = duedate.strip()
        if ds:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", ds):
                print(
                    "--due must be YYYY-MM-DD (Jira fields.duedate).",
                    file=err,
                )
                return 2
            batch_fields["duedate"] = ds

    def _put_cf(
        display_name: str,
        env_key: str | None,
        value: str | None,
    ) -> int:
        if value is None or not str(value).strip():
            return 0
        key = custom_field_key_from_settings(env_key, display_name, client)
        if not key:
            print(
                f'No custom field named "{display_name}" (and no matching JIRA_*_FIELD_ID).',
                file=err,
            )
            return 2
        fdef = _field_def_by_id(all_field_defs or [], key) if all_field_defs else None
        coerced = _coerce_custom_field_value(fdef, str(value).strip(), client=client, err=err)
        if coerced is None:
            return 2
        batch_fields[key] = coerced
        return 0

    if severity is not None and str(severity).strip():
        rc = _put_cf(_CF_SEVERITY, None, str(severity).strip())
        if rc != 0:
            return rc

    if team is not None and str(team).strip():
        rc = _put_cf(_CF_ASSIGNED_TEAM, settings.assigned_team_field_id, str(team).strip())
        if rc != 0:
            return rc

    for display_name, env_attr, val in (
        (
            _CF_PRELIMINARY_TESTING,
            settings.preliminary_testing_field_id,
            preliminary_testing,
        ),
        (_CF_TEST_COVERAGE, settings.test_coverage_field_id, test_coverage),
        (_CF_FIXED_IN_BUILD, settings.fixed_in_build_field_id, fixed_in_build),
        (_CF_TEST_LINK, settings.test_link_field_id, test_link),
        (_CF_GIT_PULL_REQUEST, settings.git_pull_request_field_id, git_pull_request),
    ):
        if val is None or not str(val).strip():
            continue
        rc = _put_cf(display_name, env_attr, str(val).strip())
        if rc != 0:
            return rc

    for display_name, env_attr, val, clear, email_flag in (
        (_CF_DEVELOPER, None, developer_email, developer_clear, "--developer-email"),
        (_CF_QA_CONTACT, None, qa_contact_email, qa_contact_clear, "--qa-contact-email"),
        (_CF_DOC_CONTACT, None, doc_contact_email, doc_contact_clear, "--doc-contact-email"),
        (
            _CF_CONTRIBUTORS,
            settings.contributors_field_id,
            contributors_emails,
            contributors_clear,
            "--contributors-email",
        ),
    ):
        clear_flag = email_flag.replace("-email", "-clear")
        rc = _reject_user_field_clear_conflict(
            clear,
            val,
            clear_flag=clear_flag,
            email_flag=email_flag,
            err=err,
        )
        if rc != 0:
            return rc
        if clear:
            rc = _clear_custom_field(batch_fields, display_name, env_attr, client, err)
            if rc != 0:
                return rc
            continue
        if val is None or not str(val).strip():
            continue
        rc = _put_cf(display_name, env_attr, str(val).strip())
        if rc != 0:
            return rc

    return 0


def _match_score_field(query: str, f: dict[str, Any]) -> int:
    q = query.strip().casefold()
    if not q:
        return 0
    fid = str(f.get("id") or "")
    if fid.casefold() == q:
        return 100
    fkey = str(f.get("key") or "")
    if fkey.casefold() == q:
        return 96
    name = str(f.get("name") or "")
    if name.casefold() == q:
        return 92
    clauses = f.get("clauseNames")
    if isinstance(clauses, list):
        for c in clauses:
            if isinstance(c, str) and c.casefold() == q:
                return 88
    if name.casefold().startswith(q):
        return 72
    if q in name.casefold():
        return 65
    if q in fkey.casefold():
        return 60
    if q in fid.casefold():
        return 55
    return 0


def find_best_field_match(
    query: str,
    all_fields: list[dict[str, Any]],
    err: TextIO,
) -> dict[str, Any] | None:
    scored = [(_match_score_field(query, f), f) for f in all_fields]
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0] if scored else 0
    if best == 0:
        print(
            f"jira-cli edit: no field matching {query!r} (see jira-cli fields --all).",
            file=err,
        )
        return None
    top = [f for s, f in scored if s == best]
    if len(top) > 1:
        names = ", ".join(f"{str(x.get('name') or '')!r} ({x.get('id')})" for x in top[:8])
        print(f"jira-cli edit: ambiguous field {query!r} - matches: {names}.", file=err)
        return None
    return top[0]


def _preview_field_value(field_id: str, value: Any) -> str:
    if value is None:
        return "(empty)"
    if field_id == "description":
        t = _fields_description_to_plain_text(value)
        s = (t or "").replace("\n", "\\n")
        if not s:
            return "(empty)"
        return s if len(s) <= 200 else s[:197] + "…"
    if isinstance(value, list):
        parts: list[str] = []
        for x in value[:5]:
            if isinstance(x, dict):
                parts.append(
                    str(x.get("name") or x.get("value") or x.get("displayName") or "") or "…"
                )
            else:
                parts.append(str(x))
        if len(value) > 5:
            parts.append(f"(+{len(value) - 5} more)")
        return ", ".join(parts) if parts else "(empty)"
    if isinstance(value, dict):
        if "displayName" in value:
            return str(value.get("displayName") or "")
        if "name" in value:
            return str(value.get("name") or "")
        if "value" in value:
            return str(value.get("value") or "")
        if field_id == "parent" and "key" in value:
            return str(value.get("key") or "")
        return json.dumps(value, ensure_ascii=False)[:200]
    s = str(value)
    return s if len(s) <= 200 else s[:197] + "…"


def _preview_new_value(field_id: str, coerced: Any) -> str:
    if coerced is None:
        return "(clear)"
    if field_id == "description":
        t = _fields_description_to_plain_text(coerced)
        s = (t or "").replace("\n", "\\n")
        if not s:
            return "(empty)"
        return s if len(s) <= 200 else s[:197] + "…"
    if isinstance(coerced, dict):
        if "name" in coerced:
            return str(coerced.get("name") or "")
        if "accountId" in coerced:
            return f"accountId={coerced.get('accountId')}"
        if "key" in coerced:
            return str(coerced.get("key") or "")
    if isinstance(coerced, list):
        return ", ".join(str(x) for x in coerced[:12])[:200]
    s = str(coerced)
    return s if len(s) <= 200 else s[:197] + "…"


def coerce_payload_for_field_update(
    field_def: dict[str, Any] | None,
    field_id: str,
    raw: str,
    client: JiraClient,
    err: TextIO,
) -> Any | None:
    """CLI string → REST value for PUT /issue fields."""
    if field_id == "description":
        return description_plain_text_to_adf(raw)
    if field_id in ("summary", "environment"):
        return raw
    if field_id in ("assignee", "reporter"):
        if not raw.strip():
            return None
        return user_account_ref_from_email(client, raw, err)
    if field_id == "priority":
        return {"name": raw.strip()}
    if field_id == "issuetype":
        return {"name": raw.strip()}
    if field_id == "parent":
        parent_key = raw.strip()
        if not parent_key:
            return None
        try:
            project_key_from_issue(parent_key)
        except ValueError:
            print("parent value must be an issue key (e.g. PROJ-123).", file=err)
            return None
        return {"key": parent_key.upper()}
    if field_id == "labels":
        return [x.strip() for x in raw.split(",") if x.strip()]
    if field_id == "duedate":
        ds = raw.strip()
        if not ds:
            return None
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", ds):
            print("duedate value must be YYYY-MM-DD.", file=err)
            return None
        return ds
    if field_def:
        return _coerce_custom_field_value(field_def, raw, client=client, err=err)
    print(f"jira-cli edit: cannot coerce value for field {field_id!r}.", file=err)
    return None


def parse_edit_field_args(items: list[str], err: TextIO) -> list[tuple[str, str]] | None:
    out: list[tuple[str, str]] = []
    for item in items:
        if "=" not in item:
            print(
                f'jira-cli edit: --field must be KEY=VALUE (no "=" in {item!r}).',
                file=err,
            )
            return None
        k, _, v = item.partition("=")
        key = k.strip()
        if not key:
            print(f"jira-cli edit: empty field key in --field {item!r}", file=err)
            return None
        out.append((key, v))
    return out


def run_edit_field_specs(
    client: JiraClient,
    _settings: Settings,
    issue_key: str,
    edit_fields: list[str],
    *,
    skip_confirm: bool,
    force_no_input: bool,
    err: TextIO,
) -> tuple[dict[str, Any] | None, int]:
    """
    Resolve ``--field KEY=VALUE`` pairs using GET /rest/api/3/field, preview, confirm, build payload.
    Returns ``(payload, 0)``, ``(None, 2)`` on error, ``(None, 1)`` if the user declined confirmation.
    """
    parsed = parse_edit_field_args(edit_fields, err)
    if parsed is None:
        return None, 2
    try:
        all_fields = client.get_fields()
    except JiraApiError as e:
        print(f"Failed to load fields: {e}", file=err)
        return None, 1

    resolved: list[tuple[str, str, dict[str, Any]]] = []
    for key_query, raw_value in parsed:
        fdef = find_best_field_match(key_query, all_fields, err)
        if fdef is None:
            return None, 2
        fid = str(fdef.get("id") or "")
        if not fid:
            print("jira-cli edit: resolved field has no id.", file=err)
            return None, 2
        resolved.append((key_query, raw_value, fdef))

    field_ids = [str(x[2].get("id") or "") for x in resolved]
    try:
        issue = client.get_issue(issue_key, fields=field_ids)
    except JiraApiError as e:
        print_jira_api_error(e, err, message="Failed to load issue")
        return None, 1

    flds = issue.get("fields") or {}
    batch: dict[str, Any] = {}
    print("", file=err)
    for _key_query, raw_value, fdef in resolved:
        fid = str(fdef.get("id") or "")
        fname = str(fdef.get("name") or fid)
        cur = flds.get(fid)
        cur_s = _preview_field_value(fid, cur)
        if not raw_value.strip():
            coerced = None
        else:
            coerced = coerce_payload_for_field_update(
                fdef,
                fid,
                raw_value,
                client,
                err,
            )
            if coerced is None:
                return None, 2
        new_s = _preview_new_value(fid, coerced)
        print(f"  {fname} ({fid})", file=err)
        print(f"    current: {cur_s}", file=err)
        print(f"    new:     {new_s}", file=err)
        batch[fid] = coerced

    if not skip_confirm:
        if force_no_input or not sys.stdin.isatty():
            print(
                "jira-cli edit: --field needs a TTY to confirm, or pass --yes.",
                file=err,
            )
            return None, 2
        print("Apply these changes? [y/N]: ", file=err, end="")
        try:
            line = input().strip().lower()
        except EOFError:
            return None, 2
        if line not in ("y", "yes"):
            print("Aborted.", file=err)
            return None, 1
    return batch, 0


def apply_edit(
    client: JiraClient,
    settings: Settings,
    issue_key: str,
    *,
    summary: str | None = None,
    description: str | None = None,
    story_points: Any | None = None,
    sprint_id: int | None = None,
    sprint_lookup: str | None = None,
    comment: str | None = None,
    comment_idx: int | None = None,
    delete_comment_idx: int | None = None,
    transition: str | None = None,
    refresh_sprint_cache: bool = False,
    assignee_email: str | None = None,
    assignee_clear: bool = False,
    reporter_email: str | None = None,
    reporter_clear: bool = False,
    priority_name: str | None = None,
    issuetype_name: str | None = None,
    duedate: str | None = None,
    clear_due: bool = False,
    severity: str | None = None,
    team: str | None = None,
    preliminary_testing: str | None = None,
    test_coverage: str | None = None,
    fixed_in_build: str | None = None,
    test_link: str | None = None,
    git_pull_request: str | None = None,
    developer_email: str | None = None,
    developer_clear: bool = False,
    qa_contact_email: str | None = None,
    qa_contact_clear: bool = False,
    doc_contact_email: str | None = None,
    doc_contact_clear: bool = False,
    contributors_emails: str | None = None,
    contributors_clear: bool = False,
    additional_fields: dict[str, Any] | None = None,
    err: TextIO,
) -> int:
    issue_key = issue_key.strip().upper()

    batch_fields: dict[str, Any] = {}
    if summary is not None:
        s = summary.strip()
        if s:
            batch_fields["summary"] = s
    if description is not None:
        batch_fields["description"] = description_plain_text_to_adf(description)

    rc = apply_common_field_updates_to_dict(
        client,
        settings,
        batch_fields,
        story_points=story_points,
        assignee_email=assignee_email,
        assignee_clear=assignee_clear,
        reporter_email=reporter_email,
        reporter_clear=reporter_clear,
        priority_name=priority_name,
        issuetype_name=issuetype_name,
        duedate=duedate,
        clear_due=clear_due,
        severity=severity,
        team=team,
        preliminary_testing=preliminary_testing,
        test_coverage=test_coverage,
        fixed_in_build=fixed_in_build,
        test_link=test_link,
        git_pull_request=git_pull_request,
        developer_email=developer_email,
        developer_clear=developer_clear,
        qa_contact_email=qa_contact_email,
        qa_contact_clear=qa_contact_clear,
        doc_contact_email=doc_contact_email,
        doc_contact_clear=doc_contact_clear,
        contributors_emails=contributors_emails,
        contributors_clear=contributors_clear,
        err=err,
    )
    if rc != 0:
        return rc

    if additional_fields:
        batch_fields.update(additional_fields)

    if batch_fields:
        try:
            client.update_issue_fields(issue_key, batch_fields)
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to update issue fields")
            return 1

    if sprint_lookup:
        sprint_id = resolve_sprint_id(
            client,
            settings,
            issue_key,
            sprint_lookup,
            refresh_sprint_cache=refresh_sprint_cache,
        )

    if sprint_id is not None:
        try:
            client.add_issues_to_sprint(sprint_id, [issue_key])
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to add issue to sprint")
            return 1

    if delete_comment_idx is not None:
        if comment_idx is not None or (comment is not None and str(comment).strip()):
            print(
                "Cannot combine --delete-comment-idx with --comment or --comment-idx.",
                file=err,
            )
            return 2
        if delete_comment_idx < 0:
            print("--delete-comment-idx must be >= 0 (0 = first comment).", file=err)
            return 2
        try:
            comments = client.list_issue_comments(issue_key)
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to list comments")
            return 1
        if delete_comment_idx >= len(comments):
            print(
                f"No comment at index {delete_comment_idx} (issue has {len(comments)} comments).",
                file=err,
            )
            return 2
        cid = comments[delete_comment_idx].get("id")
        if cid is None:
            print(f"Comment at index {delete_comment_idx} has no id.", file=err)
            return 1
        try:
            client.delete_comment(issue_key, str(cid))
        except JiraApiError as e:
            print(f"Failed to delete comment: {e}", file=err)
            return 1
    elif comment_idx is not None:
        if comment is None or not str(comment).strip():
            print("--comment TEXT is required when --comment-idx is set.", file=err)
            return 2
        if comment_idx < 0:
            print("--comment-idx must be >= 0 (0 = first comment).", file=err)
            return 2
        try:
            comments = client.list_issue_comments(issue_key)
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to list comments")
            return 1
        if comment_idx >= len(comments):
            print(
                f"No comment at index {comment_idx} (issue has {len(comments)} comments).",
                file=err,
            )
            return 2
        cid = comments[comment_idx].get("id")
        if cid is None:
            print(f"Comment at index {comment_idx} has no id.", file=err)
            return 1
        try:
            client.update_comment(issue_key, str(cid), comment.strip())
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to update comment")
            return 1
    elif comment is not None and comment.strip():
        try:
            client.add_comment(issue_key, comment.strip())
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to add comment")
            return 1

    if transition:
        tid = resolve_transition_id(client, issue_key, transition)
        try:
            client.transition_issue(issue_key, tid)
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to transition")
            return 1

    return 0
