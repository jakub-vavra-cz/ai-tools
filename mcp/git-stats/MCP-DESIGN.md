# git-stats — CLI and MCP design

Design for a **`git-stats` CLI** and stdio **MCP server** that implement **agenda §2 — Pull requests awaiting my review** ([agenda skill](../../.cursor/skills/agenda/SKILL.md)) plus **authored PR/MR queues** (changes requested, no reviewer). Replaces ad-hoc `gh search prs` / `glab api` shell steps with one structured command or tool call.

**Status:** implemented (see `git_stats/`, `README.md`).

**Related:** [worklog](../dir-worklog/) (CLI + MCP, agenda §1). git-stats follows worklog for **CLI + MCP** dual entrypoints and human/JSON output; uses **`GIT_PATH`** top-level git clones for per-repo `gh`/`glab` fallbacks.

---

## Goals

Three **categories** (each queried on GitHub and GitLab):

| Category id | Meaning |
|-------------|---------|
| `review_requested` | Open PR/MR where **I am a requested reviewer** (agenda §2). |
| `authored_changes_requested` | Open PR/MR where **I am the author** and a reviewer has **requested changes**. |
| `authored_no_reviewer` | Open PR/MR where **I am the author** and **no reviewer is assigned**. |

Cross-cutting:

- Fetch **GitHub and GitLab in parallel** per invocation; fetch all requested categories per host in the same host worker (one `gh`/`glab` auth context).
- **Prefer non-draft** items for `review_requested`; surface GitLab drafts separately when that category’s ready queue is empty (agenda presentation rule).
- Return structured JSON for agents and a short human report for terminal use.
- **Degrade gracefully:** auth or network failure on one host must not block the other; record per-host errors in the response.

Non-goals for v1: assignee-only (non-author, non-reviewer), Jira integration (agenda §3 stays on `jira-cli` MCP), comment threads, approve/request-changes actions, team-review-requested-only queues (GitHub team requests without individual reviewers count as “reviewer set”).

---

## Package

| Field | Value |
|-------|-------|
| Package name | `git-stats` |
| Python module | `git_stats` |
| Console scripts | `git-stats` → `git_stats.cli:main`; `git-stats-mcp` → `git_stats.server:main` |
| Shared core | `git_stats.service.queue_fetch()` — used by CLI and MCP |
| MCP transport | stdio (`FastMCP`, same stack as [git-worktrees-mcp](../git-worktrees/)) |
| Cursor MCP server id (proposed) | `user-git-stats` |
| MCP server instructions | PR/MR queues on GitHub and Red Hat GitLab. Fetches hosts in parallel. Per-repo fallbacks scan git clones under `GIT_PATH`. |
| `requires-python` | `>=3.10` (same as git-worktrees) |

### Environment

Aligned with worklog / git-worktrees for `GIT_PATH` default (`~/git`).

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GIT_PATH` | No | `~/git` | Top-level workspace; repo-scan fallback walks immediate child directories containing `.git` |
| `GIT_STATS_GITHUB_LIMIT` | No | `20` | Default `--github-limit` / `github_limit` (per category) |
| `GIT_STATS_GITLAB_LIMIT` | No | `30` | Default `--gitlab-limit` / `gitlab_limit` (per category) |
| `GIT_STATS_GITLAB_HOST` | No | `gitlab.cee.redhat.com` | `glab --hostname` and GitLab remote URL detection |
| `GITHUB_TOKEN` | No | — | REST fallback when `gh` is missing or fails (also honors `GH_TOKEN`) |
| `GIT_STATS_INCLUDE_DRAFTS` | No | `0` | When `1`, include GitLab drafts/WIP in `review_requested` primary lists |
| `GIT_STATS_CATEGORIES` | No | all three | Comma-separated default for `--categories` / `categories` |

`glab` and `gh` auth are read from each tool’s normal config (`~/.config/glab-cli/`, `gh auth status`). No tokens are required when both CLIs are authenticated.

### Workspace clone discovery

Per-repo **`glab` / `gh` fallbacks** (when cross-project API fails) run inside **git directories under `GIT_PATH`**, not via `repos.ini`.

- **Scan:** each top-level child of `GIT_PATH` where `.git` exists.
- **Host selection:** `git remote get-url origin` (then `upstream`); `github.com` → GitHub, `GIT_STATS_GITLAB_HOST` → GitLab.
- **Optional filter:** `--dir NAME` / MCP `dirs: ["sssd-fork-master"]` limits fallback scan to named directories.

### Package layout (implementation target)

```
git-stats/
  MCP-DESIGN.md          # this file
  pyproject.toml
  README.md
  git_stats/
    __init__.py
    cli.py               # argparse entrypoint
    server.py            # FastMCP tool registration (git-worktrees: server.py)
    config.py            # git_base_path(), iter_workspace_clones(), remote detection
    service.py           # queue_fetch() orchestration + parallel fetch
    categories.py        # category ids, defaults, validation
    github.py            # gh subprocess + optional REST fallback (per category)
    gitlab.py            # glab api + per-repo fallback (per category)
    models.py            # typed dicts / dataclasses for PR/MR rows
    output.py            # human text + JSON serializers
    cli_util.py          # subprocess helpers + CliResult dataclass (git-worktrees: GitResult)
  tests/
    fixtures/
