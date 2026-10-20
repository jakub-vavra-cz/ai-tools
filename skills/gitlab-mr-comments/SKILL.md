---
name: gitlab-mr-comments
description: >-
  Pulls GitLab merge-request review comments via the `gitlab-mr-comments` CLI
  (glab under the hood) and prints a numbered summary with file:line locations.
  Use when the user pastes a GitLab MR URL / group/proj!N and asks about
  comments, review feedback, DiffNotes, or what reviewers said — run the CLI
  automatically; do not invent ad-hoc glab/api one-liners.
---

# GitLab MR comments

Fetch MR overview + review notes with the approved **`gitlab-mr-comments`** CLI
from ai-tools. Prefer this over raw `glab mr view --comments` or
`glab api …/notes` scraping.

## Hostnames (`~/git/ai-tools.env`)

Resolve `${GITLAB_HOST}` from `~/git/ai-tools.env` (see
[ai-tools README](../../README.md#internal-hostnames-gitai-toolsenvironment)).
Do not invent or hardcode internal hostnames in commands or tracked files.

---

## Tool

Install (once):

```bash
pip install -e ~/git/ai-tools/tools
```

Requires `glab` on `PATH` and auth for the GitLab host (`glab auth status`).

```bash
gitlab-mr-comments "https://${GITLAB_HOST}/group/repo/-/merge_requests/183"
gitlab-mr-comments 'group/repo!183' --host "$GITLAB_HOST"
gitlab-mr-comments URL --json
gitlab-mr-comments URL --include-system
gitlab-mr-comments URL --no-description
```

| Flag | Purpose |
|------|---------|
| `REFERENCE` | MR URL or `group/proj!N` |
| `--host` | GitLab hostname for shorthand (`$GITLAB_HOST` / `ai-tools.env`) |
| `--include-system` | Keep system notes (review requested, mentioned in, …) |
| `--no-description` | Skip MR description in text output |
| `--json` | Machine-readable report |

Exit: `0` ok, `2` error (missing glab, bad ref, API failure).

---

## Workflow

1. When the user asks about MR comments / review feedback and gives a GitLab MR
   URL or `group/proj!N`, run **`gitlab-mr-comments <ref>`** immediately
   (for shorthand, `--host` defaults from `$GITLAB_HOST`; use `--json` when you
   need structured fields).
2. Summarize the numbered list for the user: author, `@path:line`, body, and
   unresolved DiffNotes when present.
3. Do **not** re-implement fetching with custom `glab api` + Python in the shell
   unless the CLI is unavailable and the user asks for a workaround.
4. Do **not** paste internal hostnames into skills, READMEs, or commit messages;
   use `${GITLAB_HOST}` or `gitlab.example.com` in tracked docs.

Default output omits system notes and includes the MR description.

---

## Examples

```bash
gitlab-mr-comments \
  "https://${GITLAB_HOST}/group/repo/-/merge_requests/183"
```

Text shape:

```text
# MR !183 — feat: …
state: opened | author: alice | reviewers: bob
url: https://gitlab.example.com/group/repo/-/merge_requests/183

## Description
…

## Comments (3) (1 system notes omitted)

1. [bob] @pipelines/foo.groovy:35 (unresolved)
   Should this fail the run?
…
```
