---
name: run-te
description: >-
  Runs IdM-CI LTE with the `te` test executor: CLI flags (--upto, --phase,
  --phases), twd layout, metadata path, phase selection, outputs, and exit
  codes. Use when invoking `te`, choosing phase flags, reprovisioning, running
  test/teardown only, or understanding what `te` writes under twd — not for
  authoring metadata (create-idmci-metadata) or full @TESTRUNS campaign workflow
  (run-sssd-tests-idmci).
---

# Run `te` (IdM-CI test executor)

## When this applies

User wants to **invoke or understand** the IdM-CI `te` script (`idm-ci/scripts/te`, installed as `te` after `pip install idm-ci`). Run commands via the Shell tool from the campaign **`twd`**.

| Need | Skill |
|------|-------|
| Full @TESTRUNS campaign (handoff, clean-twd, sync, AWS) | [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md) |
| Author `metadata.yaml` | [create-idmci-metadata](../create-idmci-metadata/SKILL.md) |
| Conceptual IdM-CI / LTE docs | [about-idmci](../about-idmci/SKILL.md) |
| Jenkins instead of local LTE | [run-idm-jenkins](../run-idm-jenkins/SKILL.md) |

**Docs:** [Getting started (LTE)](https://docs-idmci.psi.redhat.com/user_docs/guides/intro/user_getting_started.html), [Phases and steps](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/pipeline_phases_steps.html), [Artifacts and logs](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/artifacts_and_logs.html). Local clone: `~/git/idmcidoc-fork-main/`. CLI source: `~/git/idm-ci/scripts/te`.

---

## Prerequisites

1. **Working directory** — always `cd` to **`twd`** (test working directory). Relative paths in metadata (`../sssd/...`, playbooks) resolve from `twd`.
2. **Metadata argument** — positional path or URL to the job metadata YAML (e.g. `metadata.yaml`, `103_metadata.yaml`, `config/metadata.yaml` after init).
3. **IdM-CI installed** — `pip install ~/git/idm-ci` (or fork); `te` on `PATH`.
4. **Secrets** — `ANSIBLE_VAULT_PASSWORD_FILE` for encrypted idm-ci secrets (see [user_getting_started](https://docs-idmci.psi.redhat.com/user_docs/guides/intro/user_getting_started.html#handling_secrets)).
5. **Cloud auth** — before phases that provision (OpenStack/AWS), configure lab credentials per [labs/authentication](https://docs-idmci.psi.redhat.com/user_docs/guides/labs/authentication.html).

---

## CLI reference

```text
te [options] <metadata>

positional:
  metadata          Path or https:// URL to job metadata YAML

options:
  --upto PHASE      Run phases from the first through PHASE (inclusive)
  --phase PHASE     Run only that phase
  --phases SPEC     Comma list or range: phase1,phase2  or  prep:test
  --phase-timeout N Default per-phase timeout in seconds (default: 14400 = 4h)
  --dry-run         Print commands only; do not execute
  -t, --timestamp   Prepend log lines with timestamps
  --ignore-missing-phase  Exit 0 with error log if named phase is absent
```

**Default (no phase flag):** runs **all** phases in metadata order (provision → prep → test → collect → teardown).

`--upto`, `--phase`, and `--phases` are **mutually exclusive**.

### Phase selection cheat sheet

| Goal | Command |
|------|---------|
| Provision only (init + VMs + prep) | `te --upto prep metadata.yaml` |
| Test only (hosts already up) | `te --phase test metadata.yaml` |
| Teardown / destroy VMs | `te --phase teardown metadata.yaml` |
| Extra prep after `prep` | `te --phases prep2:prep4 metadata.yaml` or `te --upto prep4 metadata.yaml` |
| Re-prep then test | `te --phases prep:test metadata.yaml` |
| Full job end-to-end | `te metadata.yaml` |

**`--upto` stops at the phase name exactly** — if metadata has `prep2` after `prep`, `--upto prep` does **not** run `prep2`. Use `--phases` or `--upto prep4` for later prep phases.

**`--phases` range** — `prep:test` runs every phase from `prep` through `test` inclusive (metadata order).

---

## Typical LTE flow

```bash
cd ~/git/@TESTRUNS/<campaign>/twd

te --upto prep metadata.yaml      # init → provision → prep
te --phase test metadata.yaml     # pytest-mh / pytests / restraint steps
te --phase teardown metadata.yaml # mrack destroy when done

# Or one shot:
te metadata.yaml
```

After **init**, `config/metadata.yaml` is the canonical copy; either `metadata.yaml` or `config/metadata.yaml` may be passed if they match.

Metadata may be a **URL** — `te` downloads it to a temp file (Jenkins snippet raw URLs, etc.).

---

## What `te` executes

Metadata **`phases`** → ordered **`steps`**. Step type is determined by a single key:

| Step key | Action |
|----------|--------|
| `playbook:` | `ansible-playbook` (built-in, `../` clone, or absolute path) |
| `pytest-mh:` | `pytest` with `--mh-config=./config/pytest-mh.yaml`, junit/html under `twd` |
| `pytests:` | `run-pytests.py` (upstream-style suites) |
| `restraint:` | `run-restraint2.py` |
| `module:` | Single Ansible module |
| `command:` | Local or SSH command (`host: localhost` vs remote) |

Per-phase/step `timeout`, `stop-on-error`, and `ignore-failure` come from metadata (see [pipeline_phases_steps](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/pipeline_phases_steps.html)). Global default: `--phase-timeout` (14400s).

On step failure, `te` **stops** unless `stop-on-error: 'False'` or `ignore-failure: 'True'`.

---

## Outputs under `twd`

| Path | Meaning |
|------|---------|
| `runner.log` | Full `te` transcript (appended each run) |
| `config/metadata.yaml` | Metadata copy after init |
| `config/pytest-mh.yaml` | Generated mh config (when `config.outputs` includes `pytest-mh`) |
| `config/test.inventory.yaml` | Ansible inventory from domains |
| `pytest-run.rc` | Last pytest/restraint exit code (`0` = pass) |
| `*junit.xml`, `*report.html` | Pytest reports |
| `logs/*_pytest-run.log` | Pytest debug log per test step |
| `mrack.log` | Provision/teardown (when mrack playbooks run) |
| `polarion/` | Polarion import XML when enabled |

For a short pass/fail summary after test, use **`te-test-summary`** (see [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md)).

---

## Exit codes and debugging

- **Non-zero exit** — phase/step failed, missing phase (without `--ignore-missing-phase`), playbook not found, or timeout.
- **`--dry-run`** — always exits 0; use to inspect ansible/pytest commands.
- **Provision failures** — check `runner.log` and `mrack.log`; do not run `test` until inventory is populated.
- **Re-run pytest by hand** — mirror `pytest_mh()` in `idm-ci/scripts/te` (same `--mh-config`, `--mh-artifacts-dir`, junit paths).

---

## Related CLIs (not `te`)

These wrap or complement `te` but are separate commands — see [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md):

| CLI | Role |
|-----|------|
| `clean-twd` | Clear logs/junit before test **re-run** |
| `sync-twd-tests` | Overlay local fork onto init clone paths |
| `te-test-summary` | Parse `pytest-run.rc` / junit for short summary |
| `idmci-rerun-failed` | Re-run only failed tests via filtered metadata |

---

## More detail

- Full option tables, env vars, and doc cross-links: [reference.md](reference.md)
