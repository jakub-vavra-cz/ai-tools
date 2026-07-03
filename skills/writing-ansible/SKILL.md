---
name: writing-ansible
description: >-
  Writes and edits Ansible playbooks, roles, tasks, handlers, and vars. After any
  Ansible YAML change, runs yamllint and ansible syntax-check on system Ansible
  plus uvx pins (Python 3.12 + ansible 9.13.0 and idm-ci ansible 8.7.0), with no
  deprecation warnings (ansible-lint --strict and output checks), and project
  ansible-lint on all stacks when configured, until clean. Use when creating or
  modifying Ansible code, playbooks, roles, inventories, or ansible-lint/yamllint
  config.
---

# Ansible edits: yamllint and syntax-check

## CLI helper (`check-ansible`)

Prefer the packaged runner from `ai-tools/tools` when available — it encodes this
skill’s gate (yamllint, multi-stack syntax-check / ansible-lint, deprecations):

```bash
pip install -e /path/to/ai-tools/tools   # once
check-ansible path/to/changed.yml
check-ansible path/to/playbook.yml -i inventory.yml
check-ansible path/to/tasks.yml --skip-uvx -q
check-ansible path/to/tasks.yml --skip-extra -q   # primary uvx only (skip idm-ci 8.7.0)
```

See `tools/README.md` for flags (`--ansible-version`, `--extra-ansible-version`,
`--extra-python`, `--json`, skip switches). When the CLI is not installed, run
the manual steps below.

## Before running any check

Do **not** assume default CLI flags until you have checked the repo. Discover how this project expects Ansible linting to run, then invoke tools so they pick up that configuration.

1. **In-repo configuration (prefer this)** — Look for settings that define yamllint, ansible-lint, or ansible-playbook usage:

   - **yamllint**: `.yamllint`, `.yamllint.yml`, or `[yamllint]` in `setup.cfg` / `pyproject.toml`.
   - **ansible-lint**: `.ansible-lint`, `.ansible-lint.yml`, or `ansible-lint` in `.pre-commit-config.yaml`.
   - **Ansible**: `ansible.cfg` (repo root or nearest parent of edited files), `files/ansible.cfg`, or `ANSIBLE_CONFIG`.
   - **Orchestration**: `.pre-commit-config.yaml` / `.pre-commit-hooks.yaml` (hooks often show exact checker and args maintainers use).

   When a config file exists, run the tool **without** overriding those settings (e.g. plain `yamllint path/to/file.yml` so `.yamllint` applies). Only add explicit flags when they match the discovered config or when you must point at a config path the tool would not find by default.

2. **If project lint configuration is missing or unclear** — Inspect CI for what the project actually runs in automation:

   - **GitHub Actions**: `.github/workflows/*.yml` — look for `yamllint`, `ansible-lint`, `ansible-playbook --syntax-check`, `pre-commit run`, or `make` lint targets.
   - **GitLab CI**: `.gitlab-ci.yml`, `.gitlab-ci.yaml`, and includes under `.gitlab/ci/*.yml` — same signals (e.g. `yamllint metadata/ test-plan/`).

   Mirror CI’s choice of tools, paths, and substantive arguments when running locally after edits.

3. **Working directory** — Run checks from the directory that owns `ansible.cfg` / `.ansible-lint` / `.yamllint` when those files are not at the repo root (e.g. `sssd-ci-containers/src/ansible/`, `idm-ci/`). Walk up from the edited file until you find project config, then use that as `$ANSIBLE_ROOT`.

4. **Ansible stacks** — Run every Ansible check on **system** and on **each** uvx pin after edits:

   | Stack | How | Purpose |
   |-------|-----|---------|
   | **System** | `ansible-playbook` / `ansible-lint` on `PATH` | Host / active venv |
   | **uvx primary** | Python **3.12** + **`ansible==9.13.0`** (ansible-core **2.16.x**) | Default forward/compat gate |
   | **uvx idm-ci** | Python **3.12** + **`ansible==8.7.0`** (ansible-core **2.15.x**) | Matches `idm-ci` `agent/requirements/all.pip` |

   Record stack versions before checking:

   ```bash
   ansible-playbook --version
   uvx --python 3.12 --from ansible-core --with 'ansible==9.13.0' ansible-playbook --version
   uvx --python 3.12 --from ansible-core --with 'ansible==8.7.0' ansible-playbook --version
   ```

   Fix failures on **any** stack before considering the task done. If CI pins a different primary `ansible==9.x` (e.g. sssd-ci-containers uses `9.8` for CentOS 8), use that pin for the **primary** uvx `--with` instead of `9.13.0`; still run the idm-ci **8.7.0** extra pin unless the project clearly does not need it (`check-ansible --skip-extra`, or omit the extra manual uvx invocation).

   When `uv` / `uvx` is unavailable, run the **system** stack only and report that the uvx gates were skipped.

