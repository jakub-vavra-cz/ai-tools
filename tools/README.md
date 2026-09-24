# ai-tools CLI

Standalone command-line helpers from the [ai-tools](https://github.com/jakub-vavra-cz/ai-tools) repository.
These are intended as tools both for manual ause and for agent to use as "approved" tools.

## Install

From a local checkout:

```bash
pip install -e /path/to/ai-tools/tools
```

## Commands

| Command | Description |
|---------|-------------|
| `clean-twd` | Remove stale IdM-CI `twd` logs and test artifacts before re-execution |
| `pull-jenkins-artifacts` | Fetch Jenkins console, extract `RD_JR_ARTIFACTS_URL`, download twd artifacts (auto-decompress) |
| `jenkins-to-testrun` | Pull Jenkins artifacts and scaffold `@TESTRUNS/<campaign>/twd` for local `te` |
| `artifact-grep` | Search Jenkins / IdM-CI artifact dumps and twd logs (gzip-aware) |
| `idmci-rerun-failed` | `clean-twd` + optional overlay + re-run only failed pytest tests via `te` |
| `check-ansible` | yamllint + multi-stack ansible syntax-check / ansible-lint (writing-ansible) |
| `check-python` | Read-only Python lint/format checks (ruff, flake8, black, isort) |
| `dump-polarion-testcase` | Fetch a Polarion testcase via REST API and dump it as `key=value` |
| `dump-polarion-docs` | Dump Polarion project documents for Confluence migration |
| `dump-polarion-requirements` | Dump Polarion requirements for Confluence migration |
| `import-polarion-confluence` | Import Polarion dump into stage Confluence (IDMRHEL) |
| `import-jira-testcase` | Import a jira-format dump into RHELTEST (match by ID, then summary) |
| `scan-python-testcase` | Scan local Python tests (Betelgeuse-style) into jira-format dumps |
| `beetlejuice` | Import Betelgeuse Polarion XML to Jira (`test-case`; `test-run` planned) |
| `is-merged` | Check whether a local tip is already on upstream (ancestor / cherry / patch-id) |
| `clone-review` | Clone a GitHub PR / GitLab MR under `~/git/@REVIEWS` and list changed files |
| `review-diff` | Print PR/MR patch, diffstat, or changed-file list (gh/glab or local clone) |
| `cleanup-review` | Remove clone-review checkouts under `~/git/@REVIEWS` after a review |
| `review-pr` | Orchestrate clone + diff metadata + lint changed files (+ optional cleanup) |
| `sync-twd-tests` | Overlay local test WIP onto an IdM-CI campaign sibling of `twd` |
| `brew-fetch-nvr` | Download brewroot binary RPMs for a Fixed in Build NVR into `twd/brew-rpms/` |
| `twd-rpm` | Query or install those RPMs on twd inventory hosts (default group: `client`) |
| `te-test-summary` | Extract the pytest/te short summary from a `twd` for a Jira draft |
| `run-idm-jenkins` | Upload metadata as an sssd-qe GitLab snippet; print Jenkins trigger params |
| `decompress-logs` | Decompress gzip IdM-CI / Jenkins log artifacts (incl. misnamed `.gz`) |
| `bugzilla` | Query Bugzilla REST API (`get`, `search`, `config`) |

### clean-twd

Allow ai agent to delete specific logs without giving it rights to run "rm" directly.

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
clean-twd              # remove logs/, runner.log, pytest-run.rc, *junit.xml
clean-twd -n           # dry-run
clean-twd /path/to/twd # explicit twd path
```

### pull-jenkins-artifacts

Fetches Jenkins `consoleText`, extracts `RD_JR_ARTIFACTS_URL`, and downloads
diagnostic twd files (`metadata.mod.yaml`, `runner.log`, junit, etc.) from the
artifact server. Gzip-compressed uploads are decompressed on download and a
**`decompress-logs`** pass runs on the output tree afterward (misnamed `.gz`,
gzip at plain paths). Use `--no-decompress` to skip the post-pass. For manual
`curl` dumps, use standalone **`decompress-logs`**.

Requires `JENKINS_USERNAME` and `JENKINS_PASSWORD` (API token) for console
fetch. Optional: `REQUESTS_CA_BUNDLE` for corp TLS.

```bash
export JENKINS_USERNAME=<username>
export JENKINS_PASSWORD=<api-token>
export REQUESTS_CA_BUNDLE=~/git/certs/combined-certifi.pem

pull-jenkins-artifacts 'https://jenkins…/job/…/123/' -o /tmp/jenkins-123
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --url-only
pull-jenkins-artifacts --artifacts-url 'https://idm-artifacts…/path/' -f metadata.mod.yaml
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --console-only
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --no-decompress
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --json
```

### jenkins-to-testrun

Pull Jenkins IdM-CI artifacts (via `pull-jenkins-artifacts`, including automatic
decompression) and create an `@TESTRUNS` campaign with `twd/metadata.yaml` ready
for `te`.

```bash
export JENKINS_USERNAME=<username>
export JENKINS_PASSWORD=<api-token>

jenkins-to-testrun 'https://jenkins…/job/…/123/'
jenkins-to-testrun 'https://jenkins…/job/…/123/' --campaign jenkins-c-ares-sssd-tier0-3
jenkins-to-testrun 'https://jenkins…/job/…/123/' --git-path ~/git --json
jenkins-to-testrun 'https://jenkins…/job/…/123/' --metadata-only
jenkins-to-testrun 'https://jenkins…/job/…/123/' --pull-dir /tmp/jenkins-123 --keep-pull-dir
```

Defaults: `$GIT_PATH` or `~/git` → `~/git/@TESTRUNS/<campaign>/twd/`. Campaign
name is derived from the Jenkins job path and build number unless `--campaign` is
set. Copies `metadata.mod.yaml` → `metadata.yaml` plus reference artifacts
(`runner.log`, junit, `logs/`) unless `--metadata-only`. Prints `te --upto prep`
and `te --phase test` next steps.

Exit `0` on success, `2` on error.

### check-ansible

Runs the [writing-ansible](../skills/writing-ansible/SKILL.md) check gate on
one or more Ansible YAML files:

1. Discover `$ANSIBLE_ROOT` (`ansible.cfg`, `.ansible-lint`, `.yamllint`, …)
2. **yamllint** (system, or `uvx` fallback)
3. **ansible-playbook --syntax-check** on playbooks — system + uvx pins
   (Python 3.12 + `ansible==9.13.0`, plus idm-ci `ansible==8.7.0`); fails on
   `[DEPRECATION WARNING]`
4. **ansible-lint --strict** when the project uses ansible-lint, or for
   non-playbook role/tasks files — system + both uvx pins
5. **ansible-lint --strict -t deprecations** always — system + both uvx pins

```bash
check-ansible roles/facts/tasks/RedHat.yml
check-ansible playbook.yml -i inventory.yml
check-ansible roles/facts/tasks/RedHat.yml --skip-uvx -q
check-ansible roles/facts/tasks/RedHat.yml --skip-extra -q   # primary uvx only
check-ansible roles/facts/tasks/RedHat.yml --json
check-ansible path.yml --ansible-version 9.8.0   # e.g. CentOS 8 primary pin
check-ansible path.yml --extra-ansible-version 8.7.0 --extra-python 3.12
```

Exit `0` when all non-skipped checks pass; `1` on lint/syntax/deprecation
failure; `2` on bad arguments / missing paths.

### check-python

Runs read-only Python checks on one or more `.py` files, discovering project
tooling from `pyproject.toml`, `.flake8`, `.pre-commit-config.yaml`, and CI
workflows. Mirrors the
[run-python-static-code-analysis](../skills/run-python-static-code-analysis/SKILL.md)
skill:

1. **Ruff projects** — `ruff check` + `ruff format --check`
2. **flake8 / black / isort projects** — `flake8`, plus `black --check` and
   `isort --check-only` when configured
3. **Unconfigured trees** — ruff fallback (`ruff check` + `ruff format --check`)

```bash
check-python path/to/changed.py
check-python src/pkg/mod.py tests/test_mod.py --root ~/git/@REVIEWS/repo-pr42
check-python file.py --json
check-python file.py --force-flake8 -q
check-python file.py --skip-ruff --skip-black
```

| Flag | Purpose |
|------|---------|
| `paths` | One or more `.py` files |
| `--root` | Override project root for config discovery |
| `--skip-ruff` / `--skip-flake8` / `--skip-black` / `--skip-isort` | Skip tools |
| `--force-ruff` / `--force-flake8` | Override discovery |
| `--json` | Machine-readable report |
| `-q` | Omit command output from text report |

Exit `0` when all non-skipped checks pass; `1` on lint failure; `2` on bad
arguments / missing paths.

### dump-polarion-docs / dump-polarion-requirements / import-polarion-confluence

Migrate Polarion **documents** and **requirements** into stage Confluence
(`IDMRHEL`). Skill: [migrate-polarion-confluence](../skills/migrate-polarion-confluence/SKILL.md).

```bash
export POLARION_TOKEN=…
export CONFLUENCE_URL=https://stage-redhat.atlassian.net
export CONFLUENCE_USERNAME=… CONFLUENCE_API_TOKEN=…

cd ~/git/<project>-doc-migration
dump-polarion-docs --project-id RHEL_IDM --out-dir polarion-dump
dump-polarion-requirements --project-id RHEL_IDM --out-dir polarion-dump/requirements
import-polarion-confluence \
  --dump-dir polarion-dump \
  --state-file polarion-dump/confluence-import.json \
  --parent-id 454629179 \
  --project-id RHEL_IDM \
  --project-label "RHEL Identity Management" \
  --skip-attachments
```

Parts API failures soft-dump from `homePageContent`. Testcase citations link to
stage RHELTEST summary search. See the skill `reference.md` for flags and
parent page ids (CERT / RHDS / RHEL_IDM).

### dump-polarion-testcase

Fetches a Polarion work item (testcase) and its test steps via the REST API
v1 (same endpoints/auth as `mcp-server-polarion`) and writes a one-line-per-
field `key=value` dump.

**Default `--format jira`** maps fields for RHELTEST Test Case import
([create-rheltest-testcase](../skills/create-rheltest-testcase/SKILL.md)):

| Dump key | Polarion source | Jira field |
|----------|-----------------|------------|
| `summary` | `title` | Summary |
| `assignee` | Polarion assignee email, else author email | Assignee |
| `components` | `casecomponent` | Components |
| `labels` | `tags` | Labels |
| `AssignedTeam` | `subsystemteam` | `customfield_10606` |
| `ID` | `testCaseID` | `customfield_10591` |
| `URL` | `automation_script` if valid http(s), else hyperlinks `testscript` | `customfield_10933` |
| `External issue URL` | Polarion browse URL | `customfield_10766` |
| `status` | Polarion status | Issue status (`Draft` / `Active` / `Retired`) |
| `description` | Polarion description + setup / steps / teardown + remaining fields as HTML (`created`/`updated` omitted) | Description |

Polarion status mapping: `draft` / `needs update` / `proposed` → `Draft`;
`inactive` → `Retired`; `approved` → `Active`. The import tool applies
`status` via a workflow transition after create/update.

Use `--format polarion` for the raw Polarion attribute dump. Newlines in
values are escaped as `\n`.

Requires `POLARION_URL` and `POLARION_TOKEN`. Optional: `POLARION_VERIFY_SSL`
(`false` to disable TLS verify), `REQUESTS_CA_BUNDLE` for corp TLS.

```bash
export POLARION_URL=https://polarion.engineering.redhat.com
export POLARION_TOKEN=<personal-access-token>
export REQUESTS_CA_BUNDLE=~/git/certs/combined-certifi.pem

dump-polarion-testcase -P RHEL_IDM -i RHEL-130263
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 -o /tmp/RHEL-130263.properties
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 --stdout
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 --format polarion
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 --no-teststeps
```

### scan-python-testcase

Betelgeuse-style scanner: walks a local/cloned tree for `test_*.py` /
`*_test.py`, collects `test_*` functions/methods via AST, reads `:field:`
docstring metadata (and optional [pytest-output](https://github.com/next-actions/pytest-output)
`polarion.yaml` defaults), and writes one jira-format `key=value` dump per
test for `import-jira-testcase`.

Does expand ``@pytest.mark.parametrize`` (literal values) and
``@pytest.mark.topology`` / ``KnownTopology(Group)`` into one dump per
variant. Each variant gets a distinct ``ID`` (pytest-style
``…[param-id] (topology)``) and parameters are appended to
``summary`` / title.

```bash
# Auto-discovers polarion.yaml upward from the source path when present
scan-python-testcase ~/git/sssd-fork-master/src/tests/system/tests \
  -o /tmp/sssd-dumps --tests-url https://github.com/SSSD/sssd/tree/master/src/tests/system

scan-python-testcase path/to/test_foo.py -o /tmp/dumps --no-polarion-config \
  --id-prefix idm-sssd-tc --title-prefix 'IDM-SSSD-TC: ' \
  --component sssd --team rhel-idm-sssd --upstream yes

scan-python-testcase path/to/tests -n --json   # dry-run summary
import-jira-testcase /tmp/sssd-dumps/<id>.properties --dry-run
```

Optional: PyYAML when reading `--polarion-config` / auto-discovered
`polarion.yaml`.

### beetlejuice

Betelgeuse-shaped CLI for Polarion importer XML → Jira RHELTEST:

| Subcommand | Status | Input |
|------------|--------|--------|
| `test-case` | implemented | `import-testcase.xml` (Betelgeuse / IdM-CI) |
| `test-run` | planned | `import-testrun.xml` |

`test-case` maps each `<testcase>` through the same Polarion→Jira path as
`dump-polarion-testcase` / `import-jira-testcase`. Accepts a local XML file
(plain or gzip), a directory of such files, or an http(s) URL to the XML or
the `polarion/` directory listing. Gzipped IdM artifact uploads are
decompressed automatically.

| XML | Dump / Jira |
|-----|-------------|
| `@id` (or `testCaseID` custom field) | `ID` (`customfield_10591`) |
| `title` | `summary` |
| `status-id` | `status` (same mapping as dump-polarion) |
| `casecomponent` | `components` |
| `subsystemteam` (`sst_idm_*` → `rhel-idm-*`) | `AssignedTeam` |
| `tags` / `upstream` / `customerscenario` | `labels` |
| `automation_script` if http(s), else `testscript` hyperlink | `URL` |
| description + setup + test-steps + other fields | `description` (HTML) |

Requires `-o` and/or `--import`. Import needs IdM-CI Jira env vars (with
`JIRA_*` fallback when run from ai-tools):

| Variable | Role |
|----------|------|
| `IDMCI_JIRA_URL` | Jira base URL (default: `https://stage-redhat.atlassian.net`) |
| `IDMCI_JIRA_EMAIL` | Account email (required for `--import`) |
| `IDMCI_JIRA_API_TOKEN` | API token (required for `--import`) |
| `IDMCI_JIRA_PROJECT` | Default project key (`-P` / `--project`; else `RHELTEST`) |

```bash
# Dump only (from local XML or polarion/ dir)
beetlejuice test-case /path/to/import-testcase.xml -o /tmp/bj-dumps
beetlejuice test-case /path/to/polarion/ -o /tmp/bj-dumps

# From IdM artifacts URL (directory listing or direct XML)
beetlejuice test-case 'https://idm-artifacts…/polarion/' -o /tmp/bj-dumps --limit 5
beetlejuice test-case 'https://idm-artifacts…/polarion/import-testcase.xml' -o /tmp/bj-dumps

# Push to stage Jira (dry-run first)
export IDMCI_JIRA_EMAIL=<you@redhat.com>
export IDMCI_JIRA_API_TOKEN=<token>
# optional: IDMCI_JIRA_URL / IDMCI_JIRA_PROJECT (defaults: stage URL, RHELTEST)
beetlejuice test-case /path/to/import-testcase.xml --import -n --skip-assignee --skip-components
beetlejuice test-case /path/to/import-testcase.xml --import --skip-assignee --team rhel-idm-sssd --tier 1
```

### import-jira-testcase

Imports a `--format jira` dump into Jira (default project `RHELTEST`, issue
type `Test Case`):

1. Search for an existing Test Case with matching `customfield_10591` (`ID`)
2. If `ID` is set and no match → **create** (do not fall back to summary;
   parametrized tests often share titles)
3. If `ID` is absent → search by exact `summary`
4. Update on match; otherwise create

Requires `JIRA_URL`, `JIRA_EMAIL` (or `JIRA_USER`), and `JIRA_API_TOKEN`.
Optional: `REQUESTS_CA_BUNDLE`, `JIRA_VERIFY_SSL=false`.

```bash
export JIRA_URL=https://stage-redhat.atlassian.net
export JIRA_EMAIL=<you@redhat.com>
export JIRA_API_TOKEN=<token>

dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 -o /tmp/tc.properties
import-jira-testcase /tmp/tc.properties --dry-run
import-jira-testcase /tmp/tc.properties --skip-assignee --skip-components
import-jira-testcase /tmp/tc.properties --json
```

### is-merged

Checks whether a local tip is already on an upstream remote ref (exact
ancestor, tip/branch ``git cherry``, subject hits, optional tip patch-id
scan). Used by the [is-merged](../skills/is-merged/SKILL.md) skill.

```bash
is-merged ~/git/sf-SSSD-8151 --fetch
is-merged . --ref topic --upstream upstream/main --deep --json
is-merged /path/to/worktree --no-origin
```

Exit `0` when merged, `1` when not, `2` on error.

### clone-review

Clones a GitHub PR or GitLab MR under ``~/git/@REVIEWS`` (or
``$CLONE_REVIEW_ROOT``), checks out the PR/MR head, and lists files changed
vs the target/default branch. Used by the
[review-changes](../skills/review-changes/SKILL.md) skill.

The destination path **must** contain the substring ``reviews`` (safety rail
for agent use). Existing matching clones are refreshed; unrelated directories
are not overwritten.

Requires ``gh`` (GitHub) or ``glab`` (GitLab) on ``PATH``.

```bash
clone-review https://github.com/SSSD/sssd/pull/1842
clone-review https://gitlab.cee.redhat.com/identity-management/idm-ci/-/merge_requests/2726
clone-review identity-management/idm-ci!2726 --host gitlab.cee.redhat.com --json
clone-review SSSD/sssd#1842 --name sssd-pr1842 -q
clone-review URL --root ~/git/@REVIEWS --no-refresh
```

| Flag | Purpose |
|------|---------|
| `reference` | PR/MR URL, or `owner/repo#N` / `group/proj!N` |
| `--root` | Parent dir (must contain `reviews`) |
| `--name` | Clone dirname under `--root` |
| `--platform` / `--host` | Force platform/host for shorthand |
| `--no-refresh` | Reuse clone; only recompute the diff |
| `--json` | Machine-readable result |
| `-q` | Omit file list / diffstat from text output |

Exit `0` on success, `2` on error.

### review-diff

Print the patch for a GitHub PR or GitLab MR. Uses an existing
``clone-review`` checkout when present; otherwise fetches via ``gh pr diff`` /
``glab mr diff``. Used by the
[review-changes](../skills/review-changes/SKILL.md) skill.

```bash
review-diff https://github.com/SSSD/sssd-ci-containers/pull/189
review-diff SSSD/sssd#1842 --name-only
review-diff URL --stat --json
review-diff URL --api-only
review-diff URL --clone-path ~/git/@REVIEWS/sssd-ci-containers-pr189
review-diff URL -o /tmp/pr189.patch
```

| Flag | Purpose |
|------|---------|
| `reference` | PR/MR URL, or `owner/repo#N` / `group/proj!N` |
| `--root` / `--name` | Locate an existing clone-review tree |
| `--clone-path` | Use a specific checkout (must contain `reviews`) |
| `--api-only` | Skip local clone even when present |
| `--name-only` | Changed file paths only |
| `--stat` | Diffstat summary only |
| `-o` / `--output` | Write patch to a file |
| `--json` | Machine-readable metadata (+ diff unless `--name-only`/`--stat`) |

Exit `0` on success, `2` on error.

### cleanup-review

Remove ``clone-review`` checkouts after a review. Only deletes paths under a
directory containing ``reviews``.

```bash
cleanup-review https://github.com/SSSD/sssd-ci-containers/pull/189
cleanup-review --name sssd-ci-containers-pr189
cleanup-review --all
cleanup-review URL -n --json
```

| Flag | Purpose |
|------|---------|
| `reference` | PR/MR URL or shorthand (optional with other selectors) |
| `--root` | Reviews parent directory |
| `--name` | Clone directory name under `--root` |
| `--clone-path` | Remove a specific checkout |
| `--all` | Remove every git clone under the reviews root |
| `-n` / `--dry-run` | Show what would be removed |
| `--json` | Machine-readable result |

Exit `0` on success, `2` on error.

### review-pr

Orchestrates the [review-changes](../skills/review-changes/SKILL.md) mechanical
workflow:

1. ``clone-review`` — checkout under ``~/git/@REVIEWS``
2. Lint changed ``*.py`` with ``check-python`` and Ansible ``*.yml``/``*.yaml``
   with ``check-ansible`` (paths missing at HEAD — deleted files — are skipped)
3. Optional ``cleanup-review`` when ``--cleanup`` is set

Code-quality / docstring review is still for the agent after linter output.

```bash
review-pr https://github.com/SSSD/sssd-ci-containers/pull/189
review-pr SSSD/sssd#1842 --json -q
review-pr URL --skip-lint
review-pr URL --include-diff -o /tmp/pr189.txt   # use review-diff for patch-only
review-pr URL --cleanup
review-pr URL --no-refresh
```

| Flag | Purpose |
|------|---------|
| `reference` | PR/MR URL or shorthand |
| `--root` / `--name` / `--platform` / `--host` | Passed to clone-review |
| `--no-refresh` | Reuse clone; recompute diff and lint only |
| `--skip-lint` | Clone and list changes only |
| `--include-diff` | Include full patch in output |
| `--cleanup` | Remove review clone after the run |
| `--cleanup-dry-run` | Show cleanup without deleting |
| `--json` | Machine-readable report |
| `-q` | Omit linter output bodies from text report |

Exit `0` when linters pass (or ``--skip-lint``); `1` on lint failure; `2` on
error.

### sync-twd-tests

Overlay a local test checkout onto the campaign clone next to `twd` (after
`te` init/prep git clone). Dest is inferred from `pytest-mh:` / `pytests:` /
`restraint:` in `metadata.yaml`. Excludes `.git`, `.venv`, `__pycache__`,
`.pytest_cache`. Does **not** `--delete`. Dest must be a sibling of a
validated twd (or a path under that sibling), never inside `twd`.

Used by [ticket-pre-verification](../skills/ticket-pre-verification/SKILL.md)
and [ticket-verification](../skills/ticket-verification/SKILL.md).

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
sync-twd-tests ~/git/sudoup-fork-regex_escape --json
sync-twd-tests ~/git/sudo-tests/pytest --twd . -n
sync-twd-tests /path/to/tree --twd ~/git/@TESTRUNS/<campaign> --dest ../sudo-tests
```

### brew-fetch-nvr

Download binary RPMs for an NVR from brewroot (client arch + `noarch`).
Skips `src/`, `data/`, `*debuginfo*`, `*debugsource*`. Default dest is
`<twd>/brew-rpms/`. Override the brew host only via `--base-url` or
`$BREWROOT_PACKAGES`. Optional: `REQUESTS_CA_BUNDLE` for corp TLS.

```bash
brew-fetch-nvr sudo-1.9.17-5.p2.el10_2 --twd . --json
brew-fetch-nvr sudo-1.9.17-5.p2.el10_2 --twd . --arch x86_64 --arch aarch64
brew-fetch-nvr sudo-1.9.17-5.p2.el10_2 --dest /tmp/rpms
```

### twd-rpm

Query installed NVRs or `dnf install` RPMs on twd inventory hosts via
ansible (`config/test.inventory.yaml`, become root). **`--hosts` defaults
to `client`**; pass any inventory group or host pattern (`ipa`, `dns`,
`client:ipa`, a hostname, `all`).

```bash
twd-rpm query --nvr sudo-1.9.17-5.p2.el10_2 --twd . --json
twd-rpm query --nvr sudo-1.9.17-5.p2.el10_2 --hosts ipa
twd-rpm install --twd . --json
twd-rpm install --hosts dns --rpm-dir ./brew-rpms -n
```

`query` prints `older` / `same` / `newer` / `missing` per host. Used by
[ticket-verification](../skills/ticket-verification/SKILL.md) to confirm the
compose already has Fixed in Build. `install` copies `brew-rpms/` and runs
`dnf install -y` (pre-verification path). Exit `0` on success, `1` on
ansible/dnf failure, `2` on bad NVR/args.

### te-test-summary

Pull the last pytest short summary from `twd/runner.log` (else `*junit.xml`)
plus `pytest-run.rc`. Prints the Jira draft snippet (`Complete!` / `PASSED` /
`FAILED` / totals). Does **not** post to Jira. `--upgraded NEVRA` (repeatable)
prepends the `Upgraded:` block.

```bash
te-test-summary --twd . --json
te-test-summary --twd ~/git/@TESTRUNS/<campaign> \
  --upgraded sudo-1.9.17-5.p2.el10_2.x86_64 \
  --upgraded sudo-python-plugin-1.9.17-5.p2.el10_2.x86_64
```

JSON includes `rc`, `outcome` (`passed`/`failed`/`unknown`), passed/failed
names, `snippet`, and `draft`. Exit `0` on a successful parse (even if tests
failed), `2` if there is no summary.

### run-idm-jenkins

Upload a job metadata file as a **project snippet** on `sssd/sssd-qe` and print
the Jenkins parameters for MCP `user-jenkins` / `trigger_build`
(`User-Tools/trigger-test-suite-tool`). Pass **`--trigger`** to POST
`buildWithParameters` via the Jenkins REST API when MCP is unavailable.

Requires `glab` authenticated to `gitlab.cee.redhat.com`. `--trigger` also needs
`JENKINS_USERNAME` / `JENKINS_PASSWORD` (and optional `JENKINS_URL`,
`REQUESTS_CA_BUNDLE`). Used by
[run-idm-jenkins](../skills/run-idm-jenkins/SKILL.md).

```bash
run-idm-jenkins path/to/metadata.yaml --json
run-idm-jenkins path/to/metadata.yaml --json \
  --idmci-gitrepo https://gitlab.cee.redhat.com/<user>/idm-ci.git \
  --idmci-gitbranch topic
run-idm-jenkins path/to/metadata.yaml --json \
  --idmci-checkout ~/git/idmci-fork-topic
run-idm-jenkins path/to/metadata.yaml --json \
  --idmci-replace-os 'rhel:rhel-10.2|windows:win-2025' \
  --idmci-replace-token 'SUITE:-k="test_gpo"|NAME:gpo' \
  --idmci-compose-url 'https://download.example/compose/' \
  --idmci-provider openstack
run-idm-jenkins path/to/metadata.yaml --json --envvar-file envvar.txt
run-idm-jenkins path/to/metadata.yaml --json --trigger
run-idm-jenkins path/to/metadata.yaml -n --json   # dry-run, no snippet
```

| Flag | Purpose |
|------|---------|
| `metadata` | Path to the YAML job file |
| `--idmci-gitrepo` | Custom IdM-CI git URL (`IDMCI_GITREPO`; env `IDMCI_GITREPO`) |
| `--idmci-gitbranch` | Custom IdM-CI branch (`IDMCI_GITBRANCH` → Jenkins `IDMCI_BRANCH`) |
| `--idmci-checkout` | Infer repo URL + branch from a local idm-ci clone |
| `--idmci-replace-os` | `IDMCI_REPLACE_OS` |
| `--idmci-replace-token` | `IDMCI_REPLACE_TOKEN` |
| `--idmci-compose-url` | `IDMCI_COMPOSE_URL` |
| `--idmci-provider` | `IDMCI_PROVIDER` (`openstack` / `aws` / `beaker`) |
| `--envvar-file` | Load params from artifact `envvar.txt` (skips secrets/empty) |
| `--trigger` | POST Jenkins `buildWithParameters` (MCP fallback) |
| `--jenkins-url` | Jenkins base URL (`JENKINS_URL`; default idmops-ci) |
| `--trigger-wait` | Seconds to wait for a build URL after `--trigger` (default 15; `0` skips) |
| `--param KEY=VALUE` | Extra Jenkins parameter (repeatable) |
| `--repo` | Snippet project (default `sssd/sssd-qe`) |
| `--hostname` | GitLab host (default `gitlab.cee.redhat.com`) |
| `-n` / `--dry-run` | Skip snippet create |
| `--json` | Machine-readable result |

`run-idm-jenkins --help` lists every `IDMCI_*` trigger-test-suite-tool flag
(`--idmci-is-fips`, `--idmci-brew-task-id`, `--idmci-skip-teardown`, …).

JSON includes `jenkins_job`, `jenkins_parameters` (pass this dict to
`trigger_build` unless `--trigger` was used), `snippet.raw_url` / `web_url`,
`idmci_gitrepo` / `idmci_gitbranch`, and `trigger` when the REST fallback ran.
Exit `0` on success, `2` on error.

### artifact-grep

Search Jenkins / IdM-CI artifact dumps and `twd` logs for regex patterns.
Reads gzip-compressed files transparently (plain paths and `.gz`).

```bash
artifact-grep 'Failed to resolve|Going offline' /tmp/jenkins-123
artifact-grep -i offline ~/git/@TESTRUNS/foo/twd --twd
artifact-grep -C 2 AssertionError /tmp/jenkins-123/logs
artifact-grep -F 'Domain name not found' /tmp/jenkins-123 --include '*.log'
artifact-grep 'SSSD is offline' /tmp/jenkins-123 --json
artifact-grep pattern /tmp/jenkins-123 -l
```

Exit `0` when matches are found, `1` when none, `2` on error.

### idmci-rerun-failed

Clean stale twd artifacts, optionally overlay local tests, and re-run only the
pytest cases that failed or errored in the last run.

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
idmci-rerun-failed
idmci-rerun-failed --overlay ~/git/sssd-fork-cares_gating
idmci-rerun-failed --prepare-only
idmci-rerun-failed -n --json
idmci-rerun-failed --pytest-args '-k test_0012_ad_parameters_server_unresolvable'
```

Workflow:

1. Read failed nodeids from `runner.log` or `*junit.xml` (via `te-test-summary` logic)
2. `clean-twd`
3. Optional `sync-twd-tests` when `--overlay` is set
4. Write `metadata.rerun.yaml` with appended `-k` filter (preserves existing `args:`)
5. Run `te --phase test metadata.rerun.yaml` unless `--prepare-only` / `--dry-run`

Exit `0` when `te` passes, non-zero `te` rc on test failure, `2` on setup errors.

### decompress-logs

Decompress gzip log artifacts from IdM-CI / Jenkins dumps. Handles real gzip
payloads and misnamed `.gz` files that `pull-jenkins-artifacts` already wrote as
plain text.

```bash
decompress-logs /tmp/jenkins-123/logs
decompress-logs /tmp/jenkins-123/logs --json
decompress-logs /tmp/jenkins-123/logs -n
decompress-logs /tmp/jenkins-123/logs --remove-source
```

Writes plain files next to the sources (`.log.gz` → `.log`). Use `--force` to
replace existing outputs. Exit `0` on success, `2` on error.

### bugzilla

Query [Red Hat Bugzilla](https://bugzilla.redhat.com/) via the REST API.
Authentication uses `Authorization: Bearer` with an API key from Bugzilla
Preferences → API Keys.

Environment:

| Variable | Required | Default |
|----------|----------|---------|
| `BUGZILLA_API_TOKEN` | yes | — |
| `BUGZILLA_HOST` | no | `https://bugzilla.redhat.com` |
| `BUGZILLA_USERNAME` | no | — (used by `search --mine`) |

```bash
export BUGZILLA_API_TOKEN=<api-key>
export BUGZILLA_HOST=bugzilla.redhat.com
export BUGZILLA_USERNAME=user@redhat.com

bugzilla config
bugzilla get 1002592
bugzilla get 1002592,1547234 --json
bugzilla search --component sssd --status CLOSED --summary GPO --limit 10
bugzilla search --mine --status NEW
bugzilla search --quicksearch "sssd ad forest" --json
```

`get` accepts multiple ids and comma-separated lists. `search` requires at
least one filter (`--product`, `--component`, `--status`, `--summary`,
`--assigned-to`, `--mine`, `--creator`, or `--quicksearch`). Exit `0` on success, `1` when
`search` finds no bugs, `2` on configuration or API errors.

## Tests

```bash
cd tools
python -m unittest discover -s tests -v
```
