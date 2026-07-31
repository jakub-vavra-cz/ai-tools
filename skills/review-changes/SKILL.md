---
name: review-changes
description: >-
  Clones a GitHub or GitLab PR/MR with the approved `clone-review` CLI under
  ~/git/@REVIEWS/ (path must include the literal substring reviews), computes the
  changed file set against the default branch, runs project-appropriate linters in
  read-only mode, then evaluates the diff for unclear docstrings and general code
  quality. Use when reviewing pull requests or merge requests, when the user
  mentions review-changes, gh, glab, clone-review, or wants lint plus a concise
  quality pass on remote branch changes without an existing checkout.
---

# Review-changes (PR/MR clone and linters)

## When this applies

User wants to **review** a PR/MR or branch they do not already have checked out, and to **run linters** on only what changed. This skill is **read-only** for the remote code (report results; do not reformat unless the user asks).

If you **edit** Python in a workspace after review, use the project skill [run-python-static-analysis](../run-python-static-analysis/SKILL.md) for lint and format rules on your own changes.

---

## 1. Clone with `clone-review` (preferred)

Prefer the approved CLI from [ai-tools/tools](../../tools/README.md) over ad-hoc
`gh` / `glab` / `git` sequences. Install once:

```bash
pip install -e ~/git/ai-tools/tools
```

```bash
clone-review https://github.com/OWNER/REPO/pull/N --json
clone-review https://gitlab.cee.redhat.com/GROUP/REPO/-/merge_requests/N --json
clone-review identity-management/idm-ci!2726 --host gitlab.cee.redhat.com --json
```

| Flag | Purpose |
|------|---------|
| `reference` | PR/MR URL, or `owner/repo#N` / `group/proj!N` |
| `--root` | Parent dir (default `~/git/@REVIEWS` or `$CLONE_REVIEW_ROOT`); must contain `reviews` |
| `--name` | Clone dirname (default `<repo>-prN` / `<repo>-mrN`) |
| `--platform` / `--host` | Force platform/host for shorthand |
| `--no-refresh` | Reuse existing clone; only recompute the diff |
| `--json` | Machine-readable result (use this for agents) |
| `-q` | Omit file list / diffstat from text output |

Exit: `0` success, `2` error.

From the JSON (or text) report, take:

| Field | Use |
|-------|-----|
| `clone_path` | Working tree for lint / reading the diff |
| `base_ref` / `base_sha` | Merge-base vs target/default branch |
| `head_sha` | PR/MR tip |
| `changed_files` | Lint scope |
| `diff_stat` | Short summary for the review report |

**Safety:** `clone-review` refuses destinations whose resolved path does not
contain `reviews`, and will not overwrite an unrelated existing clone.

### Manual fallback (only if CLI unavailable)

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

---

## 2. Run appropriate linters (read-only for review)

Run tools **from the clone root** (`clone_path`) so repo configs apply (`setup.cfg`, `tox.ini`, `.flake8`, `pyproject.toml`, `.pre-commit-config.yaml`).

| Changed files | Action |
|---------------|--------|
| `*.py` | `flake8` on those paths (omit `--max-line-length` if project config sets it). Run `black --check` on the same set **if** the project uses Black (config in `pyproject.toml` / `.pre-commit-config.yaml` / CI). Run `ruff check` without `--fix` if `ruff` is configured. |
| Ansible `*.yml` / `*.yaml` | Prefer [writing-ansible](../writing-ansible/SKILL.md) / `check-ansible` (system + uvx pins). |
| `*.toml` / `*.cfg` / `*.ini` | Only run Python tools if they are clearly the lint config; otherwise skip. |
| JS/TS | If `package.json` has `lint` or `eslint`, run `npm ci` or `pnpm install` only when needed, then the documented lint script on changed files or the package scope the project uses. |
| Go / Rust / etc. | Run `golangci-lint`, `cargo clippy`, etc. only when the repo defines them and changed files match. |

**Review default:** use check-only mode (`black --check`, `ruff check` without `--fix`) unless the user asked to auto-fix.

If a tool is missing, say which package or dev extra installs it; do not assume global install.

---

## 3. Evaluate the change (after linters)

Read **`git diff "$base_sha".."$head_sha"`** from `clone_path` (and new/changed symbols in `changed_files`). Focus on the PR’s intent and regressions, not style (linters already covered that).

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

## 4. Report

Summarize: `clone_path`, `base_ref` / SHAs, changed files, **linter** pass/fail and commands, then **quality/docstring** findings from section 3 (or state none worth noting).
