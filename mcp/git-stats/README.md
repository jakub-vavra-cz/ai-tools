# git-stats

CLI and MCP server for GitHub/GitLab PR/MR queues: review-requested, authored PRs with changes requested, and authored PRs with no reviewer.

## Install

```bash
cd git-stats
python3 -m venv .venv
.venv/bin/pip install -e '.[mcp,dev]'
```

## CLI

```bash
git-stats                          # all categories
git-stats reviews                  # agenda §2 shorthand
git-stats authored                 # both authored categories
git-stats reviews github --json    # GitHub only
git-stats reviews --all --json     # include closed/merged
git-stats done                     # today's GitHub/GitLab updates
git-stats done --date 2026-07-01 --json
git-stats --dir sssd-fork-master   # limit repo-scan fallback to one GIT_PATH child
```

Per-repo fallbacks scan top-level git directories under `GIT_PATH` and infer GitHub vs GitLab from `origin` / `upstream` remote URLs.

## MCP

Tools: `git_stats`, `git_stats_reviews`, `git_stats_done`.

### Local install

```bash
pip install -e '.[mcp]'
git-stats-mcp
```

### Cursor (`~/.cursor/mcp.json`)

#### venv (local checkout)

```json
{
  "mcpServers": {
    "git-stats": {
      "command": "/path/to/git-stats/.venv/bin/git-stats-mcp",
      "env": {
        "GIT_PATH": "/home/you/git"
      }
    }
  }
}
```

#### uvx

`uvx` installs `git-stats` and the `mcp` extra into an isolated tool env on first use. Re-run with `uvx --refresh ...` after upstream changes.

**Local checkout** — adjust the path to your clone:

```json
{
  "mcpServers": {
    "git-stats": {
      "command": "uvx",
      "args": [
        "--from",
        "/home/you/git/ai-tools/mcp/git-stats[mcp]",
        "git-stats-mcp"
      ],
      "env": {
        "GIT_PATH": "/home/you/git"
      }
    }
  }
}
```

**Git HTTPS** — package lives in the `git-stats/` subdirectory of `jvavra-test-tools` (pin `@master` or a tag as needed):

```json
{
  "mcpServers": {
    "git-stats": {
      "command": "uvx",
      "args": [
        "--from",
        "git-stats[mcp] @ git+https://github.com/jakub-vavra-cz/ai-tools@master#subdirectory=mcp/git-stats",
        "git-stats-mcp"
      ],
      "env": {
        "GIT_PATH": "/home/you/git"
      }
    }
  }
}
```

Private GitLab hosts may require credentials (`git credential`, `~/.netrc`, or a personal access token in the URL). Tilde paths work in `GIT_PATH`.

See [MCP-DESIGN.md](MCP-DESIGN.md) for full design.

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `GIT_PATH` | `~/git` | Workspace scanned for git clones (repo-scan fallback) |
| `GIT_STATS_GITHUB_LIMIT` | `20` | Max GitHub PRs per category |
| `GIT_STATS_GITLAB_LIMIT` | `30` | Max GitLab MRs per category |
| `GIT_STATS_GITLAB_HOST` | `gitlab.cee.redhat.com` | GitLab hostname for `glab api` and remote detection |
| `GIT_STATS_INCLUDE_DRAFTS` | `0` | Include GitLab drafts in `review_requested` when `1` |
| `GIT_STATS_INCLUDE_ALL` | `0` | Include closed/merged PRs/MRs when `1` (same as `--all`) |
| `GIT_STATS_DONE_MAX_PAGES` | `10` | Max event API pages per host for `done` (100 events/page) |

## Test

```bash
.venv/bin/pytest
.venv/bin/ruff check git_stats tests
```
