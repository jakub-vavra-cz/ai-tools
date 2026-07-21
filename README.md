# ai-tools

Personal helper tools for working with AI: Cursor skills and MCP servers.

## Layout

| Path | Contents |
|------|----------|
| `skills/` | Cursor agent skills |
| `tools/` | Installable CLI helpers (`pip install -e tools`; see [tools/README.md](tools/README.md)) |
| `mcp/` | MCP server packages (CLI + stdio servers for Cursor and other clients) |

Each MCP package has its own `README.md` with install steps and Cursor `mcp.json` examples.

## MCP servers

### git-worktrees

Automates cloning SSSD-related forks with upstream remotes and creating topic branches in new git worktrees

- Console entry: `git-worktrees-mcp`
- See [mcp/git-worktrees/README.md](mcp/git-worktrees/README.md)

### git-stats

CLI and MCP server for GitHub/GitLab PR/MR queues: review-requested, authored PRs with changes requested, and authored PRs with no reviewer. Repo-scan fallback uses git clones under `GIT_PATH`.

- CLI: `git-stats`, `git-stats reviews`, `git-stats authored`, `git-stats done`
- MCP tools: `git_stats`, `git_stats_reviews`, `git_stats_done`
- See [mcp/git-stats/README.md](mcp/git-stats/README.md)

### rh-jira-cli

CLI and MCP server for Jira Cloud (REST API v3 + Agile): list/search/show issues, edit custom fields, sprint membership, comments, and workflow transitions. This has customizations for Red Hat jira to support personalized workflows compared to generic atlassian mcp.

- CLI: `jira-cli`
- MCP tools: `jira_list_mine`, `jira_search`, `jira_get_issue`, `jira_update_issue`, `jira_agenda`, `jira_backlog`, `jira_create_issue_link`, and others
- See [mcp/rh-jira-cli/README.md](mcp/rh-jira-cli/README.md)

### dir-worklog

CLI and MCP server for daily agenda workspace activity: repos touched on the last workday or today, changed files (respecting `.gitignore` in git repos), and your git commits. Default workspace is `GIT_PATH` (`~/git`); pass multiple workspace roots.

- CLI: `worklog activity` (previous Mon–Fri workday), `worklog today`, `worklog last-workday`
- MCP tools: `worklog_workspace_activity`, `worklog_workspace_today`, `worklog_last_workday`
- See [mcp/dir-worklog/README.md](mcp/dir-worklog/README.md)

## CLI tools

Install all commands from the tools package:

```bash
pip install -e /path/to/ai-tools/tools
```

| Command | Purpose |
|---------|---------|
| `clean-twd` | Clean IdM-CI `twd` artifacts before test re-execution |
| `pull-jenkins-artifacts` | Fetch Jenkins console + IdM-CI twd artifacts from the artifact server |
| `check-ansible` | yamllint + dual-stack ansible syntax-check / ansible-lint |

See [tools/README.md](tools/README.md).

## Cursor skills

| Skill | Purpose |
|-------|---------|
| `agenda` | Daily work agenda from worklog, git-stats, and jira-cli MCP tools |
| `analyze-jenkins-failure` | Debug IdM-CI Jenkins jobs from a build URL (console → `RD_JR_ARTIFACTS_URL` → logs + `metadata.mod.yaml` → reproduction) |
| `backlog` | Backlog tickets for estimation and sprint planning via jira-cli MCP |
| `jira-cli-mcp` | Jira issue search, updates, and transitions via the jira-cli MCP |
| `review-changes` | Clone a PR/MR, lint changed files, and review diff quality |
| `run-python-static-code-analysis` | Lint and format Python edits using project-configured tools |
| `run-sssd-tests-idmci` | IdM-CI / @TESTRUNS multihost tests (`~/git/@TESTRUNS`, `twd/metadata.yaml`, `te`); pytest-mh and in-repo pytest |
| `write-sssd-system-tests` | Author SSSD multihost system tests with sssd-test-framework / pytest-mh |

Skills live under `skills/<name>/SKILL.md`. Cursor loads them from `~/git/.cursor/skills`, which symlinks here.

## Install (MCP via uvx)

Typical Cursor `~/.cursor/mcp.json` entries install from this repo (adjust host/path as needed):

```json
{
  "mcpServers": {
    "jira-cli": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/jakub-vavra-cz/ai-tools#subdirectory=mcp/rh-jira-cli",
        "--with",
        "mcp>=1.0",
        "jira-cli-mcp"
      ]
    },
    "git-worktrees": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/jakub-vavra-cz/ai-tools#subdirectory=mcp/git-worktrees",
        "--with",
        "mcp>=1.0",
        "git-worktrees-mcp"
      ],
      "env": {
        "GIT_PATH": "~/git"
      }
    },
    "worklog": {
      "command": "uvx",
      "args": [
        "--from",
        "worklog[mcp] @ git+https://github.com/jakub-vavra-cz/ai-tools#subdirectory=mcp/dir-worklog",
        "worklog-mcp"
      ],
      "env": {
        "GIT_PATH": "~/git"
      }
    },
    "git-stats": {
      "command": "uvx",
      "args": [
        "--from",
        "git-stats[mcp] @ git+https://github.com/jakub-vavra-cz/ai-tools#subdirectory=mcp/git-stats",
        "git-stats-mcp"
      ],
      "env": {
        "GIT_PATH": "~/git"
      }
    }
  }
}
```

For local development, install editable from each package directory instead (see per-package READMEs).
