---
name: is-merged
description: >-
  Checks whether a local git branch or worktree tip is already present on
  upstream (exact ancestor, tip/branch cherry-equivalent, subject hits,
  optional patch-id). Runs the `is-merged` CLI from ai-tools. Use when the user
  asks if a branch/worktree/PR tip is merged, landed upstream, or already
  applied, or before cleaning a topic worktree.
---

# Is-merged

Decide whether a **local clone / worktree tip** is already on upstream. Prefer
the approved CLI over ad-hoc `git` one-liners.

Related: [git-worktrees MCP](../../mcp/git-worktrees/) `worktree_cleanup`
(removes a worktree only when merged).

---

## Tool

Install (once) from the ai-tools checkout:

```bash
pip install -e ~/git/ai-tools/tools
```

Run:

```bash
is-merged /path/to/repo-or-worktree
is-merged /path/to/repo --ref BRANCH --fetch
is-merged /path/to/repo --upstream upstream/master --deep --json
```

| Flag | Purpose |
|------|---------|
| `repo` | Path to clone/worktree (default `.`) |
| `--ref` | Local ref (default current branch / HEAD) |
| `--upstream` | Remote ref (default `upstream/HEAD`, else `upstream/master\|main`, …) |
| `--fetch` | `git fetch` upstream/origin first |
| `--deep` | Scan recent upstream commits for tip patch-id match |
| `--no-origin` | Skip `ls-remote` check for `origin/<branch>` |
| `--json` | Machine-readable result |

Exit: `0` merged, `1` not merged, `2` error.

---

## Workflow

1. Resolve the path the user named (`@…`, worktree dir, or cwd).
2. Run **`is-merged <path> --fetch`** (add `--deep` when tip cherry is pending
   but substance may still be upstream; add `--json` when you need fields).
3. Report from the result:

| Field | Meaning |
|-------|---------|
| `merged` / `merge_status` | Verdict: `exact`, `cherry`, or `not_merged` |
| `tip` + `tip_subject` | Commit under test |
| `upstream_ref` | Compared remote ref |
| `ancestor` | Tip is ancestor of upstream |
| `tip_cherry` | Tip alone: `equivalent` / `pending` / `failed` |
| `branch_cherry_pending` | Whole-branch `git cherry` `+` count |
| `subject_hits` | Upstream log lines matching tip subject / tickets |
| `tip_patch_id_match` | Upstream SHA with same tip patch-id (`--deep`) |
| `origin_branch_present` | Whether fork still has the branch |
| `notes` | Caveats (e.g. subject hits without confirmed patch) |

4. Be explicit when `merged` is false but `subject_hits` is non-empty: that is
   **not** proof the tip landed (related commits or differently shaped patches).

Do **not** claim merged from subject hits alone. Do **not** delete worktrees
unless the user asked; for cleanup after a confirmed merge, use git-worktrees
`worktree_cleanup` or the user's cleanup request.

---

## Examples

```bash
is-merged ~/git/sf-SSSD-8151 --fetch
is-merged ~/git/sssd-qe-fork-multiarch_mh --ref multiarch_mh --upstream upstream/main --deep --json
```