```

No `tools/*.json` descriptors — tools are registered via `@mcp.tool()` only (same as git-worktrees). Optional markdown in README listing tool names and args.

Dependencies:

- **CLI:** stdlib + subprocess (`gh`, `glab`).
- **MCP extra:** `mcp>=1.0`.

### `pyproject.toml` scripts

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "git-stats"
version = "0.1.0"
description = "CLI and MCP: GitHub/GitLab PR/MR review and authored queues"
readme = "README.md"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
mcp = ["mcp>=1.0"]
repos = ["ruff>=0.1.0", "pytest>=7.0", "flake8>=6.0"]

[project.scripts]
git-stats = "git_stats.cli:main"
git-stats-mcp = "git_stats.server:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["git_stats*"]

[tool.ruff]
line-length = 100
target-version = "py310"
```

Install:

```bash
cd git-stats && python3 -m venv .venv
.venv/bin/pip install -e '.[mcp,dev]'
```

---

## CLI

Primary user-facing interface. MCP tools call the same `queue_fetch()` function with equivalent parameters.

### Commands

| Command | Categories |
|---------|------------|
| `git-stats` | all three (default) |
| `git-stats reviews` | `review_requested` only (agenda §2 shorthand) |
| `git-stats authored` | `authored_changes_requested` + `authored_no_reviewer` |
| `git-stats authored changes-requested` | `authored_changes_requested` only |
| `git-stats authored no-reviewer` | `authored_no_reviewer` only |

Bare `git-stats` with no subcommand runs **all categories** (not help-only).

Optional host filter on any command: trailing `github` or `gitlab` positional (same as before).

### `git-stats` / `git-stats reviews` / `git-stats authored …`

```bash
git-stats [reviews|authored [changes-requested|no-reviewer]] [github|gitlab] [options]
```

When `github` or `gitlab` is given, fetch only that host; otherwise fetch both in parallel.

#### Options

| Flag | Env default | Default | Description |
|------|-------------|---------|-------------|
| `--categories CAT[,CAT…]` | `GIT_STATS_CATEGORIES` | all three | Explicit category list (overrides subcommand preset) |
| `--github-limit N` | `GIT_STATS_GITHUB_LIMIT` | `20` | Max GitHub PRs **per category** |
| `--gitlab-limit N` | `GIT_STATS_GITLAB_LIMIT` | `30` | Max GitLab MRs **per category** |
| `--include-drafts` | `GIT_STATS_INCLUDE_DRAFTS` | off | Include GitLab drafts/WIP in `review_requested` lists |
| `--gitlab-host HOST` | `GIT_STATS_GITLAB_HOST` | `gitlab.cee.redhat.com` | `glab --hostname` for cross-project API |
| `--dir NAME` | — | all under `GIT_PATH` | Limit per-repo fallback to a top-level directory name (repeatable) |
| `--json` | — | off | Emit the MCP response dict on stdout |
| `-q` / `--quiet` | — | off | Errors only on stderr (with `--json`, stdout stays clean JSON) |

`--categories` values: `review_requested`, `authored_changes_requested`, `authored_no_reviewer`. Subcommand presets apply when `--categories` is omitted.

CLI flags override environment defaults.

#### Human output (default)

When `--json` is not set, print a short report to stdout:

```
Reviews waiting on me
  GitHub
    owner/repo#42  Fix regression in sssd cache  https://github.com/...
    (none)
  GitLab
    group/project!17  CI: bump container image  https://gitlab.cee.redhat.com/...

My PRs — changes requested
  GitHub
    myorg/tools#9  Address review comments  https://github.com/...
  GitLab
    (none)

My PRs — no reviewer set
  GitHub
    myorg/tools#12  Draft cleanup  https://github.com/...
  GitLab
    idm/lib!3  Add helper module  https://...
```

- Section headers: human labels per category (see [Category labels](#category-labels)), then `GitHub` / `GitLab` sub-headers.
- Each line: `ref`, title, URL (tab- or ` — `-separated).
- When a host returned zero items for a category: print `(none)` under that sub-header.
- For `review_requested` only: when GitLab has drafts and `--include-drafts` is off, append `GitLab (drafts only)` under that category.
- Per-host failures go to stderr, one line: `GitHub: gh not authenticated` (stdout still lists the other host / other categories).

#### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (at least one host succeeded, or both returned empty queues) |
| `2` | Usage error or invalid flags |
| `1` | Both hosts failed (auth/network/tool missing) |
| `3` | Partial failure: one host failed, one succeeded (optional; alternatively always `0` when any host succeeds — **recommend `0` when any host succeeds**, `1` only when all requested hosts failed) |

---

## MCP tools

MCP mirrors the CLI: `git_stats` ≡ `git-stats`; `git_stats_reviews` ≡ `git-stats reviews` (alias).

Registered in `git_stats/server.py` with `@mcp.tool()` and `_require_fastmcp()` (same import guard as [git-worktrees `server.py`](../git-worktrees/git_worktrees_mcp/server.py)). No checked-in `tools/*.json` descriptors.

| Tool | Purpose |
|------|---------|
| **`git_stats`** | All requested categories on GitHub and/or GitLab |
| **`git_stats_reviews`** | Alias: `categories=["review_requested"]` only (agenda §2) |

`FastMCP` constructor:

```python
mcp = FastMCP(
    "git-stats",
    instructions=(
        "PR/MR queues on GitHub and Red Hat GitLab. "
        "Categories: review_requested, authored_changes_requested, authored_no_reviewer. "
        "Env: GIT_PATH, GIT_STATS_GITLAB_HOST; per-repo fallbacks scan git clones under GIT_PATH."
    ),
)
mcp.run(transport="stdio")
```

#### Parameters (`git_stats`)

| Name | Type | Default | CLI equivalent |
|------|------|---------|----------------|
| `categories` | `list[string]` | all three | subcommand preset or `--categories` |
| `hosts` | `list[string]` | `["github", "gitlab"]` | optional `github` / `gitlab` positional |
| `github_limit` | `integer` | `20` | `--github-limit` (per category) |
| `gitlab_limit` | `integer` | `30` | `--gitlab-limit` (per category) |
| `include_drafts` | `boolean` | `false` | `--include-drafts` |
| `gitlab_host` | `string` | `gitlab.cee.redhat.com` | `--gitlab-host` |
| `dirs` | `list[string]` | `[]` | repeatable `--dir` (empty → all clones under `GIT_PATH`) |

`categories` values: `review_requested`, `authored_changes_requested`, `authored_no_reviewer` (case-insensitive). Unknown values → `{"ok": false, "error": "..."}` (same error shape as [git-worktrees `create_worktree_branch`](../git-worktrees/git_worktrees_mcp/server.py)).

`hosts` values: `"github"`, `"gitlab"` (case-insensitive).

`dirs` values: top-level directory names under `GIT_PATH` (e.g. `sssd-fork-master`). Empty list → all git clones found in the workspace.

Tool returns the [response schema](#response-schema) dict directly.

#### Response schema

```json
{
  "ok": true,
  "git_path": "/home/user/git",
  "categories": [
    "review_requested",
    "authored_changes_requested",
    "authored_no_reviewer"
  ],
  "github": {
    "ok": true,
    "source": "gh",
    "username": "jvavra",
    "review_requested": {
      "count": 2,
      "items": [
        {
          "ref": "SSSD/sssd#7421",
          "title": "Fix regression in cache invalidation",
          "url": "https://github.com/SSSD/sssd/pull/7421",
          "updated_at": "2026-06-30T14:22:11Z",
          "draft": false,
          "repository": "SSSD/sssd",
          "number": 7421
        }
      ]
    },
    "authored_changes_requested": {
      "count": 1,
      "items": [
        {
          "ref": "jvavra/tools#9",
          "title": "Address review comments",
          "url": "https://github.com/jvavra/tools/pull/9",
          "updated_at": "2026-06-28T10:00:00Z",
          "draft": false,
          "repository": "jvavra/tools",
          "number": 9
        }
      ]
    },
    "authored_no_reviewer": {
      "count": 0,
      "items": []
    },
    "error": null
  },
  "gitlab": {
    "ok": true,
    "source": "api",
    "username": "jvavra",
    "review_requested": {
      "count": 1,
      "items": [
        {
          "ref": "idm/sssd!4821",
          "title": "CI: bump container image",
          "url": "https://gitlab.cee.redhat.com/idm/sssd/-/merge_requests/4821",
          "updated_at": "2026-06-29T09:15:00Z",
          "draft": false,
          "work_in_progress": false,
          "project": "idm/sssd",
          "iid": 4821
        }
      ],
      "drafts": []
    },
    "authored_changes_requested": {
      "count": 0,
      "items": []
    },
    "authored_no_reviewer": {
      "count": 1,
      "items": [
        {
          "ref": "idm/lib!3",
          "title": "Add helper module",
          "url": "https://gitlab.cee.redhat.com/idm/lib/-/merge_requests/3",
          "updated_at": "2026-06-27T08:00:00Z",
          "draft": false,
          "work_in_progress": false,
          "project": "idm/lib",
          "iid": 3
        }
      ]
    },
    "error": null
  },
  "errors": []
}
```

Omitted category keys: when a category was not requested, omit its key under each host (do not return empty stubs).

| Field | Meaning |
|-------|---------|
| `ok` | `true` when `queue_fetch` completed (per-host failures may still be present); `false` for fatal argument/config errors. |
| `git_path` | Resolved `GIT_PATH`. |
| `categories` | Resolved category list for this response. |
| `github.ok` / `gitlab.ok` | `true` when the host worker completed (empty queues still ok). |
| `github.source` / `gitlab.source` | `gh`, `api`, or `repo-scan` (GitLab only for last). |
| `*.username` | Authenticated login on that host (`gh api user`, `glab api user`). |
| `*.<category>.items` | Matching entries, sorted by `updated_at` desc. |
| `gitlab.review_requested.drafts` | Draft/WIP MRs excluded from `items` unless `include_drafts`. |
| `*.items[].ref` | Short id: `owner/repo#N` or `group/project!N`. |
| `errors` | Top-level non-fatal issues, e.g. `[{"host": "github", "category": "authored_no_reviewer", "message": "..."}]`. |

#### Category labels

| Category id | Human report heading |
|-------------|----------------------|
| `review_requested` | Reviews waiting on me |
| `authored_changes_requested` | My PRs — changes requested |
| `authored_no_reviewer` | My PRs — no reviewer set |

When every requested host fails, still return the dict with `ok: true` at top level if the invocation itself succeeded; per-host `ok: false` and `error` strings. MCP must not throw unless arguments are invalid.

Fatal argument errors: `{"ok": false, "error": "invalid categories: foo"}`.

---

## Core API

Both CLI and MCP call:

```python
def queue_fetch(
    *,
    categories: list[str] | None = None,
    hosts: list[str] | None = None,
    github_limit: int = 20,
    gitlab_limit: int = 30,
    include_drafts: bool = False,
    gitlab_host: str = "gitlab.cee.redhat.com",
    dirs: list[str] | None = None,
) -> dict[str, Any]: ...
```

- `categories is None` or `[]` → all three category ids.
- `hosts is None` or `[]` → `["github", "gitlab"]`.
- `dirs is None` or `[]` → scan all git clones under `GIT_PATH`.
- **Clone paths** from `iter_workspace_clones(dirs=…)`.
- One **host worker** per forge runs all requested categories sequentially inside the thread (shared username resolution).
- GitHub and GitLab workers run concurrently (`concurrent.futures.ThreadPoolExecutor`, max 2 workers).
- Top-level `ok: true` on success; include `git_path` in every response.
- Return value is identical for `git-stats --json` and `git_stats`.

`review_queue = queue_fetch` alias with `categories=["review_requested"]` for internal/tests backward compat.

---

## Algorithms

Per-category queries below. Each host module exposes `fetch_category(category, *, limit, username, …) -> CategoryResult`.

### GitHub — `review_requested`

Equivalent to agenda skill:

```bash
gh search prs --review-requested=@me --state=open --limit="${LIMIT}" \
  --json number,title,url,updatedAt,isDraft,repository
```

**Sort:** `updated_at` descending.

**Drafts:** set `draft` from `isDraft`; include in `items` (rare for review-requested).

#### GitHub fallbacks (`review_requested`, in order)

1. **`gh search prs`** (primary).
2. **`gh api search/issues`** with `q=is:pr is:open review-requested:@me`.
3. **REST** search with `GITHUB_TOKEN` / `GH_TOKEN` when `gh` is unavailable.
4. On failure: record error on host; `items = []` for that category.

### GitHub — `authored_changes_requested`

```bash
gh search prs --author=@me --state=open --review=changes_requested --limit="${LIMIT}" \
  --json number,title,url,updatedAt,isDraft,repository
```

GitHub search qualifier: `author:@me is:open is:pr review:changes_requested`.

**Sort:** `updated_at` descending.

**Fallbacks:** same pattern as `review_requested` with `q=is:pr is:open author:@me review:changes_requested`.

### GitHub — `authored_no_reviewer`

GitHub issue search has **no** “no reviewer assigned” qualifier. Two-step fetch:

**Step 1 — candidate pool** (over-fetch, then filter):

```bash
gh search prs --author=@me --state=open --limit="${POOL}" \
  --json number,title,url,updatedAt,isDraft,repository,reviewRequests
```

Use `POOL = min(github_limit * 3, 100)` to allow headroom after filtering.

**Step 2 — client filter:** keep PRs where `reviewRequests` is empty **or** every entry is not a pending user/team request (no open review request). Exclude entries that only have completed reviews.

If `reviewRequests` is not available from search JSON, **fallback:** GraphQL search:

```graphql
search(query: "author:@me is:open is:pr", type: ISSUE, first: $n) {
  nodes {
    ... on PullRequest {
      number title url updatedAt isDraft
      repository { nameWithOwner }
      reviewRequests(first: 1) { totalCount }
    }
  }
}
```

Keep nodes with `reviewRequests.totalCount == 0`. Cap at `github_limit`.

**Definition (v1):** “no reviewer set” = no individual or team review request is currently pending on the PR. Team-only review requests count as reviewer set.

Do **not** call the Cursor `user-github` MCP from this tool (circular for agents).

### GitLab — shared setup

**Resolve username** once per host worker:

```bash
glab api user --hostname "${GITLAB_HOST}"
```

On failure, skip API paths and use **GIT_PATH clone fallbacks** where clones exist.

### Per-repo fallback (GitHub and GitLab)

When cross-project `gh search` / `glab api` fails (auth, network, 403), scan **top-level git directories under `GIT_PATH`**:

1. `clones = iter_workspace_clones(dirs=…)` in `git_stats.config`.
2. For each `(name, host, path)`:
   - **GitLab** (`host == "gitlab"`): `glab mr list …` with `cwd=path`.
   - **GitHub** (`host == "github"`): `gh pr list …` with `cwd=path`.
3. Merge results across clones; dedupe by `url` / `web_url`; cap per category after sort.
4. Set host `source: "repo-scan"` when any category used this path.

Category-specific per-repo commands (mirror cross-project filters):

| Category | GitLab (`glab mr list`) | GitHub (`gh pr list`) |
|----------|-------------------------|------------------------|
| `review_requested` | `--reviewer=@me --not-draft` | `--review-requested @me` |
| `authored_changes_requested` | `--author=@me` + filter `detailed_merge_status == requested_changes` | `--author @me` + JSON filter `reviewDecision == CHANGES_REQUESTED` or search already scoped |
| `authored_no_reviewer` | `--author=@me` + empty `reviewers` | `--author @me` + empty `reviewRequests` |

Use `CliResult` dataclass (`ok`, `command`, `cwd`, `stdout`, `stderr`, `returncode`) matching [git-worktrees `operations.py`](../git-worktrees/git_worktrees_mcp/operations.py). JSON flag detection: try `--json` then `--output json` per installed CLI version.

v1 scans only top-level dirs under `GIT_PATH`, not nested clones or `{prefix}*` worktrees.

### GitLab — `review_requested`

```bash
glab api "merge_requests?scope=all&state=opened&reviewer_username=${USERNAME}&per_page=${LIMIT}" \
  --hostname "${GITLAB_HOST}"
```

**Draft partition** (this category only): non-draft → `items`, draft/WIP → `drafts` unless `include_drafts`.

### GitLab — `authored_changes_requested`

```bash
glab api "merge_requests?scope=all&state=opened&author_username=${USERNAME}&per_page=${POOL}" \
  --hostname "${GITLAB_HOST}"
```

**Client filter:** `detailed_merge_status == "requested_changes"` (GitLab documents this value when a reviewer has requested changes).

`POOL` as for GitHub over-fetch; cap filtered results at `gitlab_limit`.

### GitLab — `authored_no_reviewer`

GitLab REST supports this directly:

```bash
glab api "merge_requests?scope=all&state=opened&author_username=${USERNAME}&reviewer_username=None&per_page=${LIMIT}" \
  --hostname "${GITLAB_HOST}"
```

`reviewer_username=None` is the literal string `None` in the API (returns MRs with **no reviewers** assigned).

### GitHub — per-repo fallback

Same [per-repo fallback](#per-repo-fallback-github-and-gitlab) table when `gh search` / REST is unavailable. Cross-project search remains primary when `gh` auth works.

### GitLab — field mapping (all categories)

| API field | Output |
|-----------|--------|
| `references.full` | `ref` |
| `title` | `title` |
| `web_url` | `url` |
| `updated_at` | `updated_at` |
| `project.path_with_namespace` | `project` |
| `iid` | `iid` |
| `draft` / `work_in_progress` | same |

**Sort:** `updated_at` descending per category.

### Parallel orchestration (`service.queue_fetch`)

```
                    categories=[…]
                           │
         ┌─────────────────┴─────────────────┐
         ▼                                   ▼
┌─────────────────────┐           ┌─────────────────────┐
│ github worker       │           │ gitlab worker       │
│  for cat in cats:   │           │  resolve username   │
│    fetch_category   │           │  for cat in cats:   │
└──────────┬──────────┘           │    fetch_category   │
           │                      └──────────┬──────────┘
           └──────────────┬───────────────────┘
                          ▼
                 merge into response
                 attach category labels
                 append errors[]
```

Timeout per subprocess: **30s** default. On timeout, set host `ok=false` or per-category error in `errors[]`.

---

## Cursor registration

Same layout as [git-worktrees README](../git-worktrees/README.md):

```json
{
  "mcpServers": {
    "git-stats": {
      "command": "/home/you/git/jvavra-test-tools/git-stats/.venv/bin/git-stats-mcp",
      "env": {
        "GIT_PATH": "/home/you/git"
      }
    }
  }
}
```

Equivalent module invocation:

```json
"command": "/home/you/git/jvavra-test-tools/git-stats/.venv/bin/python",
"args": ["-m", "git_stats.server"]
```

Restart the MCP client after changing env vars.

CLI (no MCP): `git-stats` or `git-stats reviews --json`

Invoke from agents: `call_mcp_tool` with `server: "user-git-stats"`, `toolName: "git_stats"`, `arguments: {}` (all categories) or `{"categories": ["review_requested"]}` for agenda §2 only.

---

## Agenda skill integration

Update [agenda/SKILL.md](../../.cursor/skills/agenda/SKILL.md) §2 to prefer git-stats when available:

1. **Reviews waiting on me:** `git-stats reviews --json` or `git_stats_reviews` / `git_stats` with `categories: ["review_requested"]` (parallel with worklog §1 and Jira §3).
2. **Optional authored sections** (when building a fuller daily agenda): use full `git-stats --json` or `git_stats` with all categories; map:
   - `github|gitlab.review_requested.items[]` → **Reviews waiting on me**
   - `*.authored_changes_requested.items[]` → **My PRs — changes requested**
   - `*.authored_no_reviewer.items[]` → **My PRs — no reviewer set**
3. Per line: `[ref](url) — title`; GitLab `review_requested` drafts rule unchanged.
4. If a host `ok` is false, one-line error (do not omit the section).
5. Keep shell fallbacks (`gh search prs`, `glab api …`) when CLI/MCP is unavailable.

Suggested report template addition:

```markdown
## My PRs — changes requested
### GitHub
- [owner/repo#N](url) — title
### GitLab
- [group/project!N](url) — title

## My PRs — no reviewer set
### GitHub
- …
### GitLab
- …
```

Checklist:

```
- [ ] git_stats fetched (or gh/glab shell fallback)
```

---

## Testing notes

- **Unit:** `iter_workspace_clones()` and `--dir` / `dirs` filter; remote host detection from `origin`.
- **Unit:** GitHub `authored_no_reviewer` filter — empty `reviewRequests`, team-only requests, completed reviews.
- **Unit:** GitLab `authored_changes_requested` filter on `detailed_merge_status`.
- **Unit:** GitLab `authored_no_reviewer` via `reviewer_username=None` query string.
- **Unit:** draft/WIP partition for `review_requested` only; `include_drafts` true/false.
- **Unit:** `ref` formatting; merge/dedupe repo-scan results by `web_url`.
- **Unit:** category validation and subcommand → `categories` resolution.
- **Integration (mocked subprocess):** partial host failure; per-category error recording.
- **Integration:** parallel host workers with multiple categories.
- **Fixture:** empty arrays → `count: 0`, host `ok: true`.

Use recorded JSON under `tests/fixtures/`; no live network in CI.

### Lint (optional)

With dev extras (same as git-worktrees):

```bash
.venv/bin/pip install -e '.[mcp,repos,dev]'
.venv/bin/ruff check git_stats
.venv/bin/flake8 git_stats
```

---

## Open questions

1. **`glab` / `gh` JSON flags:** `--json` vs `--output json` varies by version; try both in `cli_util.py`.
2. **GitHub Enterprise:** v1 targets github.com via `gh`; optional `GITHUB_HOST` later for GHES.
3. **Pagination:** per-category caps may need `page=` loops when limit > default `per_page`.
4. **Worktree scan:** defer nested clones and worktree directories; top-level `GIT_PATH` children only for v1. tune `POOL` multiplier vs GraphQL-only path if search JSON lacks `reviewRequests`.
7. **Category overlap:** authored PR with changes requested appears only under `authored_changes_requested`, not `authored_no_reviewer`.
8. **Draft authored PRs:** include in `authored_*` when open and matching filters; draft side-channel only for `review_requested`.