## uvx wrappers (pinned stacks)

Use these prefixes from `$ANSIBLE_ROOT`. They create an isolated tool env on first run.

**Prerequisite** — if `uvx --python 3.12 …` fails with “No interpreter found”:

```bash
uv python install 3.12
```

**Pinned command prefixes** (reuse for every check below):

```bash
# Primary — ansible 9.13.0 (ansible-core 2.16.x)
UVX_ANSIBLE=(uvx --python 3.12 --from ansible-core --with 'ansible==9.13.0')
UVX_LINT=(uvx --python 3.12 --from ansible-lint --with 'ansible==9.13.0')

# idm-ci agent — ansible 8.7.0 (ansible-core 2.15.x; agent/requirements/all.pip)
UVX_IDMCI_ANSIBLE=(uvx --python 3.12 --from ansible-core --with 'ansible==8.7.0')
UVX_IDMCI_LINT=(uvx --python 3.12 --from ansible-lint --with 'ansible==8.7.0')

# yamllint (same Python interpreter for consistency)
uvx --python 3.12 --from yamllint yamllint
```

Example — syntax-check a playbook on both uvx pins:

```bash
cd "$ANSIBLE_ROOT"
"${UVX_ANSIBLE[@]}" ansible-playbook --syntax-check -i inventory.yml path/to/playbook.yml
"${UVX_IDMCI_ANSIBLE[@]}" ansible-playbook --syntax-check -i inventory.yml path/to/playbook.yml
```

**Collections** — when syntax-check or ansible-lint fails on missing collections, install project requirements into a local path and point Ansible at it:

```bash
cd "$ANSIBLE_ROOT"
COLLECTIONS_DIR="${ANSIBLE_ROOT}/.ansible-compat/collections"
mkdir -p "$COLLECTIONS_DIR"
export ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS_DIR"
"${UVX_ANSIBLE[@]}" ansible-galaxy collection install -r requirements.yml -p "$COLLECTIONS_DIR"
# or: collections/requirements.yml, meta/collection-requirements.yml — use what the repo documents
```

If system-wide collections under `/usr/share/ansible/collections` skew uvx results, keep `ANSIBLE_COLLECTIONS_PATH` set to the project-local dir for the compat run only; the system stack may still use the default collection path.

**Deprecation checks** — for every Ansible command below on **all** stacks, use:

```bash
export ANSIBLE_DEPRECATION_WARNINGS=True
```

Capture combined stdout/stderr and **fail** if output matches Ansible runtime deprecations:

```bash
# Example wrapper — run the real command inside, then scan output
output=$(ansible-playbook --syntax-check path/to/playbook.yml 2>&1) || { echo "$output"; exit 1; }
echo "$output"
echo "$output" | rg -qi '\[DEPRECATION WARNING\]|DEPRECATION WARNING' && {
  echo "ERROR: deprecation warnings in ansible-playbook output"; exit 1; }
```

`--syntax-check` validates structure only and usually prints **no** runtime deprecations; static deprecations (deprecated modules, bare vars, `local_action`, old Jinja, non-FQCN patterns ansible-lint tracks) are caught by **ansible-lint** in the next sections. Do not skip ansible-lint deprecations just because syntax-check was clean.

## After any Ansible YAML change

Treat this section as **project-defined tooling**. Always run the checks below on every `.yml` / `.yaml` file you created or modified in this turn that contains Ansible content (playbooks, roles, tasks, handlers, vars, group/host vars, inventory, collections).

### 1. yamllint

Run yamllint on each changed file and fix reported issues before considering the task done.

```bash
cd "$ANSIBLE_ROOT"   # when config is not at repo root
yamllint path/to/changed_file.yml
```

Optionally also run `uvx --python 3.12 --from yamllint yamllint …` when yamllint is not installed on the system.

If multiple files changed, pass all of them (or the smallest sensible scope the project uses in CI, e.g. `yamllint metadata/infra/ test-plan/`). Respect discovered yamllint config; do not override with ad-hoc ignores unless the user asks.

When CI scopes yamllint to specific directories, still lint **changed files outside that scope** individually so your edit does not introduce new violations.

### 2. Ansible syntax-check (system + uvx pins)

