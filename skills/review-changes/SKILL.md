---
name: review-changes
description: >-
  Clones a GitHub or GitLab PR/MR with the approved `clone-review` CLI under
  ~/git/@REVIEWS/ (path must include the literal substring reviews), computes the
  changed file set against the default branch, runs project-appropriate linters in
  read-only mode, then evaluates the diff for unclear docstrings and general code
  quality. Covers Python, Ansible, Groovy/Jenkinsfile (npm-groovy-lint) and
  AsciiDoc (docs-idmci Makefile build). Prefer `review-pr` for the full
  mechanical workflow; or use `clone-review` / `review-diff` / `check-python` /
  `check-ansible` / `check-groovy` / `check-adoc` / `cleanup-review`
  individually. Use when reviewing pull
  requests or merge requests, when the user mentions review-changes, gh, glab,
  review-pr, clone-review, review-diff, check-python, cleanup-review, groovy
  lint, Jenkinsfile, adoc, or wants lint plus a concise quality pass on remote
  branch changes without an existing checkout.
---

# Review-changes (PR/MR clone and linters)


## Hostnames (`~/git/ai-tools.env`)

Resolve `${GITLAB_HOST}`, `${JENKINS_URL}`, `${DOCS_IDMCI_URL}`, and other Scope A
hosts from `~/git/ai-tools.env` (see [ai-tools README](../../README.md#internal-hostnames-gitai-toolsenvironment)).
Do not invent or hardcode internal hostnames in commands or tracked files.

## When this applies

User wants to **review** a PR/MR or branch they do not already have checked out, and to **run linters** on only what changed. This skill is **read-only** for the remote code (report results; do not reformat or auto-fix unless the user asks — never pass `--fix` to linters).

**Never post comments, reviews, approvals, or requests-for-changes on the PR/MR autonomously.** Report findings only in the chat. Leave GitHub/GitLab review actions to the user unless they explicitly ask you to submit a review or comment.

If you **edit** code in a workspace after review, use the matching authoring skill for lint and format rules on your own changes: [run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md), [writing-ansible](../writing-ansible/SKILL.md), [writing-adoc](../writing-adoc/SKILL.md).

All commands below come from [ai-tools/tools](../../tools/README.md). Install
once with `pip install -e ~/git/ai-tools/tools`. **Never use raw `cd <clone> && git diff …` or ad-hoc `gh` / `glab` / `git` sequences** — the ai-tools CLIs handle clone management, merge-base computation, diff, lint discovery, and cleanup in a safe, consistent way.

---

## 1. Clone + lint with `review-pr` (one-shot, preferred)

A single command clones the PR/MR under `~/git/@REVIEWS`, discovers changed
files, and runs project-appropriate linters (Python via `check-python`, Ansible
via `check-ansible`, Groovy/Jenkinsfile via `check-groovy`, AsciiDoc via
`check-adoc`):

```bash
review-pr https://github.com/OWNER/REPO/pull/N --json -q
review-pr https://${GITLAB_HOST}/GROUP/REPO/-/merge_requests/N --json -q
review-pr identity-management/idm-ci!2726 --host ${GITLAB_HOST} --json -q
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
| `python.ok` / `python.results[]` | Per-tool lint details (also `ansible`, `groovy`, `adoc` when those files changed) |
| `skipped_lint` | Deleted or unlintable paths |

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
| `check-groovy path.groovy --root <clone_path> --json` | Lint Groovy / Jenkinsfile (section 1b) |
| `check-adoc path.adoc --root <clone_path> --json` | AsciiDoc build gate (section 1b) |
| `review-diff REFERENCE` | Print the patch (see section 2) |
| `cleanup-review REFERENCE` | Remove the clone (see section 4) |

---

## 1b. Groovy and AsciiDoc gates (included in `review-pr`)

`review-pr` also routes changed files to two more linters; their results appear
in the JSON as `groovy` / `adoc` (same shape as `python`: `ok`, `results[]`) and
count toward `lint_ok`:

| Changed files | CLI | Gate |
|---------------|-----|------|
| `*.groovy`, `*.gvy`, `*.gradle`, `Jenkinsfile*` | `check-groovy` | `npm-groovy-lint` with the repo's `.groovylintrc.json` (host, else podman `node:22-bookworm` + JRE); same flags as the repo CI `groovylint_check` |
| `*.adoc` in a docs-idmci tree | `check-adoc` | scoped `make maintainer_docs` / `user_docs` / `all`; fails on non-zero exit or any asciidoctor `WARNING:` / `missing attribute` ([writing-adoc](../writing-adoc/SKILL.md) gate) |

Notes for the report:

- A gate reported `[SKIP]` (no `npm-groovy-lint`/podman, or no `asciidoctor`/podman)
  did **not** run — say so; do not call it a pass.
- `.adoc` files outside a docs-idmci tree (no `Makefile` + `macros/source-url.rb`)
  are listed in `skipped_lint`.
- The AsciiDoc build writes `html/` into the review clone (removed by
  `cleanup-review`). Both gates are read-only for sources; never add `--fix`.
- Groovy: errors are must-fix, warnings should-fix, info nit. AsciiDoc typical
  must-fix: unescaped literal braces (`\{name}`), missing index entry / owner
  header on new pages, bare `link:` for internal refs. Also review the AsciiDoc
  content against the `writing-adoc` authoring rules.
- The Groovy gate lint takes ~30-60 s in the container (JRE + npm install).
- Not run: `gradle-check` / Gradle tests (need the wrapper and network) — mention
  if the diff touches `src/`, `vars/` or `tests/` in a jenkins-libs repo.

Run a gate alone (e.g. after the author pushes a fix):

```bash
check-groovy vars/foo.groovy jenkinsfile/Jenkinsfile --root "$CLONE_PATH" -q
check-adoc maintainer_docs/designs/foo.adoc --root "$CLONE_PATH" -q
```

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

- **Correctness:** edge cases, error paths, resource cleanup, concurrency, security-sensitive use of input, fixing the root cause instead of workarounds.
- **Structure:** clear naming, reasonable function size, duplication, layering leaks, avoid functions doing many unrelated things.
- **Scalability:** wrong results for concurrent access (Time-of-Check to Time-of-Use race), processing in O(n^2) or worse for input.
- **Resilience:** how will the code behave under IO/memory pressure and network load.
- **Speed:** avoid O(n^2) or O(n^3) algorithms, repeated work, and unnecessary allocations, prevent long sleeps in favour of looped polling, but keep looped code lean.
- **Tests:** if behavior changed, tests or types should reflect it; note gaps.
- **Compatibility:** API/ABI/config migrations if the diff touches interfaces.

Classify findings (e.g. must-fix / should-fix / nit) and tie each to a file or hunk. Prefer a short list of high-signal items over an exhaustive nitpick.

---

## 4. Report and cleanup

Summarize: `clone_path`, `base_ref` / SHAs, changed files, **linter** pass/fail (from `review-pr` JSON, including `groovy` / `adoc` gates), then **quality/docstring** findings from section 3 (or state none worth noting).

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
- Lint Groovy/Jenkinsfile: `npm-groovy-lint --output txt --files <changed>` from the repo root (needs Node + JRE; or a `docker.io/library/node:22-bookworm` container with `default-jre-headless`).
- Build AsciiDoc: `make <user_docs|maintainer_docs|all>` per [writing-adoc](../writing-adoc/SKILL.md).
