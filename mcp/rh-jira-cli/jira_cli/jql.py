"""Build JQL for listing issues."""

from __future__ import annotations


def jql_user_field_equals_principal(
    display_name: str,
    field_id: str | None,
    principal: str,
) -> str:
    """
    JQL fragment ``<field> = <principal>`` for a user-picker field.

    ``principal`` is ``currentUser()`` or a quoted user id from `jql_user_identity_for_clause`.

    Optional numeric or ``customfield_*`` id maps to ``customfield_N``; otherwise the field is
    addressed by display name (quoted).
    """
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid.startswith("customfield_"):
            return f"{fid} = {principal}"
        if fid.isdigit():
            return f"customfield_{fid} = {principal}"
    return f"{jql_quote(display_name)} = {principal}"


def jql_user_field_equals_current_user(display_name: str, field_id: str | None) -> str:
    """JQL fragment ``<field> = currentUser()`` (see `jql_user_field_equals_principal`)."""
    return jql_user_field_equals_principal(display_name, field_id, "currentUser()")


def jql_multi_user_field_in_principal(
    display_name: str,
    field_id: str | None,
    principal: str,
) -> str:
    """
    JQL fragment ``<field> in (<principal>)`` for a multi-user-picker field.

    REST payloads expose selected users (including ``emailAddress``); JQL matches by the same
    user identity as ``assignee`` / single user-picker fields (``currentUser()`` or quoted
    account id from `jql_user_identity_for_clause`).

    ``principal`` is ``currentUser()`` or a quoted user id from `jql_user_identity_for_clause`.
    """
    if field_id and isinstance(field_id, str) and field_id.strip():
        fid = field_id.strip()
        if fid.startswith("customfield_"):
            return f"{fid} in ({principal})"
        if fid.isdigit():
            return f"customfield_{fid} in ({principal})"
    return f"{jql_quote(display_name)} in ({principal})"


def jql_multi_user_field_in_current_user(display_name: str, field_id: str | None) -> str:
    """JQL fragment ``<field> in (currentUser())`` (see `jql_multi_user_field_in_principal`)."""
    return jql_multi_user_field_in_principal(display_name, field_id, "currentUser()")


def jql_user_identity_for_clause(user: dict[str, object]) -> str | None:
    """
    Quoted JQL user identifier for ``assignee`` / user-picker custom fields (Cloud ``accountId``
    or Server ``name`` / ``key``). Same resolution as ``assignee_clause_for_user``.
    """
    aid = user.get("accountId")
    if isinstance(aid, str) and aid.strip():
        return jql_quote(aid.strip())
    name = user.get("name")
    if isinstance(name, str) and name.strip():
        return jql_quote(name.strip())
    key = user.get("key")
    if isinstance(key, str) and key.strip():
        return jql_quote(key.strip())
    return None


def list_mine_base_or_clause(contributors_field_id: str | None = None) -> str:
    """
    Issues where the authenticated user is assignee, Developer, QA Contact, Doc Contact,
    or listed in the multi-user **Contributors** field.

    ``currentUser()`` matches the API user (same identity as ``JIRA_EMAIL`` on Cloud).
    Contributors uses ``in (currentUser())`` (multi-user picker JQL).
    """
    parts = [
        "assignee = currentUser()",
        jql_user_field_equals_current_user("Developer", None),
        jql_user_field_equals_current_user("QA Contact", None),
        jql_user_field_equals_current_user("Doc Contact", None),
        jql_multi_user_field_in_current_user("Contributors", contributors_field_id),
    ]
    return "(" + " OR ".join(parts) + ")"


def list_user_base_or_clause(
    user: dict[str, object],
    *,
    contributors_field_id: str | None = None,
) -> str | None:
    """
    Same roles as `list_mine_base_or_clause`, but for a resolved user (``list <email>``).

    Uses the same JQL identity as ``assignee = …`` for each user-picker / Contributors clause.
    """
    ident = jql_user_identity_for_clause(user)
    if ident is None:
        return None
    parts = [
        f"assignee = {ident}",
        jql_user_field_equals_principal("Developer", None, ident),
        jql_user_field_equals_principal("QA Contact", None, ident),
        jql_user_field_equals_principal("Doc Contact", None, ident),
        jql_multi_user_field_in_principal("Contributors", contributors_field_id, ident),
    ]
    return "(" + " OR ".join(parts) + ")"


