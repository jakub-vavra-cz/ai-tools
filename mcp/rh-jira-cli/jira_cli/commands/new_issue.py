"""Create a new issue (POST /rest/api/3/issue)."""

from __future__ import annotations

import json
from typing import Any, TextIO

from jira_cli.api import (
    JiraApiError,
    JiraClient,
    description_plain_text_to_adf,
    print_jira_api_error,
    project_key_from_issue,
)
from jira_cli.commands.edit_issue import (
    apply_common_field_updates_to_dict,
    resolve_sprint_id_for_project,
    resolve_transition_id,
)
from jira_cli.config import Settings

DEFAULT_NEW_ISSUE_DESCRIPTION = (
    "Lorem ipsum dolor sit amet, dominus crudelis et perblandus inerte otio languet. "
    "Quia taedium ingens animo eius insidet, servos miseros ad opera prorsus inutilia ac "
    "supervacua compellit. Huc illuc harenam movere, fossas fodere et statim replere iubet, "
    "non utilitatis causa, sed ut spatium vacuum diei sui fallat. Servis laborantibus sine "
    "fructu, ipse ex alto spectat, fastidio tantummodo levato.\n\n"
    "Cum vero solitudine laborat et neminem habet quocum loquatur, conventus futiles ac "
    "sine fine convocat. Omnes subditi ac mancipia subito arcessuntur ut in aula magna "
    "inanes horas conterant. Ibi, dominus de nihilo fabulans, quaestiones sine responso "
    "proponit et sententias vacuas profert, tantum ut vocem suam audiat.\n\n"
    '    "Nullum consilium capitur, nulla res agitur; tantummodo tempus pretiosum omnium '
    'funditus perditur et frustratio maxima gignitur."\n\n'
    "Quisque in conventu sedens suspirat, dum dominus solitudinem suam simulatione negotii "
    "tegit. Nemo discedere audet, nemo tacere potest, dum totus dies inefficaciter "
    "effluit, et labor verus neglectus iacet."
)


def execute_new_issue(
    client: JiraClient,
    settings: Settings,
    *,
    project: str,
    summary: str,
    issue_type: str,
    issuetype_name: str | None = None,
    description: str | None = None,
    story_points: float | None = None,
    sprint: str | None = None,
    comment: str | None = None,
    transition: str | None = None,
    refresh_sprint_cache: bool = False,
    assignee_email: str | None = None,
    reporter_email: str | None = None,
    priority_name: str | None = None,
    duedate: str | None = None,
    severity: str | None = None,
    preliminary_testing: str | None = None,
    test_coverage: str | None = None,
    fixed_in_build: str | None = None,
    test_link: str | None = None,
    developer_email: str | None = None,
    qa_contact_email: str | None = None,
    doc_contact_email: str | None = None,
    contributors_emails: str | None = None,
    parent_key: str | None = None,
    err: TextIO,
) -> tuple[dict[str, Any] | None, int]:
    """
    Create an issue and optional sprint/comment/transition follow-ups.

    Returns ``(payload, 0)`` on success where ``payload`` has ``create`` (API object) and
    optional ``issue_key``; ``(None, rc)`` on failure (messages on ``err``).
    """
    pk = project.strip()
    sm = summary.strip()
    if not pk:
        print("jira-cli new: --project must not be empty.", file=err)
        return None, 2
    if not sm:
        print("jira-cli new: --summary must not be empty.", file=err)
        return None, 2
    it = issue_type.strip()
    if not it:
        print("jira-cli new: --type must not be empty.", file=err)
        return None, 2

    type_display = (
        issuetype_name.strip() if issuetype_name is not None and str(issuetype_name).strip() else it
    )

    fields: dict[str, Any] = {
        "project": {"key": pk},
        "summary": sm,
        "issuetype": {"name": type_display},
    }
    desc = description if description is not None else DEFAULT_NEW_ISSUE_DESCRIPTION
    fields["description"] = description_plain_text_to_adf(desc)

    if parent_key is not None:
        raw_parent = parent_key.strip()
        if not raw_parent:
            print("jira-cli new: --parent must not be empty.", file=err)
            return None, 2
        try:
            project_key_from_issue(raw_parent)
        except ValueError:
            print(
                "jira-cli new: --parent must be an issue key (e.g. PROJ-123).",
                file=err,
            )
            return None, 2
        fields["parent"] = {"key": raw_parent.upper()}

    rc = apply_common_field_updates_to_dict(
        client,
        settings,
        fields,
        story_points=story_points,
        assignee_email=assignee_email,
        assignee_clear=False,
        reporter_email=reporter_email,
        priority_name=priority_name,
        issuetype_name=None,
        duedate=duedate,
        clear_due=False,
        severity=severity,
        preliminary_testing=preliminary_testing,
        test_coverage=test_coverage,
        fixed_in_build=fixed_in_build,
        test_link=test_link,
        developer_email=developer_email,
        qa_contact_email=qa_contact_email,
        doc_contact_email=doc_contact_email,
        contributors_emails=contributors_emails,
        err=err,
    )
    if rc != 0:
        return None, rc

    try:
        data = client.create_issue(fields)
    except JiraApiError as e:
        print_jira_api_error(e, err)
        return None, 1

    issue_key = data.get("key")
    if not isinstance(issue_key, str) or not issue_key.strip():
        return {"issue_key": None, "create": data}, 0

    key = issue_key.strip()

    sprint_lookup = sprint if sprint and not str(sprint).strip().isdigit() else None
    sprint_id: int | None = int(sprint) if sprint and str(sprint).strip().isdigit() else None

    if sprint_lookup:
        try:
            sprint_id = resolve_sprint_id_for_project(
                client,
                pk,
                sprint_lookup,
                refresh_sprint_cache=refresh_sprint_cache,
            )
        except SystemExit as e:
            print(str(e), file=err)
            return None, 1

    if sprint_id is not None:
        try:
            client.add_issues_to_sprint(sprint_id, [key])
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to add issue to sprint")
            return None, 1

    if comment is not None and str(comment).strip():
        try:
            client.add_comment(key, comment.strip())
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to add comment")
            return None, 1

    if transition is not None and str(transition).strip():
        try:
            tid = resolve_transition_id(client, key, str(transition).strip())
        except SystemExit as e:
            print(str(e), file=err)
            return None, 1
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to resolve transition")
            return None, 1
        try:
            client.transition_issue(key, tid)
        except JiraApiError as e:
            print_jira_api_error(e, err, message="Failed to transition")
            return None, 1

    return {"issue_key": key, "create": data}, 0


