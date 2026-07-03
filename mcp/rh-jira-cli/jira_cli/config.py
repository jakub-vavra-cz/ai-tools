"""Load settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _strip_trailing_slash(url: str) -> str:
    return url.rstrip("/")


@dataclass
class Settings:
    base_url: str
    email: Optional[str]
    api_token: Optional[str]
    preliminary_testing_field_id: Optional[str]
    fixed_in_build_field_id: Optional[str]
    test_coverage_field_id: Optional[str]
    test_link_field_id: Optional[str]
    git_pull_request_field_id: Optional[str]
    story_points_field_id: Optional[str]
    contributors_field_id: Optional[str]
    assigned_team_field_id: Optional[str]

    @property
    def auth(self) -> tuple[str, str] | None:
        if self.email and self.api_token:
            return (self.email, self.api_token)
        return None


def load_settings(
    env: Optional[dict[str, str]] = None,
) -> Settings:
    e = env if env is not None else os.environ
    base = e.get("JIRA_URL", "").strip()
    if not base:
        raise ConfigError(
            "JIRA_URL is required (e.g. https://your-domain.atlassian.net)",
        )
    email = (e.get("JIRA_EMAIL") or e.get("JIRA_USER") or "").strip() or None
    api_token = (e.get("JIRA_API_TOKEN") or "").strip() or None

    if not (email and api_token):
        raise ConfigError(
            "Set JIRA_EMAIL and JIRA_API_TOKEN.",
        )

    prelim_test_id = (e.get("JIRA_PRELIMINARY_TESTING_FIELD_ID") or "").strip() or None
    fixed_build_id = (e.get("JIRA_FIXED_IN_BUILD_FIELD_ID") or "").strip() or None
    test_cov_id = (e.get("JIRA_TEST_COVERAGE_FIELD_ID") or "").strip() or None
    test_link_id = (e.get("JIRA_TEST_LINK_FIELD_ID") or "").strip() or None
    git_pr_id = (e.get("JIRA_GIT_PULL_REQUEST_FIELD_ID") or "").strip() or None
    story_points_id = (e.get("JIRA_STORY_POINTS_FIELD_ID") or "").strip() or None
    contributors_id = (e.get("JIRA_CONTRIBUTORS_FIELD_ID") or "").strip() or None
    assigned_team_id = (e.get("JIRA_ASSIGNED_TEAM_FIELD_ID") or "").strip() or None

    return Settings(
        base_url=_strip_trailing_slash(base),
        email=email,
        api_token=api_token,
        preliminary_testing_field_id=prelim_test_id,
        fixed_in_build_field_id=fixed_build_id,
        test_coverage_field_id=test_cov_id,
        test_link_field_id=test_link_id,
        git_pull_request_field_id=git_pr_id,
        story_points_field_id=story_points_id,
        contributors_field_id=contributors_id,
        assigned_team_field_id=assigned_team_id,
    )


class ConfigError(Exception):
    pass
