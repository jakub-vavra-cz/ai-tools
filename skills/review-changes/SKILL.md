---
name: review-changes
description: >-
  Clones a GitHub or GitLab PR/MR with gh or glab under ~/git/@REVIEWS/ (path must
  include the literal substring reviews), computes the changed file set against the
  default branch, runs project-appropriate linters in read-only mode, then evaluates
  the diff for unclear docstrings and general code quality. Use when reviewing pull
  requests or merge requests, when the user mentions review-changes, gh, glab, or wants
  lint plus a concise quality pass on remote branch changes without an existing checkout.
---

# Review-changes (PR/MR clone and linters)

## When this applies

User wants to **review** a PR/MR or branch they do not already have checked out, and to **run linters** on only what changed. This skill is **read-only** for the remote code (report results; do not reformat unless the user asks).

If you **edit** Python in a workspace after review, use the project skill [run-python-static-analysis](../run-python-static-analysis/SKILL.md) for lint and format rules on your own changes.

---

## 1. Choose CLI and clone location

- Prefer **`gh`** when the URL or context is GitHub (`github.com`, `GH_HOST`, or `gh` succeeds).
- Prefer **`glab`** for GitLab (`gitlab.com`, self-hosted GitLab, or `glab` succeeds).
- If both exist, pick the one matching the remote URL the user gave.

**Clone under `~/git/@REVIEWS/`** (same as `$HOME/git/@REVIEWS/`). The full path must still include the literal substring `reviews`. Name each worktree distinctly under that directory. Examples:

- `~/git/@REVIEWS/sssd-pr1842`
- `~/git/@REVIEWS/gitlab-io-sssd-mr42`

Create `~/git/@REVIEWS/` (and any intermediate parents) if needed. Do not clone over an unrelated repo without confirming.

### GitHub — typical patterns

```bash
# Clone default branch, then checkout PR (replace OWNER, REPO, N)
gh repo clone OWNER/REPO ~/git/@REVIEWS/REPO-prN
cd ~/git/@REVIEWS/REPO-prN
gh pr checkout N
```

If the user only provides a PR URL, use `gh pr checkout --help` for the exact form supported by the installed `gh` version; fallback is clone + `git fetch origin pull/N/head:pr-N` + `git checkout pr-N`.

### GitLab — typical patterns

```bash
glab repo clone GROUP/REPO ~/git/@REVIEWS/REPO-mrN
cd ~/git/@REVIEWS/REPO-mrN
glab mr checkout IID
```

Use the project’s documented default branch name (`main`, `master`, `devel`) when computing the diff below.

---

## 2. Determine changed files

From the checked-out branch (PR/MR head):

```bash
git fetch origin main 2>/dev/null || git fetch origin master 2>/dev/null || true
BASE=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD origin/master 2>/dev/null || git merge-base HEAD origin/devel 2>/dev/null)
git diff --name-only "$BASE"..HEAD
```

If merge-base is ambiguous, fall back to the remote’s default branch from `gh repo view --json defaultBranchRef` or `glab repo view -F json`, then `git merge-base HEAD "origin/$DEFAULT"`.

Treat the output as the **changed file set** for lint scope. Optionally show a short stat: `git diff --stat "$BASE"..HEAD`.

---

## 3. Run appropriate linters (read-only for review)

Run tools **from the clone root** so repo configs apply (`setup.cfg`, `tox.ini`, `.flake8`, `pyproject.toml`, `.pre-commit-config.yaml`).

| Changed files | Action |
|---------------|--------|
| `*.py` | `flake8` on those paths (omit `--max-line-length` if project config sets it). Run `black --check` on the same set **if** the project uses Black (config in `pyproject.toml` / `.pre-commit-config.yaml` / CI). Run `ruff check` without `--fix` if `ruff` is configured. |
| `*.toml` / `*.cfg` / `*.ini` | Only run Python tools if they are clearly the lint config; otherwise skip. |
| JS/TS | If `package.json` has `lint` or `eslint`, run `npm ci` or `pnpm install` only when needed, then the documented lint script on changed files or the package scope the project uses. |
| Go / Rust / etc. | Run `golangci-lint`, `cargo clippy`, etc. only when the repo defines them and changed files match. |

**Review default:** use check-only mode (`black --check`, `ruff check` without `--fix`) unless the user asked to auto-fix.

If a tool is missing, say which package or dev extra installs it; do not assume global install.

---

## 4. Evaluate the change (after linters)

Read **`git diff "$BASE"..HEAD`** (and new/changed symbols in the changed file set). Focus on the PR’s intent and regressions, not style (linters already covered that).

**Docstrings and comments**

- Public APIs, modules, classes, and non-obvious functions: docstrings should state purpose, non-obvious parameters/returns/raises/side effects, and units where relevant.
- For **added or changed** docstrings, compare nearby and same-layer symbols in the file or package: tone, section order (e.g. Args/Returns/Raises), imperative vs declarative voice, blank-line layout, reStructuredText/Google/NumPy/Sphinx style, and cross-reference patterns should **match existing conventions** in that codebase—not introduce a one-off format.
- Flag **missing** docstrings where the project or language norms expect them; **vague** or **stale** text (wrong behavior, wrong types, copy-paste); **misleading** names vs behavior.
- Inline comments: only where they add “why”; remove or fix comments that contradict the code.

**General code quality**

- **Correctness:** edge cases, error paths, resource cleanup, concurrency, security-sensitive use of input.
- **Structure:** clear naming, reasonable function size, duplication, layering leaks.
- **Tests:** if behavior changed, tests or types should reflect it; note gaps.
- **Compatibility:** API/ABI/config migrations if the diff touches interfaces.

Classify findings (e.g. must-fix / should-fix / nit) and tie each to a file or hunk. Prefer a short list of high-signal items over an exhaustive nitpick.

---

## 5. Report

Summarize: clone path, base ref, changed files, **linter** pass/fail and commands, then **quality/docstring** findings from section 4 (or state none worth noting).