Run **system** and **both** uvx pins for every changed playbook. Use the same inventory/extra args for each. Define the `UVX_*` arrays from **uvx wrappers** above first.

**Playbooks** (files with a top-level `hosts:` / `import_playbook:` / `- hosts:` play list):

```bash
cd "$ANSIBLE_ROOT"

# 1) System Ansible
output=$(ansible-playbook --syntax-check path/to/playbook.yml 2>&1) || { echo "$output"; exit 1; }
echo "$output"
echo "$output" | rg -qi '\[DEPRECATION WARNING\]|DEPRECATION WARNING' && exit 1

# 2) Primary uvx (Python 3.12 + ansible 9.13.0)
output=$("${UVX_ANSIBLE[@]}" ansible-playbook --syntax-check path/to/playbook.yml 2>&1) || { echo "$output"; exit 1; }
echo "$output"
echo "$output" | rg -qi '\[DEPRECATION WARNING\]|DEPRECATION WARNING' && exit 1

# 3) idm-ci uvx (Python 3.12 + ansible 8.7.0)
output=$("${UVX_IDMCI_ANSIBLE[@]}" ansible-playbook --syntax-check path/to/playbook.yml 2>&1) || { echo "$output"; exit 1; }
echo "$output"
echo "$output" | rg -qi '\[DEPRECATION WARNING\]|DEPRECATION WARNING' && exit 1
```

Use the inventory the project documents when syntax-check requires it (comments in the playbook, README, or CI). Common patterns — run **each** line on **system** and **both** uvx pins:

```bash
ansible-playbook --syntax-check -i config/test.inventory.yaml path/to/playbook.yml
"${UVX_ANSIBLE[@]}" ansible-playbook --syntax-check -i config/test.inventory.yaml path/to/playbook.yml
"${UVX_IDMCI_ANSIBLE[@]}" ansible-playbook --syntax-check -i config/test.inventory.yaml path/to/playbook.yml
```

If `--syntax-check` fails because of missing inventory or collections, use the project’s documented inventory, install declared collections (see **Collections** under **uvx wrappers**), or run from the same container/venv CI uses — do not skip system or either uvx pin without recording why.

**Role tasks, handlers, includes without a standalone playbook** — syntax-check on **all** stacks via ansible-lint or a minimal wrapper playbook:

```bash
# Prefer when .ansible-lint or pre-commit ansible-lint is present — always add --strict:
ansible-lint --strict path/to/tasks/main.yml
"${UVX_LINT[@]}" ansible-lint --strict path/to/tasks/main.yml
"${UVX_IDMCI_LINT[@]}" ansible-lint --strict path/to/tasks/main.yml

# Or one-off wrapper (from $ANSIBLE_ROOT, adjust role path) — run on all stacks:
ansible-playbook --syntax-check -i localhost, -c local - <<'EOF'
---
- hosts: localhost
  tasks:
    - import_tasks: roles/myrole/tasks/main.yml
EOF
"${UVX_ANSIBLE[@]}" ansible-playbook --syntax-check -i localhost, -c local - <<'EOF'
---
- hosts: localhost
  tasks:
    - import_tasks: roles/myrole/tasks/main.yml
EOF
"${UVX_IDMCI_ANSIBLE[@]}" ansible-playbook --syntax-check -i localhost, -c local - <<'EOF'
---
- hosts: localhost
  tasks:
    - import_tasks: roles/myrole/tasks/main.yml
EOF
```

Fix syntax errors and re-run the failing stack until all exit 0 with **no deprecation warnings** in captured output.

### 3. ansible-lint (when the project uses it)

If the repo has `.ansible-lint`, an `ansible-lint` pre-commit hook, or an `ansible-lint` CI job, run ansible-lint on changed Ansible paths on **all** stacks after yamllint and syntax-check pass. Always pass **`--strict`** so warnings (including deprecation-related rules in `warn_list`) fail the run:

```bash
cd "$ANSIBLE_ROOT"
export ANSIBLE_DEPRECATION_WARNINGS=True

# System
ansible-lint --strict path/to/changed_file.yml

# Primary uvx (Python 3.12 + ansible 9.13.0)
"${UVX_LINT[@]}" ansible-lint --strict path/to/changed_file.yml

# idm-ci uvx (Python 3.12 + ansible 8.7.0)
"${UVX_IDMCI_LINT[@]}" ansible-lint --strict path/to/changed_file.yml
# or the path/directory CI passes (e.g. playbooks/, src/ansible/)
```

Respect `.ansible-lint` skip/enable rules; do not add ad-hoc `--skip-list` unless the user asks. A rule may pass on one stack and fail on another — fix the code or document a stack-specific exception only when the project already uses that pattern.

