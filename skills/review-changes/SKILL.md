---
name: review-changes
description: >-
  Clones a GitHub or GitLab PR/MR with the approved `clone-review` CLI under
  ~/git/@REVIEWS/ (path must include the literal substring reviews), computes the
  changed file set against the default branch, runs project-appropriate linters in
  read-only mode, then evaluates the diff for unclear docstrings and general code
  quality. Prefer `review-pr` for the full mechanical workflow, or
  `clone-review` / `review-diff` / `check-python` / `check-ansible` /
  `cleanup-review` individually. Use when reviewing pull requests or merge
  requests, when the user mentions review-changes, gh, glab, review-pr,
  clone-review, review-diff, check-python, cleanup-review, or wants lint plus a
  concise quality pass on remote branch changes without an existing checkout.
---

# Review-changes (PR/MR clone and linters)

## When this applies

User wants to **review** a PR/MR or branch they do not already have checked out, and to **run linters** on only what changed. This skill is **read-only** for the remote code (report results; do not reformat unless the user asks).

**Never post comments, reviews, approvals, or requests-for-changes on the PR/MR autonomously.** Report findings only in the chat. Leave GitHub/GitLab review actions to the user unless they explicitly ask you to submit a review or comment.

If you **edit** Python in a workspace after review, use the project skill [run-python-static-analysis](../run-python-static-analysis/SKILL.md) for lint and format rules on your own changes.

All commands below come from [ai-tools/tools](../../tools/README.md). Install
once with `pip install -e ~/git/ai-tools/tools`. **Never use raw `cd <clone> && git diff …` or ad-hoc `gh` / `glab` / `git` sequences** — the ai-tools CLIs handle clone management, merge-base computation, diff, lint discovery, and cleanup in a safe, consistent way.

---

## 1. Clone + lint with `review-pr` (one-shot, preferred)

A single command clones the PR/MR under `~/git/@REVIEWS`, discovers changed
files, and runs project-appropriate linters (Python via `check-python`, Ansible
via `check-ansible`):

```bash
review-pr https://github.com/OWNER/REPO/pull/N --json -q
review-pr https://gitlab.cee.redhat.com/GROUP/REPO/-/merge_requests/N --json -q
review-pr identity-management/idm-ci!2726 --host gitlab.cee.redhat.com --json -q
```

Always pass **`--json`** (machine-readable) and **`-q`** (omit verbose file
lists). The JSON result contains everything needed for the rest of the review:

| JSON field | Use |
|------------|-----|
| `checkout.clone_path` | Working tree for reading full files |
| `checkout.base_ref` / `checkout.base_sha` | Merge-base vs target branch |
| `checkout.head_sha` | PR/MR tip |
| `checkout.changed_files` | Lint scope and review scope |
| `diff_stat` | Short summary for the report |
| `lint_ok` | Overall lint pass/fail |
| `python.ok` / `python.results[]` | Per-tool lint details |

| Flag | Purpose |
|------|---------|
| `--no-refresh` | Reuse existing clone; only recompute diff and lint |
| `--skip-lint` | Clone and list changes only (no linter run) |
| `--include-diff` | Embed full patch in output (usually prefer `review-diff` instead) |
| `--cleanup` | Remove review clone after the run |
| `--root` / `--name` / `--platform` / `--host` | Override clone location or platform detection |

Exit: `0` linters pass, `1` lint failure, `2` error.

### Step-by-step alternative (when you need individual control)

Use the component commands separately only when the one-shot flow is not
appropriate (e.g. re-running lint after the author pushes a fix, or when you
need a different lint scope):

| Command | Purpose |
|---------|---------|
| `clone-review REFERENCE --json` | Clone / refresh checkout; list changed files |
| `check-python path.py --root <clone_path> --json` | Lint specific Python files |
| `check-ansible path.yml --json` | Lint specific Ansible files |
| `review-diff REFERENCE` | Print the patch (see section 2) |
| `cleanup-review REFERENCE` | Remove the clone (see section 4) |

---

## 2. Read the diff with `review-diff`

After `review-pr` (or `clone-review`), use **`review-diff`** to get the patch.
Do **not** `cd` into the clone and run `git diff` manually — `review-diff`
handles merge-base detection, clone lookup, and API fallback automatically:

```bash
review-diff REFERENCE                # full patch to stdout
review-diff REFERENCE --name-only    # changed file paths only
review-diff REFERENCE --stat         # diffstat summary
review-diff REFERENCE --stat --json  # machine-readable diffstat
review-diff REFERENCE -o /tmp/pr.patch  # write to file
```

`REFERENCE` is the same PR/MR URL or shorthand used in step 1.

When the clone already exists (from `review-pr` / `clone-review`), `review-diff`
uses the local checkout. Otherwise it falls back to `gh pr diff` / `glab mr diff`.

For reading full changed files (not just the diff), use the **Read** tool on
paths under `clone_path` from the `review-pr` JSON.

---

## 3. Evaluate the change (after linters)

Read the patch via **`review-diff REFERENCE`** and full changed files from
`clone_path` as needed. Focus on the PR's intent and regressions, not style
(linters already covered that).

**Docstrings and comments**

- Public APIs, modules, classes, and non-obvious functions: docstrings should state purpose, non-obvious parameters/returns/raises/side effects, and units where relevant.
- For **added or changed** docstrings, compare nearby and same-layer symbols in the file or package: tone, section order (e.g. Args/Returns/Raises), imperative vs declarative voice, blank-line layout, reStructuredText/Google/NumPy/Sphinx style, and cross-reference patterns should **match existing conventions** in that codebase—not introduce a one-off format.
- Flag **missing** docstrings where the project or language norms expect them; **vague** or **stale** text (wrong behavior, wrong types, copy-paste); **misleading** names vs behavior.
- Inline comments: only where they add "why"; remove or fix comments that contradict the code.

**General code quality**

- **Correctness:** edge cases, error paths, resource cleanup, concurrency, security-sensitive use of input.
- **Structure:** clear naming, reasonable function size, duplication, layering leaks.
- **Tests:** if behavior changed, tests or types should reflect it; note gaps.
- **Compatibility:** API/ABI/config migrations if the diff touches interfaces.

Classify findings (e.g. must-fix / should-fix / nit) and tie each to a file or hunk. Prefer a short list of high-signal items over an exhaustive nitpick.

---

## 4. Report and cleanup

Summarize: `clone_path`, `base_ref` / SHAs, changed files, **linter** pass/fail (from `review-pr` JSON), then **quality/docstring** findings from section 3 (or state none worth noting).

**Cleanup** when finished:

```bash
cleanup-review REFERENCE       # remove the specific clone
cleanup-review --all           # remove all review clones
cleanup-review REFERENCE -n    # dry-run
```

---

## Manual fallback (only if ai-tools CLIs are unavailable)

- Prefer **`gh`** for GitHub; **`glab`** for GitLab.
- Clone under `~/git/@REVIEWS/` with a distinct name (`REPO-prN` / `REPO-mrN`).
- Checkout: `gh pr checkout N` or `glab mr checkout IID`.
- Changed files:

```bash
git fetch origin main 2>/dev/null || git fetch origin master 2>/dev/null || true
BASE=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD origin/master 2>/dev/null || git merge-base HEAD origin/devel 2>/dev/null)
git diff --name-only "$BASE"..HEAD
git diff --stat "$BASE"..HEAD
```

- Lint Python: `flake8`, `black --check`, `ruff check` per [run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md).
- Lint Ansible: per [writing-ansible](../writing-ansible/SKILL.md).
