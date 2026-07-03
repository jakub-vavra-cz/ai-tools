"""Minimal Jira REST API client (Cloud v3 + Agile)."""

from __future__ import annotations

import json
from typing import Any, Optional, TextIO

import requests

from jira_cli.config import Settings
from jira_cli import sprint_cache


class JiraApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def print_jira_api_error(
    e: JiraApiError,
    err: TextIO,
    *,
    message: str | None = None,
) -> None:
    if message is not None:
        print(f"{message}: {e}", file=err)
    else:
        print(e, file=err)
    if e.body:
        print(e.body, file=err)


def user_account_ref_from_email(
    client: "JiraClient",
    email: str,
    err: TextIO,
) -> dict[str, Any] | None:
    """Resolve an email to ``{\"accountId\": ...}`` for REST user fields; print errors to ``err``."""
    raw = email.strip()
    u = client.find_user_by_email(raw)
    if not u:
        print(f"No unique Jira user for email {raw!r} (user search).", file=err)
        return None
    aid = u.get("accountId")
    if isinstance(aid, str) and aid.strip():
        return {"accountId": aid.strip()}
    print(f"User from {raw!r} has no accountId.", file=err)
    return None


def user_account_ref_list_from_email(
    client: "JiraClient",
    emails: str,
    err: TextIO,
) -> list[dict[str, Any]] | None:
    """
    Build REST values for multi-user custom fields (list of account-id dicts).

    ``emails`` is one address or comma-separated addresses (whitespace around commas is ignored).
    """
    parts = [p.strip() for p in emails.split(",") if p.strip()]
    if not parts:
        print("No email addresses provided for multi-user field.", file=err)
        return None
    out: list[dict[str, Any]] = []
    for p in parts:
        one = user_account_ref_from_email(client, p, err)
        if one is None:
            return None
        out.append(one)
    return out


class JiraClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"
        self._session.headers["Content-Type"] = "application/json"
        if settings.auth:
            self._session.auth = settings.auth

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._settings.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Any = None,
    ) -> Any:
        url = self._url(path)
        kwargs: dict[str, Any] = {}
        if params:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["json"] = json_body
        r = self._session.request(method, url, **kwargs)
        if r.status_code >= 400:
            raise JiraApiError(
                f"{method} {path} failed: {r.status_code} {r.reason}",
                status_code=r.status_code,
                body=r.text[:2000] if r.text else None,
            )
        if not r.content:
            return None
        try:
            return r.json()
        except json.JSONDecodeError:
            return r.text

    def search(
        self,
        jql: str,
        *,
        fields: Optional[list[str]] = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """JQL search via enhanced API (POST /rest/api/3/search/jql)."""
        payload: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
        }
        if fields:
            payload["fields"] = fields
        return self.request("POST", "/rest/api/3/search/jql", json_body=payload)

    def get_issue(
        self,
        issue_key: str,
        *,
        fields: Optional[list[str]] = None,
        all_fields: bool = False,
        expand: Optional[str] = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {}
        if all_fields:
            params["fields"] = "*all"
        elif fields:
            params["fields"] = ",".join(fields)
        if expand:
            params["expand"] = expand
        return self.request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params=params or None,
        )

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create an issue; POST /rest/api/3/issue."""
        data = self.request("POST", "/rest/api/3/issue", json_body={"fields": fields})
        if data is None:
            raise JiraApiError("POST /rest/api/3/issue returned empty body")
        if not isinstance(data, dict):
            raise JiraApiError("POST /rest/api/3/issue returned unexpected payload")
        return data

    def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        """
        Find a user by email (GET /rest/api/3/user/search).

        Prefers an exact case-insensitive match on emailAddress. If there is no
        exact match and the search returns exactly one user, returns that user;
        otherwise returns None when multiple candidates lack an exact email match.
        """
        em = email.strip()
        if not em:
            return None
        data = self.request("GET", "/rest/api/3/user/search", params={"query": em})
        if not isinstance(data, list) or not data:
            return None
        want = em.lower()
        exact = [
            u
            for u in data
            if isinstance(u.get("emailAddress"), str) and u["emailAddress"].strip().lower() == want
        ]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return exact[0]
        if len(data) == 1:
            return data[0]
        return None

    def get_fields(self) -> list[dict[str, Any]]:
        """All issue fields (system + custom); GET /rest/api/3/field."""
        data = self.request("GET", "/rest/api/3/field")
        if data is None:
            return []
        if not isinstance(data, list):
            raise JiraApiError("GET /rest/api/3/field returned unexpected payload")
        return data

    def get_statuses(self) -> list[dict[str, Any]]:
        """All statuses visible to the user; GET /rest/api/3/status."""
        data = self.request("GET", "/rest/api/3/status")
        if data is None:
            return []
        if not isinstance(data, list):
            raise JiraApiError("GET /rest/api/3/status returned unexpected payload")
        return data

    def update_issue_fields(self, issue_key: str, fields: dict[str, Any]) -> None:
        self.request("PUT", f"/rest/api/3/issue/{issue_key}", json_body={"fields": fields})

    def add_comment(self, issue_key: str, plain_text: str) -> dict[str, Any]:
        body = _plain_text_to_adf(plain_text)
        return self.request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/comment",
            json_body={"body": body},
        )

    def list_issue_comments(self, issue_key: str) -> list[dict[str, Any]]:
        """All comments (paginated GET /rest/api/3/issue/{key}/comment). Order matches Jira (oldest first)."""
        out: list[dict[str, Any]] = []
        start = 0
        page_size = 50
        while True:
            data = self.request(
                "GET",
                f"/rest/api/3/issue/{issue_key}/comment",
                params={"startAt": str(start), "maxResults": str(page_size)},
            )
            if not isinstance(data, dict):
                break
            chunk = data.get("comments") or []
            out.extend(chunk)
            total = data.get("total")
            if not chunk:
                break
            if total is not None and len(out) >= total:
                break
            if len(chunk) < page_size:
                break
            start += len(chunk)
        return out

    def update_comment(self, issue_key: str, comment_id: str, plain_text: str) -> dict[str, Any]:
        body = _plain_text_to_adf(plain_text)
        return self.request(
            "PUT",
            f"/rest/api/3/issue/{issue_key}/comment/{comment_id}",
            json_body={"body": body},
        )

    def delete_comment(self, issue_key: str, comment_id: str) -> None:
        self.request("DELETE", f"/rest/api/3/issue/{issue_key}/comment/{comment_id}")

    def get_transitions(self, issue_key: str) -> dict[str, Any]:
        return self.request("GET", f"/rest/api/3/issue/{issue_key}/transitions")

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        self.request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json_body={"transition": {"id": transition_id}},
        )

    def boards_for_project(
        self,
        project_key: str,
        *,
        board_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        GET /rest/agile/1.0/board

        board_type: optional Agile API `type` filter (e.g. scrum, kanban).
        """
        params: dict[str, str] = {"projectKeyOrId": project_key}
        if board_type:
            params["type"] = board_type
        return self.request(
            "GET",
            "/rest/agile/1.0/board",
            params=params,
        )

    def boards_scrum_paginated(
        self,
        *,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """GET /rest/agile/1.0/board with ``type=scrum`` only (no ``projectKeyOrId``)."""
        params: dict[str, str] = {
            "startAt": str(start_at),
            "maxResults": str(max_results),
            "type": "scrum",
        }
        return self.request("GET", "/rest/agile/1.0/board", params=params)

    def all_sprints_from_all_scrum_boards(
        self,
        *,
        state: Optional[str] = "future,active,closed",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Every sprint from every Scrum board the caller can see, deduped by sprint id,
        plus per-board sprint lists for cache persistence.

        Used when resolving a sprint **name** without a project key (slower than
        ``all_sprints_for_project``).
        """
        st = state if state is not None else "future,active,closed"
        by_id: dict[int, dict[str, Any]] = {}
        boards_payload: list[dict[str, Any]] = []
        start = 0
        page = 50
        while True:
            data = self.boards_scrum_paginated(start_at=start, max_results=page)
            boards = data.get("values") or []
            for b in boards:
                bid = int(b["id"])
                bname = str(b.get("name") or "")
                board_sprints = self.all_sprints_for_board(bid, state=st)
                boards_payload.append({"id": bid, "name": bname, "sprints": board_sprints})
                for s in board_sprints:
                    sid = int(s["id"])
                    if sid not in by_id:
                        by_id[sid] = s
            if data.get("isLast") or not boards:
                break
            start += len(boards)
        return list(by_id.values()), boards_payload

    def sprints_for_board(
        self,
        board_id: int,
        *,
        state: Optional[str] = None,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "startAt": str(start_at),
            "maxResults": str(max_results),
        }
        if state:
            params["state"] = state
        return self.request(
            "GET",
            f"/rest/agile/1.0/board/{board_id}/sprint",
            params=params,
        )

    def all_sprints_for_board(
        self,
        board_id: int,
        *,
        state: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """All sprints on a board (paginated GET /board/{id}/sprint).

        Kanban boards and other non-sprint boards often return 400/404 for this endpoint;
        those are treated as no sprints (empty list).
        """
        out: list[dict[str, Any]] = []
        start = 0
        page_size = 50
        while True:
            try:
                data = self.sprints_for_board(
                    board_id, state=state, start_at=start, max_results=page_size
                )
            except JiraApiError as e:
                if e.status_code in (400, 404) and start == 0:
                    return []
                raise
            values = data.get("values") or []
            out.extend(values)
            if data.get("isLast") or not values:
                break
            start += len(values)
        return out

    def all_sprints_for_project(
        self,
        project_key: str,
        *,
        state: Optional[str] = "future,active,closed",
        use_cache: bool = True,
        refresh_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """All sprints on every Scrum board in the project; deduped by sprint id.

        Default state filter includes closed sprints so sprint name resolution can target past
        sprints. Reads local file cache first; refetches only on cache miss or when
        ``refresh_cache`` is True (``--refresh-sprint-cache``).
        """
        st = state if state is not None else "future,active,closed"
        if use_cache and not refresh_cache and sprint_cache.is_enabled():
            cached = sprint_cache.load_merged_sprints(project_key, st)
            if cached is not None:
                return cached

        boards_data = self.boards_for_project(project_key, board_type="scrum")
        boards = boards_data.get("values") or []
        if not boards:
            return []
        by_id: dict[int, dict[str, Any]] = {}
        boards_payload: list[dict[str, Any]] = []
        for b in boards:
            bid = int(b["id"])
            bname = b.get("name") or ""
            sprints = self.all_sprints_for_board(bid, state=state)
            boards_payload.append({"id": bid, "name": bname, "sprints": sprints})
            for s in sprints:
                sid = int(s["id"])
                if sid not in by_id:
                    by_id[sid] = s
        result = list(by_id.values())
        if use_cache and sprint_cache.is_enabled():
            sprint_cache.save_merged_sprints(project_key, st, result, boards_payload)
        return result

    def add_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        self.request(
            "POST",
            f"/rest/agile/1.0/sprint/{sprint_id}/issue",
            json_body={"issues": issue_keys},
        )

    def get_create_issue_issuetypes(self, project_key: str) -> list[dict[str, Any]]:
        """Issue types available when creating in a project (paginated createmeta)."""
        out: list[dict[str, Any]] = []
        start = 0
        page_size = 50
        while True:
            data = self.request(
                "GET",
                f"/rest/api/3/issue/createmeta/{project_key}/issuetypes",
                params={"startAt": str(start), "maxResults": str(page_size)},
            )
            if not isinstance(data, dict):
                raise JiraApiError("GET createmeta issuetypes returned unexpected payload")
            chunk = data.get("issueTypes") or []
            out.extend(chunk)
            total = data.get("total")
            if not chunk:
                break
            if total is not None and len(out) >= int(total):
                break
            if len(chunk) < page_size:
                break
            start += len(chunk)
        return out

    def bulk_move_issues(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit bulk move; POST /rest/api/3/bulk/issues/move."""
        data = self.request(
            "POST",
            "/rest/api/3/bulk/issues/move",
            json_body=payload,
        )
        if data is None:
            raise JiraApiError("POST /rest/api/3/bulk/issues/move returned empty body")
        if not isinstance(data, dict):
            raise JiraApiError("POST /rest/api/3/bulk/issues/move returned unexpected payload")
        return data

    def get_bulk_task(self, task_id: str) -> dict[str, Any]:
        """Poll bulk operation progress; GET /rest/api/3/bulk/queue/{taskId}."""
        data = self.request("GET", f"/rest/api/3/bulk/queue/{task_id}")
        if data is None:
            raise JiraApiError(f"GET /rest/api/3/bulk/queue/{task_id} returned empty body")
        if not isinstance(data, dict):
            raise JiraApiError(f"GET /rest/api/3/bulk/queue/{task_id} returned unexpected payload")
        return data


def _plain_text_to_adf(text: str) -> dict[str, Any]:
    paragraphs = text.split("\n\n") if "\n\n" in text else [text]
    content: list[dict[str, Any]] = []
    for para in paragraphs:
        lines = para.split("\n")
        inner: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            if i:
                inner.append({"type": "hardBreak"})
            inner.append({"type": "text", "text": line})
        content.append({"type": "paragraph", "content": inner})
    return {"type": "doc", "version": 1, "content": content}


def description_plain_text_to_adf(text: str) -> dict[str, Any]:
    """Atlassian Document Format for ``fields.description`` (REST API v3). Empty text clears the description."""
    t = text.strip()
    if not t:
        return {"type": "doc", "version": 1, "content": []}
    return _plain_text_to_adf(t)


def project_key_from_issue(issue_key: str) -> str:
    if "-" not in issue_key:
        raise ValueError(f"Invalid issue key: {issue_key}")
    return issue_key.split("-", 1)[0]