### 4. Deprecation scan (always — all stacks)

Even when the project has no `.ansible-lint`, run a **deprecation-only** ansible-lint pass on every changed Ansible path. `--syntax-check` does not report most deprecations; this step catches them.

```bash
cd "$ANSIBLE_ROOT"
export ANSIBLE_DEPRECATION_WARNINGS=True

# System
ansible-lint --strict -t deprecations path/to/changed_file.yml

# Primary + idm-ci uvx pins
"${UVX_LINT[@]}" ansible-lint --strict -t deprecations path/to/changed_file.yml
"${UVX_IDMCI_LINT[@]}" ansible-lint --strict -t deprecations path/to/changed_file.yml
```

The `deprecations` tag covers rules such as `deprecated-module`, `deprecated-bare-vars`, `deprecated-local-action`, and related syntax removals. Fix every finding; do not `# noqa` or skip-list unless the project already documents that exception.

When a project `.ansible-lint` sets `strict: true` or `profile: production`, the full **§3** run may already enforce overlapping rules — still run **§4** on changed paths so all stacks explicitly gate deprecations.

## Order of operations

1. **Discover** lint expectations (in-repo config, then CI if needed), as in **Before running any check**. Set `$ANSIBLE_ROOT`. Ensure `uv python install 3.12` when needed. Print `ansible-playbook --version` for system and both uvx pins (9.13.0 and 8.7.0).
2. Edit the Ansible YAML file(s).
3. **yamllint** on every changed file → fix → re-run until clean.
4. **ansible-playbook --syntax-check** on changed playbooks — **system**, then **uvx 9.13.0**, then **uvx 8.7.0** (same inventory) → fix → re-run failing stack until all pass with **no `[DEPRECATION WARNING]` in output**.
5. For changed role tasks/handlers/includes, **syntax-check** via ansible-lint or wrapper playbook on **all** stacks → fix → re-run until all pass cleanly.
6. If the project uses **ansible-lint**, run **`ansible-lint --strict`** on **system**, then **both** uvx pins, on changed paths → fix → re-run until all pass.
7. **`ansible-lint --strict -t deprecations`** on changed paths — **system**, then **both** uvx pins → fix → re-run until all pass (always, even when §6 was skipped).
8. Re-run **yamllint** and any failed Ansible stack if lint/autofix edits touched YAML again.

Do not mark the task complete while any check fails on files you changed on **any** stack, or while **deprecation warnings** remain in Ansible check output or ansible-lint results.

## Authoring best practices

Follow **existing repo conventions first** (naming, FQCN vs short module names, `become: yes` vs `true`, variable prefixes, header comments). When adding new code with no clear precedent, apply the practices below — they align with ansible-lint’s `production` profile and patterns used in idm-ci, sssd-ci-containers, and linux-system-roles content in this workspace.

### Tasks and modules

- **Name every task and handler** with a clear, unique `name:` (ansible-lint `name` rule). Avoid empty or generic names like “Install packages”.
- **Prefer FQCN** for modules and plugins (`ansible.builtin.copy`, `ansible.builtin.service`). Some trees mix short names (`copy`, `template`) with FQCN — match the file you are editing; use FQCN in new roles/playbooks unless the project is consistently short-named.
- **Avoid deprecated Ansible syntax** — replace deprecated modules (`deprecated-module`), bare variable forms (`deprecated-bare-vars`), `local_action` (use `delegate_to: localhost`), non-canonical module aliases (use FQCN + canonical names), and Jinja features flagged by ansible-lint. Runtime-only deprecations (template evaluation, module options) may require `--check` against localhost inventory when the project documents that — still fail on `[DEPRECATION WARNING]` in output.
- **Avoid the `collections:` keyword**; declare FQCN instead (ansible-lint `fqcn` rule).
- **Prefer dedicated modules over `command` / `shell`** when one exists (`ansible.builtin.package`, `ansible.builtin.file`, `ansible.posix.synchronize`, collection modules). Use raw shell only when no module fits.
- **`command` / `shell` must declare change semantics** (ansible-lint `no-changed-when`):
  - Read-only probe: `changed_when: false`
  - Always mutates: `changed_when: true` or a precise expression on `register`
  - Prefer `creates:` / `removes:` when they express idempotency cleanly
- **Quote user/path data** in shell one-liners (`{{ path | quote }}`) to avoid injection and whitespace bugs.

### Variables and validation