def my_issues_jql(contributors_field_id: str | None = None) -> str:
    """JQL for issues tied to the current user (assignee or role fields per ``list_mine_base_or_clause``)."""
    return f"{list_mine_base_or_clause(contributors_field_id)} ORDER BY updated DESC"


def add_jql_and_before_order(jql: str, condition: str) -> str:
    """Insert AND (condition) before the trailing ORDER BY clause."""
    parts = jql.rsplit(" ORDER BY ", 1)
    if len(parts) != 2:
        return f"({jql.strip()}) AND ({condition})"
    main, order_by = parts
    return f"({main.strip()}) AND ({condition}) ORDER BY {order_by}"


def jql_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def combine_list_filters(
    *,
    issue_type_name: str | None,
    extra_jql: str | None,
    sprint_id: int | None = None,
) -> str | None:
    """AND together optional ``issuetype``, ``sprint``, and user ``--jql`` fragments."""
    parts: list[str] = []
    if issue_type_name is not None and issue_type_name.strip():
        parts.append(f"issuetype = {jql_quote(issue_type_name.strip())}")
    if sprint_id is not None:
        parts.append(f"sprint = {int(sprint_id)}")
    if extra_jql is not None and extra_jql.strip():
        parts.append(f"({extra_jql.strip()})")
    if not parts:
        return None
    return " AND ".join(parts)


def unfinished_condition_from_statuses(statuses: list[dict[str, object]]) -> str:
    """
    Build a robust unfinished condition from Jira statuses.

    Terminal states are identified by:
    - statusCategory.key == "done" (preferred)
    - fallback name match for common terminal names (done/closed/resolved/completed)
    """
    terminal_names: set[str] = set()
    for status in statuses:
        name_obj = status.get("name")
        if not isinstance(name_obj, str):
            continue
        name = name_obj.strip()
        if not name:
            continue

        cat = status.get("statusCategory")
        cat_key = ""
        if isinstance(cat, dict):
            key_obj = cat.get("key")
            if isinstance(key_obj, str):
                cat_key = key_obj.strip().lower()

        lower_name = name.lower()
        if cat_key == "done" or lower_name in {
            "done",
            "closed",
            "resolved",
            "complete",
            "completed",
        }:
            terminal_names.add(name)

    if not terminal_names:
        return 'statusCategory != "Done"'

    items = ", ".join(jql_quote(n) for n in sorted(terminal_names, key=str.casefold))
    return f"status NOT IN ({items})"


def build_list_jql(
    *,
    unfinished_clause: str | None = None,
    extra_jql: str | None,
    contributors_field_id: str | None = None,
) -> str:
    """JQL for `jira-cli list-mine`: my issues, optional non-done filter, optional extra AND."""
    jql = my_issues_jql(contributors_field_id)
    if unfinished_clause:
        jql = add_jql_and_before_order(jql, unfinished_clause)
    if extra_jql:
        jql = f"({jql.rsplit(' ORDER BY ', 1)[0]}) AND ({extra_jql}) ORDER BY updated DESC"
    return jql


def build_list_by_assignee_jql(
    user: dict[str, object],
    *,
    unfinished_clause: str | None = None,
    extra_jql: str | None = None,
    contributors_field_id: str | None = None,
) -> str:
    """
    JQL for `jira-cli list <email>`: same OR as `list-mine` (assignee, Developer, QA Contact,
    Doc Contact, Contributors) but with the resolved user's JQL identity instead of ``currentUser()``.
    """
    base = list_user_base_or_clause(
        user,
        contributors_field_id=contributors_field_id,
    )
    if base is None:
        raise ValueError("resolved user has no JQL identity for list")
    jql = f"{base} ORDER BY updated DESC"
    if unfinished_clause:
        jql = add_jql_and_before_order(jql, unfinished_clause)
    if extra_jql:
        jql = f"({jql.rsplit(' ORDER BY ', 1)[0]}) AND ({extra_jql}) ORDER BY updated DESC"
    return jql


def assignee_clause_for_user(user: dict[str, object]) -> str | None:
    """Build ``assignee = …`` JQL from a /user/search User object (Cloud accountId or Server name/key)."""
    aid = user.get("accountId")
    if isinstance(aid, str) and aid.strip():
        return f"assignee = {jql_quote(aid.strip())}"
    name = user.get("name")
    if isinstance(name, str) and name.strip():
        return f"assignee = {jql_quote(name.strip())}"
    key = user.get("key")
    if isinstance(key, str) and key.strip():
        return f"assignee = {jql_quote(key.strip())}"
    return None