def run_new(
    client: JiraClient,
    settings: Settings,
    *,
    project: str,
    summary: str,
    issue_type: str,
    issuetype_name: str | None = None,
    description: str | None = None,
    story_points: float | None = None,
    sprint: str | None = None,
    comment: str | None = None,
    transition: str | None = None,
    refresh_sprint_cache: bool = False,
    assignee_email: str | None = None,
    reporter_email: str | None = None,
    priority_name: str | None = None,
    duedate: str | None = None,
    severity: str | None = None,
    preliminary_testing: str | None = None,
    test_coverage: str | None = None,
    fixed_in_build: str | None = None,
    test_link: str | None = None,
    developer_email: str | None = None,
    qa_contact_email: str | None = None,
    doc_contact_email: str | None = None,
    contributors_emails: str | None = None,
    parent_key: str | None = None,
    as_json: bool = False,
    out: TextIO,
    err: TextIO,
) -> int:
    """Create an issue with required project key and summary."""
    payload, rc = execute_new_issue(
        client,
        settings,
        project=project,
        summary=summary,
        issue_type=issue_type,
        issuetype_name=issuetype_name,
        description=description,
        story_points=story_points,
        sprint=sprint,
        comment=comment,
        transition=transition,
        refresh_sprint_cache=refresh_sprint_cache,
        assignee_email=assignee_email,
        reporter_email=reporter_email,
        priority_name=priority_name,
        duedate=duedate,
        severity=severity,
        preliminary_testing=preliminary_testing,
        test_coverage=test_coverage,
        fixed_in_build=fixed_in_build,
        test_link=test_link,
        developer_email=developer_email,
        qa_contact_email=qa_contact_email,
        doc_contact_email=doc_contact_email,
        contributors_emails=contributors_emails,
        parent_key=parent_key,
        err=err,
    )
    if rc != 0:
        return rc
    assert payload is not None
    data = payload["create"]
    key = payload.get("issue_key")

    if key is None:
        json.dump(data, out, indent=2)
        out.write("\n")
        return 0

    if as_json:
        json.dump(data, out, indent=2)
        out.write("\n")
    else:
        print(key, file=out)

    print(key, file=err)
    return 0