- **Prefix role variables** with the role name (e.g. `ad_integration_realm`); use a **double-underscore prefix** for internal/register temps the role owns (e.g. `__ad_integration_packages`).
- **Validate required inputs early** with `ansible.builtin.fail` and actionable `msg` before mutating the system.
- **Use `omit`** for optional module args instead of passing empty/null values when the project already does (see `ad_integration` package tasks).
- **Platform-specific values** belong in `vars/`, `tasks/set_vars.yml`, or `include_tasks` — not scattered magic strings in tasks.

### Idempotency, control flow, and handlers

- **Guard optional work** with `when:` (feature flags, ostree vs classic RPM, OS family).
- **Group related steps** in `block:`; use `rescue:` / `always:` when failure handling is required.
- **Restart services via handlers** (`notify:` + `handlers/main.yml`); call `ansible.builtin.meta: flush_handlers` before steps that depend on a prior handler (config then immediate use).
- **Read-only checks** (stat, slurp, command for assert): `register` + `changed_when: false`; use `failed_when` for assertions instead of bare `command` exit codes when clearer.
- **Prefer `import_tasks`** for static includes; use `include_tasks` when the include is conditional or loops.

### Files, permissions, and secrets

- Set explicit **`mode`**, and **`owner` / `group`** on `copy`, `template`, and `file` tasks (ansible-lint `risky-file-permissions`). Quote octal modes (`mode: "0644"`).
- **`no_log: true`** on tasks that handle passwords, tokens, private keys, or other secrets (ansible-lint `no-log-password`). Do not disable logging for debugging and leave it off.
- **Do not commit secrets** — use vault, CI vars, or inventory `group_vars` patterns the project already uses.

### Playbooks and layout

- Start YAML documents with `---`; use **2-space** indentation (yamllint default in idm-ci / mrack).
- **Header comments** with an example run line when the playbook needs non-obvious inventory/extra-vars (idm-ci `playbooks/prep/*.yaml` pattern).
- **Collections**: if you add a collection dependency, update `requirements.yml` / `collections/requirements.yml` with a pinned version and install before syntax-check.
- **Tags** — add when the playbook already uses selective execution; do not tag every task in untagged playbooks.

### ansible-lint autofix

When ansible-lint reports fixable `fqcn` (or other `--fix`-able) findings and the project does not forbid it, run `--fix` on the **system** stack first, then re-validate on **all** stacks:

```bash
ansible-lint --fix path/to/changed_file.yml
"${UVX_LINT[@]}" ansible-lint --fix path/to/changed_file.yml
"${UVX_IDMCI_LINT[@]}" ansible-lint --fix path/to/changed_file.yml
```

Re-run yamllint, syntax-check (all stacks, no deprecation output), **`ansible-lint --strict`**, and **`ansible-lint --strict -t deprecations`** after autofix. Never `--fix` across unrelated files the user did not ask to change.

## Tools missing

**System stack** — use whatever the project documents (`dnf install ansible-core`, project venv, container). At minimum: `ansible-playbook`, and **`ansible-lint`** (required for deprecation scans even when the project has no `.ansible-lint`).

**uvx pins** — install [uv](https://docs.astral.sh/uv/) and use **uvx wrappers** above (`uv python install 3.12` once). If `uv` / `uvx` is unavailable, run the system stack only and report that the Python 3.12 + ansible 9.13.0 / 8.7.0 gates were skipped.

**Fallback install** when neither stack has the tools:

```bash
pip install 'ansible==9.13.0' yamllint ansible-lint
# idm-ci agent pin when validating that tree:
# pip install 'ansible==8.7.0'
# or: dnf install ansible-core yamllint ansible-lint
```

Prefer the project’s documented toolchain when known. If tools truly cannot be installed, say so and list the commands the user should run locally.

## Scope notes

- **Plain YAML without Ansible** (e.g. GitLab CI, generic config) — run **yamllint** only unless the user asked for Ansible changes or the file lives under Ansible paths the project lints.
- **Line-length** — Prefer wrapping or splitting long lines; use `# yamllint disable-line rule:line-length` only when matching existing project patterns (e.g. long URLs in idm-ci metadata).
- **Ansible stacks** — `ansible-playbook --syntax-check` and ansible-lint (when configured) must pass on **system Ansible**, **uvx ansible 9.13.0**, and **uvx ansible 8.7.0** (idm-ci agent pin). yamllint runs once via system `yamllint` when available.
- **No deprecation warnings** — `ansible-lint --strict -t deprecations` on all stacks plus scanning ansible-playbook output for `[DEPRECATION WARNING]`; fix all deprecations before done.
