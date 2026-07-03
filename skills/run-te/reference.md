# `te` reference

Paths relative to `~/git/idmcidoc-fork-main/` unless noted.

## Source and install

| Item | Location |
|------|----------|
| Script | `~/git/idm-ci/scripts/te` |
| Package | `pip install ~/git/idm-ci` → `te` on PATH |
| Implementation | `idmci.te` module; step runners in `scripts/te` |

## CLI flags (complete)

| Flag | Type | Description |
|------|------|-------------|
| `metadata` | positional | Path relative to **cwd** (`twd`) or `http(s)://` URL |
| `--upto PHASE` | string | All phases from first through named phase inclusive |
| `--phase PHASE` | string | Single phase only |
| `--phases SPEC` | string | `a,b,c` or `start:end` (inclusive range in metadata order) |
| `--phase-timeout N` | int | Default seconds per phase when metadata omits `timeout` (default **14400**) |
| `--dry-run` | flag | Log commands; no subprocess execution |
| `-t`, `--timestamp` | flag | Timestamp prefix on console output |
| `--ignore-missing-phase` | flag | If `--phase` name missing: log error, exit **0** (Jenkins-style) |

Phase flags are mutually exclusive. With none set, all `phases:` from metadata run sequentially.

### `--phases` parsing

- `init,provision,prep` — three named phases
- `prep:test` — range from `prep` through `test` (inclusive)
- Mix not supported in one token; use multiple invocations

### `--upto` vs named prep phases

Metadata often defines `prep`, `prep2`, `prep3`, … `--upto prep` stops at the phase **named** `prep`. Later prep phases require `--phases prep2:prep4` or `--upto prep4`.

## twd layout (after init)

```
twd/
├── metadata.yaml              # input (also copied to config/)
├── config/
│   ├── metadata.yaml          # canonical after init
│   ├── pytest-mh.yaml         # when config.outputs includes pytest-mh
│   ├── test.inventory.yaml
│   ├── polarion.yaml
│   └── ssh/                   # keys from init
├── logs/
├── runner.log
├── pytest-run.rc
├── pytests_junit.xml          # name varies by step `name:`
└── mrack.log                  # when provision/teardown uses mrack
```

Workspace (`~/git/@TESTRUNS/<campaign>/`) holds sibling clones (`../sssd`, `../sssd-ci-containers`) **outside** `twd` so they are not uploaded as artifacts.

## Step types (metadata)

From `run_step()` in `idm-ci/scripts/te` and [pipeline_phases_steps.adoc](user_docs/guides/workflow_and_architecture/pipeline_phases_steps.adoc):

| Key | Required siblings | Notes |
|-----|-------------------|-------|
| `playbook` | `extra_vars`, `extra_args`, `inventory` optional | Resolved via `get_playbook_path()` |
| `pytest-mh` | `args`, `name` optional | Writes `pytest-run.rc`, junit, html, `logs/<name>_pytest-run.log` |
| `pytests` | `git`, `args`, `version`, `name`, `ssh_transport` optional | Uses `run-pytests.py` |
| `restraint` | `git` optional | Uses `run-restraint2.py`; writes `restraint-run.rc` |
| `module` | `arguments`, `hosts`, `extra_vars`, `extra_args`, `inventory` optional | Ansible ad hoc module |
| `command` | `host` (default localhost), `cwd`, `user` optional | Local shell or SSH |

Phase/step attributes: `timeout`, `stop-on-error` (`'False'` continues phase), `ignore-failure` (`'True'` ignores step rc).

## pytest-mh flags (as built by `te`)

When debugging manually from `twd`, align with `pytest_mh()`:

```bash
python -m pytest <test_path> \
  --mh-config=./config/pytest-mh.yaml \
  --mh-artifacts-dir=./logs \
  --junit-xml=./<name>_junit.xml \
  --html=./<name>_report.html \
  --self-contained-html \
  <args from metadata step>
```

## Environment variables (common)

See [ENVVARS.adoc](user_docs/guides/workflow_and_architecture/ENVVARS.adoc). Examples affecting `te` / pytest:

| Variable | Effect |
|----------|--------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Decrypt idm-ci vault secrets |
| `IDMCI_POLARION_PROJECT` | Polarion project (default `RHEL_IDM`) |
| `IDMCI_IS_POLARION_DRYRUN` | Add `--polarion-dry-run` to pytest |
| `IDMCI_POLARION_COMPONENT` | Polarion test run property |
| Host env from inventory | Injected into `command:` local steps via `get_hosts_envvars()` |

Metadata `loadEnv:` — source secret files before `te` in LTE ([ci_secrets.adoc](user_docs/guides/workflow_and_architecture/ci_secrets.adoc)).

## Doc map

| Topic | AsciiDoc |
|-------|----------|
| LTE intro, controller, example | `user_docs/guides/intro/user_getting_started.adoc` |
| Job metadata | `user_docs/guides/workflow_and_architecture/job_files.adoc` |
| Phases, steps, timeouts | `user_docs/guides/workflow_and_architecture/pipeline_phases_steps.adoc` |
| Playbooks | `user_docs/guides/workflow_and_architecture/playbooks.adoc` |
| Artifacts, `$twd` | `user_docs/guides/workflow_and_architecture/artifacts_and_logs.adoc` |
| Lab provision CLI examples | `user_docs/guides/labs/managing_vms.adoc` |
| Long-running timeouts | `user_docs/guides/use_case_examples/long_running_jobs.adoc` |
| Cloud authentication | `user_docs/guides/labs/authentication.adoc` |

Published HTML: `https://docs-idmci.psi.redhat.com/<path-without-.adoc>.html`
