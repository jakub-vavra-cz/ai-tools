# git-worktrees (MCP + CLI)

Python **Model Context Protocol** server (and CLI) that automates the same flow as a local `branch_w.sh` helper: ensure your **fork** is cloned with an **upstream** remote under `GIT_PATH`, **fetch**, create a **new branch in a new worktree** from an upstream ref, then **`git push -u origin`**. Also supports **refreshing** the main clone and **cleaning up** topic worktrees once their changes are merged upstream.

Use it from Cursor (or any MCP client) so an agent can open or remove a topic branch without you running shell steps by hand.

## Requirements

- **Git** on `PATH`.
- **SSH** (or whatever your fork remotes use) configured for `git@github.com` / `git@gitlab.cee.redhat.com` as in your `fork_template` URLs.
- **Python 3.10+**.

## Install

From this directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Console entry points:

- **`git-worktrees-mcp`** — stdio MCP server
- **`git-worktrees`** — CLI (`list-repos`, `create`, `refresh`, `cleanup`)

## Cursor / MCP client

Run the server over stdio. Example configuration (adjust paths):

```json
{
  "mcpServers": {
    "git-worktrees": {
      "command": "/home/you/git/ai-tools/mcp/git-worktrees/.venv/bin/git-worktrees-mcp"
    }
  }
}
```

Equivalent using the module:

```json
"command": "/home/you/git/ai-tools/mcp/git-worktrees/.venv/bin/python",
"args": ["-m", "git_worktrees_mcp.server"]
```

Restart the MCP client after changing env vars or `repos.ini`.

## Tools (MCP)

| Tool | Purpose |
|------|--------|
| **`list_repos`** | Returns `git_path`, path to the active **`repos.ini`**, and per-repo metadata (default branch, clone directory name, worktree prefix, resolved main clone path). |
| **`create_worktree_branch`** | `repo`, `new_branch`, optional `source_branch`. Ensures the main clone exists, fetches, adds the worktree from `upstream/<source>`, pushes the new branch to `origin`. Response includes per-step git output or structured errors. |
| **`worktree_refresh`** | `repo`. Checkout default branch on the main clone, `git pull -r upstream`, force-push `origin`. |
| **`worktree_cleanup`** | `repo`, `branch`, optional `force`. Fetches, verifies the topic branch is merged into upstream (exact or cherry-equivalent), then deletes `origin/<branch>`, removes the worktree, and deletes the local branch. Stops if not merged. Warns and stops on uncommitted changes unless `force=true` (force does **not** bypass the merge check). |

**Two-argument behaviour (create):** omit `source_branch` to branch off the repo’s configured **default** upstream branch (for example `master` or `main`).

**Three-argument behaviour (create):** set `source_branch` to branch off `upstream/<source_branch>` instead.

## CLI

```bash
git-worktrees list-repos
git-worktrees create IDMCI my_feature [source_branch]
git-worktrees refresh IDMCI
git-worktrees cleanup IDMCI my_feature          # refuse if dirty or not merged
git-worktrees cleanup IDMCI my_feature --force  # allow dirty worktree; still requires merge
git-worktrees cleanup IDMCI my_feature --json
```

## Environment variables

| Variable | Meaning |
|----------|--------|
| **`GIT_PATH`** | Parent directory for the main fork clone and worktrees (default: `~/git`). |
| **`GITLAB_CEE_USER`** | Substituted into `{gitlab_cee_user}` in `fork_template` (default matches the original shell script). |
| **`GITHUB_USER`** | Substituted into `{github_user}` in `fork_template`. |
| **`GIT_WORKTREES_REPOS_INI`** | Absolute or home-relative path to an INI file that replaces the bundled `git_worktrees_mcp/repos.ini`. |

## Extending repositories (`repos.ini`)

Default definitions live in **`git_worktrees_mcp/repos.ini`** next to the package (also packaged in the wheel via `package-data`).

Each repository is one INI section whose name becomes the repo code (normalized to uppercase), for example `[SSSD]`. Required keys:

- **`upstream`** — upstream clone URL (typically `https://…`).
- **`fork_template`** — your fork URL; may include `{gitlab_cee_user}` and/or `{github_user}`.
- **`default_branch`** — used when `create_worktree_branch` is called without `source_branch`.
- **`default_loc`** — directory name under `GIT_PATH` for the long-lived fork clone (`git remote add upstream` lives here).
- **`prefix`** — prefix for worktree directory names (for example `sssd-fork-` plus the new branch name).

To customize: copy the file, edit or add sections, and point **`GIT_WORKTREES_REPOS_INI`** at your copy so upgrades to the package do not overwrite your list.

## Lint (optional)

With dev extras:

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/flake8 git_worktrees_mcp
```

Project **`flake8`** settings are in **`.flake8`** (line length 100).
