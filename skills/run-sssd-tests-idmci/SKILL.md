---
name: run-sssd-tests-idmci
description: >-
  Runs SSSD and related multihost tests via IdM-CI: @TESTRUNS campaigns under
  ~/git/@TESTRUNS/<name>/twd, job metadata.yaml, and `te` (provision with --upto prep,
  test with --phase test, teardown with --phase teardown). Uses `clean-twd` on test
  re-runs only to clear stale twd artifacts; reads junit/logs for diagnosis. Also covers
  pytest-mh / sssd-test-framework and in-repo pytest when not using cloud provision.
  Use for @TESTRUNS, twd, idm-ci, metadata.yaml, mrack, clean-twd, or SSSD/sudo
  system tests.
---

# Run SSSD tests (IdM-CI)

## When this applies

User wants tests **executed** (not just suggested). Run them yourself via the Shell tool, report pass/fail, and diagnose failures. Do not mark the task done while relevant tests are still failing unless the user accepts that.

For **authoring** SSSD system tests, use [write-sssd-system-tests](../write-sssd-system-tests/SKILL.md). For **Python lint/format** after edits, use [run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md).

For **cleaning twd** before a test re-run, use the **`clean-twd`** CLI from [ai-tools/tools](../../tools/README.md) (install once: `pip install -e ~/git/ai-tools/tools`).

---

## @TESTRUNS workspaces (`~/git/@TESTRUNS`)

**System / multihost test executions live here**, not only inside the source repo checkout. Each run is driven by a **job metadata file** you create in `twd`.

