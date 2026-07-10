"""Shared data shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueueItem:
    ref: str
    title: str
    url: str
    updated_at: str
    draft: bool = False
    repository: str | None = None
    number: int | None = None
    project: str | None = None
    iid: int | None = None
    work_in_progress: bool = False
    state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ref": self.ref,
            "title": self.title,
            "url": self.url,
            "updated_at": self.updated_at,
            "draft": self.draft,
        }
        if self.state is not None:
            data["state"] = self.state
        if self.repository is not None:
            data["repository"] = self.repository
        if self.number is not None:
            data["number"] = self.number
        if self.project is not None:
            data["project"] = self.project
        if self.iid is not None:
            data["iid"] = self.iid
        if self.work_in_progress:
            data["work_in_progress"] = self.work_in_progress
        return data


@dataclass
class DoneItem:
    action: str
    ref: str
    title: str
    url: str
    created_at: str
    kind: str
    detail: str | None = None
    events: list[DoneItem] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "action": self.action,
            "ref": self.ref,
            "title": self.title,
            "url": self.url,
            "created_at": self.created_at,
            "kind": self.kind,
        }
        if self.detail:
            data["detail"] = self.detail
        if self.events:
            seen: set[str] = set()
            actions: list[str] = []
            for event in reversed(self.events):
                if event.action in seen:
                    continue
                seen.add(event.action)
                actions.append(event.action)
            data["actions"] = actions
            data["events"] = [event.to_dict() for event in self.events]
        return data


@dataclass
class DoneResult:
    items: list[DoneItem] = field(default_factory=list)
    error: str | None = None
    username: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.error:
            data: dict[str, Any] = {"count": 0, "items": [], "error": self.error}
        else:
            data = {
                "count": len(self.items),
                "items": [item.to_dict() for item in self.items],
            }
        if self.username:
            data["username"] = self.username
        return data


@dataclass
class CategoryResult:
    items: list[QueueItem] = field(default_factory=list)
    drafts: list[QueueItem] = field(default_factory=list)
    error: str | None = None

    def to_dict(self, *, include_drafts: bool = False) -> dict[str, Any]:
        if self.error:
            return {"count": 0, "items": [], "error": self.error}
        data: dict[str, Any] = {
            "count": len(self.items),
            "items": [item.to_dict() for item in self.items],
        }
        if include_drafts or self.drafts:
            data["drafts"] = [item.to_dict() for item in self.drafts]
        return data