**Authoritative reference:** [IdM-CI job metadata basics](https://docs-idmci.psi.redhat.com/user_docs/guide.html#_job_metadata_basics) — read this (or an existing campaign metadata) before authoring a new file. Example templates: `idm-ci/metadata/` in the [idm-ci](https://github.com/SSSD/idm-ci) repo.

### `metadata.yaml` — the entrypoint

For a **new** execution, create **`~/git/@TESTRUNS/<campaign>/twd/metadata.yaml`**. That file is what you pass to `te`; it defines the whole job.

A job metadata file has two main sections:

| Section | Purpose |
|---------|---------|
| **`domains`** | Multihost topology: VM/host names, roles (`client`, `ipa`, `ldap`, `ad`, …), OS images, optional `pytest_mh` conn/artifacts per host |
| **`phases`** | Ordered workflow: `init` → `provision` → `prep` → `test` → `collect` → `teardown` (names are conventional, not fixed) |

Optional top-level **`config`** (e.g. `outputs: [ansible-inventory, pytest-mh]`) tells init to generate `pytest-mh.yaml` and inventory from `domains`.

**Minimum init step** — every metadata file should start the `init` phase with:

```yaml
phases:
- name: init
  steps:
  - playbook: init/testrunner-dir.yaml
```

That playbook creates `twd/config/`, copies SSH keys and mrack config, and **installs your metadata as `twd/config/metadata.yaml`**. After init, treat `config/metadata.yaml` as the canonical copy; named snapshots at `twd/*.yaml` (e.g. `103metadata.yaml`, `metadata.mod.yaml`) are variants you pass to `te` when iterating.

**Test phase step types** (use one per step):

- **`pytest-mh:`** — path relative to `twd` (e.g. `../sudo-tests/pytest/`); optional `args:`, `name:`
- **`pytests:`** — upstream-style suite; often with `git: ../sssd` and `args:`
- **`playbook:`** — Ansible prep/collect/teardown from idm-ci or sibling repos

Adapt from a similar campaign under `~/git/@TESTRUNS/` or from `idm-ci/metadata/pytests-example-metadata.yaml` rather than inventing phase/playbook names.

### Layout

```
~/git/@TESTRUNS/<campaign>/
├── twd/
│   ├── metadata.yaml             # CREATE THIS — job entrypoint for `te`
│   ├── config/                   # populated by init/testrunner-dir.yaml
│   │   ├── metadata.yaml         # copy of input metadata (canonical after init)
│   │   ├── pytest-mh.yaml        # generated from domains when configured
│   │   ├── test.inventory.yaml
│   │   └── polarion.yaml
│   ├── logs/
│   ├── runner.log
│   ├── pytest-run.rc
│   └── pytests_junit.xml
├── sssd/                         # sibling checkouts (paths vary)
├── sudo-tests/
└── sssd-ci-containers/
```

- **`<campaign>`** — one directory per execution (e.g. `logsrv`, `adtier12`). Match from user context or ask.
- **`twd`** — always `cd` here before `te`. Paths in metadata are **relative to `twd`**.

### New campaign workflow

```bash
mkdir -p ~/git/@TESTRUNS/<campaign>/twd
# Write twd/metadata.yaml (domains + phases) — see idm-ci docs above
# Clone sibling test repos beside twd when metadata references ../sudo-tests, ../sssd, etc.

cd ~/git/@TESTRUNS/<campaign>/twd
te --upto prep metadata.yaml         # provision: init → allocate cloud VMs → prep SUTs
te --phase test metadata.yaml        # first test run (no clean-twd)
te --phase teardown metadata.yaml    # free cloud resources when done
te metadata.yaml                       # full job in one go (provision + test + teardown)

# Re-run tests on the same provisioned hosts:
clean-twd                            # only for re-runs — clears prior logs/junit
te --phase test metadata.yaml
```

When changing topology or prep, edit **`metadata.yaml`** (or the named file you pass to `te`), then re-provision or re-run from the appropriate phase.

### Provision the environment (cloud)

To **allocate machines in the cloud** and prepare them **without running tests yet**:

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
te --upto prep metadata.yaml
```

This runs phases through **`prep`** inclusive:

| Phase | What happens |
|-------|----------------|
| **init** | Creates `twd/config/`, copies metadata, SSH keys, mrack config |
| **provision** | Allocates VMs in OpenStack/Beaker via mrack (`provision/mrack-up.yaml`, `provision/wait.yaml`) |
| **prep** | Installs packages, configures domains, runs playbooks on live hosts |

After `--upto prep` succeeds, `config/test.inventory.yaml` and `config/pytest-mh.yaml` reflect the live topology — run **`te --phase test metadata.yaml`** (no `clean-twd` on the first run). Check `mrack.log` and `runner.log` if provision or prep fails; do not run the test phase until inventory is populated.

### Clean artifacts on test re-runs (`clean-twd`)

Use **`clean-twd` only when re-running tests** on already provisioned hosts — not before the first `te --phase test` after `--upto prep`, and not during a continuous full `te metadata.yaml` job. Skip `clean-twd` if `twd` has no prior test artifacts (no stale `runner.log`, junit, or logs from a previous test phase).

When re-running (`te --phase test`, `te --phases prep:test`, or a second test pass after fixing code), run `clean-twd` from `twd` first so old and new results are not mixed. Do not use ad-hoc `rm` when `clean-twd` is available.

**Install** (once per environment):

```bash
pip install -e ~/git/ai-tools/tools
```

**Run** from the campaign twd (default path is `.`):

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
clean-twd              # remove stale artifacts
clean-twd -n           # dry-run: list paths only
clean-twd -q           # quiet (no stdout unless error)
```

Without install, from the ai-tools checkout:

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
python -m ai_tools.clean_twd .
```

`clean-twd` removes:

- all contents under **`logs/`** (directory kept)
- **`runner.log`**, **`pytest-run.rc`**
- **`*junit.xml`** at twd root (e.g. `pytests_junit.xml`, `junit.xml`)

It validates the path looks like a twd before deleting. Exit code `1` means the directory is not a twd — fix the cwd or pass an explicit path.

**Diagnose first** — read existing logs/junit when investigating a failure. **Clean only on re-run** — run `clean-twd` before the next test attempt, not before the initial test pass.

### Free resources (teardown)

To **destroy provisioned cloud VMs** and release mrack/OpenStack resources:

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
te --phase teardown metadata.yaml
```

This runs the **teardown** phase only (typically `teardown/mrack-destroy.yaml` and related playbooks). Call it when tests are done or the campaign is abandoned — do not leave hosts running. Full `te metadata.yaml` runs teardown at the end automatically; use `--phase teardown` when you provisioned with `--upto prep` and ran tests separately.

### Run with idm-ci `te`

Orchestration is **`te`** (`idm-ci/scripts/te`). First argument is always the **metadata file path** (relative to `twd`):

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
te --upto prep metadata.yaml         # provision only (typical first step)
te --phase test metadata.yaml        # first test run (no clean-twd)
te --phase teardown metadata.yaml    # free cloud resources (mrack destroy)

# Re-run only:
clean-twd
te --phase test metadata.yaml
te --phases prep:test metadata.yaml  # re-prep and test (clean-twd before if re-running test)
te metadata.yaml                     # full job including teardown
te config/metadata.yaml              # after init, equivalent canonical path
```

The **test** phase runs `pytest-mh:` / `pytests:` steps. Extra pytest filtering goes in each step’s `args:` (e.g. `-k test_logsrvd`).

`te` writes `pytest-run.rc`, junit/HTML under `twd/`, and pytest output to `twd/logs/<name>_pytest-run.log`. When re-running pytest by hand from `twd`, use `config/pytest-mh.yaml` and mirror `te`’s flags (see `pytest_mh()` in `idm-ci/scripts/te`).

### Inspect existing results

When **diagnosing** a prior run (not starting a fresh one), check:

| File | Meaning |
|------|---------|
| `pytest-run.rc` | `0` = pass, non-zero = fail |
| `pytests_junit.xml` / `*junit.xml` | failures, skips, durations |
| `logs/pytests_pytest-run.log` | pytest + mh debug log |
| `runner.log` | which playbooks/pytest steps ran, return codes |
| `mrack.log` | provision/teardown problems |
| `config/metadata.yaml` | what actually ran (after init) |

### When to use @TESTRUNS vs in-repo pytest

| Situation | Use |
|-----------|-----|
| New multihost run, mrack/OpenStack | Create `twd/metadata.yaml`, then `te --upto prep`, then `te --phase test` |
| Re-run tests on existing hosts | `clean-twd` then `te --phase test metadata.yaml` |
| User mentions @TESTRUNS, twd, campaign, metadata | `~/git/@TESTRUNS/<campaign>/twd` |
| Local containers only (`sssd-ci-containers`, `mhc.yaml`) | in-repo / CI-style pytest (below) |
| Unit, tox, `make check` | source repo (below) |

If `twd/config/test.inventory.yaml` is empty or `runner.log` shows provision failures, do not assume `te --phase test` will work — fix metadata/provision or report the infra blocker.

---

## 1. Discover how this repo runs tests

Do **not** guess commands until you have checked the project. Prefer documented, in-repo entry points over generic defaults — **except** for provisioned multihost runs, where **`~/git/@TESTRUNS/<campaign>/twd`** and its metadata take precedence.

**In-repo (prefer this)**

| Signal | What to look for |
|--------|------------------|
| **pytest** | `pytest.ini`, `pyproject.toml` (`[tool.pytest.ini_options]`), `conftest.py`, `tests/`, `requirements.txt` next to tests |
| **pytest-mh / system** | `mhc.yaml`, `--mh-config`, `sssd-test-framework`, `pytest-mh`, readme under `pytest/` or `src/tests/system/` |
| **tox / nox** | `tox.ini`, `noxfile.py` — env names often map to unit vs integration |
| **Autotools / cmocka** | `Makefile.am` with `check_PROGRAMS`, `TESTS`, `intgcheck`; built tree under `_build/` or user build dir |
| **Standalone Makefile tests** | `Sanity/`, `Regression/`, `Library/` trees (common in sudo) with per-case `Makefile` |
| **Docs** | `README*`, `readme.rst`, `CONTRIBUTING*`, `docs/testing*` |

**CI when local docs are unclear**

- **GitHub Actions**: `.github/workflows/*.yml` — working-directory, venv setup, `pytest` args, container setup (`sssd-ci-containers`), `make check`, `tox -e …`
- **GitLab CI**: `.gitlab-ci.yml`, includes under `.gitlab/ci/` — same signals

Mirror CI’s **working directory**, **venv activation**, and **substantive pytest/make arguments** when running locally.

**Fallback (nothing configured)**

- Python tree with `tests/` or `test_*.py`: `pytest` from the directory that contains `pytest.ini` or `conftest.py`
- Autotools C project with a build dir: `make check` from the build directory
- Otherwise ask the user which suite to run

---

## 2. Choose scope

| User intent | Scope |
|-------------|--------|
| Named test or file | `pytest path/to/test.py::test_name` (or the project’s equivalent) |
| Recent code change | Smallest set that exercises the change: affected module’s tests, then broader if green |
| “Run CI tests” / pre-push | Match the CI job that covers the changed area |
| Full suite | Only when asked or after targeted runs pass and user wants full confidence |

Start **narrow**, widen on failure or when the user requests it. For new/edited tests, run at least the new/changed cases before a wider sweep.

---

## 3. Prepare the environment

1. **Working directory** — `cd` to the path CI or `pytest.ini` implies (e.g. `./pytest`, `src/tests/system`, repo root).
2. **Virtualenv** — If the project uses `.venv` or `requirements.txt` beside tests:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   Reuse an existing `.venv` when dependencies are already installed.
3. **Editable framework** — When CI installs `sssd-test-framework` from a sibling checkout or `pip install ./sssd-test-framework`, do the same before system tests.
4. **Build artifacts** — C/autotools tests need a configured build tree (`./configure && make` or an existing `_build/`). Integration tests under `src/tests/intg` often need `make intgcheck` / `intgcheck-installed` per that tree’s `Makefile.am`.
5. **System / multihost prerequisites** — pytest-mh tests need:
   - `mhc.yaml` (discover path; pass `--mh-config=./mhc.yaml` when CI does)
   - Resolvable `*.test` hostnames — CI stacks usually include **ci-dns** / dnsmasq (`sssd-ci-containers`)
   - SSH access to container hosts as configured in `mhc.yaml`

If containers or DNS are not available locally, say so clearly, run what you can (e.g. `pytest --collect-only`), and summarize what CI would run.

---

## 4. Run by test type

### Plain pytest (unit / functional)

From the discovered root:

```bash
source .venv/bin/activate   # when applicable
pytest -v path/to/tests_or_file.py
```

Respect `addopts` in `pytest.ini` / `pyproject.toml`. Add `-x` when iterating on a single failure unless the user wants the full list.

### pytest-mh / sssd-test-framework (system)

**From @TESTRUNS `twd`** (provisioned hosts) — run via `te --phase test` or, when re-running pytest only:

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
source ../sudo-tests/pytest/.venv/bin/activate   # when that venv exists
python -m pytest ../sudo-tests/pytest/ \
  --mh-config=./config/pytest-mh.yaml \
  --mh-artifacts-dir=./logs \
  -vvv path/or/args/from/metadata
```

Read the **`pytest-mh:`** / **`pytests:`** path and `args:` from the job metadata (`metadata.yaml` or `config/metadata.yaml`).

**From in-repo / CI containers** — typical pattern:

```bash
source .venv/bin/activate
pytest \
  --mh-config=./mhc.yaml \
  --mh-artifacts-dir=/tmp/mh-artifacts \
  -vvv path/to/test.py::test_case
```

Quick metadata/collection check when CI does it:

```bash
pytest --mh-config=./mhc.yaml --collect-only .
```

For Polarion-enabled trees, include `--polarion-config=…` only when CI or the user requires it.

### tox / nox

```bash
tox -e py312          # example; use env name from tox.ini or CI
nox -s tests            # when noxfile.py defines the session
```

### Autotools / cmocka

From the **build directory**:

```bash
make check
# or a subtree, e.g.:
make -C src/tests/cwrap check
```

Integration pytest under `src/tests/intg` may use fakeroot/cwrap env vars from `Makefile.am` — prefer `make intgcheck` targets over hand-rolled pytest when documented.

### Makefile sanity / regression (sudo-style)

Each case often has its own `Makefile`. Run the specific case the user cares about, or the parent target documented in the repo:

```bash
make -C Sanity/run-as
```

---

## 5. Interpret results and iterate

1. Capture **exit code**, failing test names, and the **last useful traceback** (not the entire log unless needed).
2. **Classify** failure: test bug, product bug, environment (missing container, DNS, package), or flaky infra.
3. **Fix and re-run** the same scoped command after code or test changes until green or blocked.
4. When blocked on environment, state exactly what is missing and what passed locally.

---

## 6. Report

Summarize:

- Commands run (cwd + key args)
- Pass/fail counts or `make check` result
- Failures with file::test and one-line cause
- Environment gaps (no containers, no build dir, missing venv)
- Wider suites not run yet, if any

---

## Order of operations

1. **@TESTRUNS?** — If multihost / campaign context applies: ensure `~/git/@TESTRUNS/<campaign>/twd/metadata.yaml` exists (create or edit per [job metadata basics](https://docs-idmci.psi.redhat.com/user_docs/guide.html#_job_metadata_basics)). Provision with `te --upto prep metadata.yaml` if hosts are not up. Diagnose prior runs from junit/logs first.
2. **Discover** other test entry points (in-repo, then CI).
3. **Scope** to the user’s change or named test.
4. **Prepare** — venv, build dir, `te --upto prep` (cloud provision), or local containers as required.
5. **Re-run?** — If tests already ran in this `twd`, **`clean-twd`** before the next test phase (install: `pip install -e ~/git/ai-tools/tools`). Skip on first test pass after provision.
6. **Run** the narrowest relevant command.
7. **Diagnose** failures; fix or report blockers.
8. **Widen** scope only when appropriate.
9. **Teardown** — `te --phase teardown metadata.yaml` when cloud hosts should be released.
