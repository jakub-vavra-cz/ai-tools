---
name: create-idmci-metadata
description: >-
  Authors IdM-CI job metadata YAML (domains, phases, config, TOKEN_ placeholders)
  and wires test-plan jobs. Uses patterns from sssd-qe, sudo, and idm-ci metadata
  trees plus idmcidoc specs.   For local @TESTRUNS, point pytest-mh:/pytests: and container playbooks at
  ~/git/<worktree>/... so te runs tests from the worktree (no sync-twd-tests);
  Jenkins/committed metadata keeps ../sssd/... init-clone paths. Use when
  creating or editing metadata.yaml, test-plan jobs, pytest-mh/pytests/restraint
  topologies, or IDMCI_REPLACE_TOKEN options.
---

# Create IdM-CI metadata

## When this applies

User needs a **new or updated job metadata file** (`metadata/**/*.yaml`) or a **test-plan job** entry pointing at it. For **`te` invocation** (phase flags, twd), use [run-te](../run-te/SKILL.md). For **running** metadata locally (@TESTRUNS campaigns), use [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md). For **running** metadata on Jenkins (`trigger-test-suite-tool`, snippet `IDMCI_METADATA_URL`), use [run-idm-jenkins](../run-idm-jenkins/SKILL.md). For **writing SSSD system tests**, use [write-sssd-system-tests](../write-sssd-system-tests/SKILL.md).

**Local vs Jenkins test paths:** For LTE / `@TESTRUNS`, set `pytest-mh:` or `pytests:` (and optional `git:`) to `~/git/<worktree>/...` so `te` runs tests directly from the developer worktree — init may still clone `../sssd` but that clone is ignored for the test phase; no `sync-twd-tests`. **Do not** use worktree paths in committed `sssd-qe` / `sudo` metadata or Jenkins jobs — CI relies on init clones (`../sssd/...`, `git: ../sssd`).

**Authoritative docs** (read before inventing structure):

- [Creating job metadata files](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/job_files.html)
- [Domains and hosts](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/pipeline_domains_specifications.html)
- [Phases and steps](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/pipeline_phases_steps.html)
- [Metadata modifier / TOKEN_ / IDMCI_* envvars](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/metadata_modifier.html)
- Local reference clone: `~/git/idmcidoc-fork-main/` (`notebooklm/metadata-samples.txt`, `notebooklm/testplan-samples.txt`)

---

## Metadata anatomy

Every job metadata file is YAML with two required blocks:

| Block | Declares |
|-------|----------|
| **`domains`** | Multihost topology: realm/forest names, domain `type`, VM `hosts` (role, group/flavor, `os`, provider, optional `pytest_mh` / `restraint_id`) |
| **`phases`** | Ordered pipeline: conventional `init` → `provision` → `prep` → `test` → `collect` → `teardown` |

Optional top-level keys:

| Key | When |
|-----|------|
| **`config.outputs`** | `[ansible-inventory, pytest-mh]` — init generates `twd/config/pytest-mh.yaml` and inventory from `domains` |
| **`config.ansible.layout`** | Ansible group hierarchy for pytest-mh / prep playbooks (copy from an existing pytest-mh metadata) |
| Domain-level vars | e.g. `ssh_key_filename`, `admin_pw` for IPA/bootc jobs |

**Minimum init step** — every file needs:

```yaml
phases:
  - name: init
    steps:
      - playbook: init/testrunner-dir.yaml
```

Add repo checkout in the same phase (`init/sssd-upstream-pytest.yaml`, `init/sssd-tests.yaml`, `init/git-clone.yaml`, …) **before or after** `testrunner-dir.yaml` depending on the template you copy.

---

## Pick a template (do not start from scratch)

Match the **test runner** and **topology**, then copy the closest file and edit.

### By test runner

| Runner | Step keyword | Typical init playbook | Example repos |
|--------|--------------|----------------------|---------------|
| **pytest-mh** (sssd-test-framework) | `pytest-mh:` path + `args:` + `name:` | `init/sssd-upstream-pytest.yaml` | `sssd-qe-fork/metadata/pytest_mh/`, `sudo-fork-master/metadata/pytest_client_ipa_ad.yaml` |
| **pytests** (in-repo upstream pytest) | `pytests:` path + `git:` + `args:` | `init/sssd-upstream-pytest.yaml` | `sssd-qe-fork/metadata/pytest/pytest-client-ipa-ad.yaml` |
| **restraint** (beakerlib) | `restraint:` xml + `git:`; hosts need `restraint_id` | `init/sssd-tests.yaml` or `init/git-clone.yaml` | `sssd-qe-fork/metadata/restraint/`, `sudo-fork-master/metadata/upstream_singlehost.yaml` |
| **playbook-only** (infra, bootc) | only `playbook:` steps in test phase | `init/testrunner-dir.yaml` | `idmci-fork-master/metadata/infra/` |

### By topology size

| Need | Start from |
|------|------------|
| Single Linux client | `sudo-fork-master/metadata/upstream_singlehost.yaml` |
| IPA master + client | `idmci-fork-master/metadata/pytests-example-metadata.yaml` |
| IPA + AD trust | `sssd-qe-fork/metadata/pytest/pytest-client-ipa-ad.yaml` |
| Full sssd-ci-containers (client, dns, ldap, ipa, samba, ad, …) | `sssd-qe-fork/metadata/pytest_mh/pytest-mh-full-env.yaml` or `pytest-mh-noSamba.yaml` |
| Client + IPA + AD (pytest-mh, no samba) | `sudo-fork-master/metadata/pytest_client_ipa_ad.yaml` |
| AD forest (multi-domain) | `sssd-qe-fork/metadata/ad_provider/ad_forest.yaml` |
| Bootc image build | `idmci-fork-master/metadata/infra/bootc-metadata.yaml` |

Canonical minimal templates live in **`idmci-fork-master/metadata/`** (`pytests-example-metadata.yaml`, `restraint-example-metadata.yaml`, `mix-master-replica-metadata.yaml`).

---

## Repo layout conventions

### `sssd-qe-fork/metadata/`

Subdirs by suite type — mirror this when adding SSSD QE jobs:

| Directory | Contents |
|-----------|----------|
| `pytest_mh/` | pytest-mh + `config.outputs` + sssd-ci-containers prep; `TOKEN_SUITE` / `TOKEN_NAME` in test phase |
| `pytest/` | upstream `pytests:` against `../sssd`; `TOKEN_TEST_PATH` / `TOKEN_SUITE` |
| `restraint/` | beakerlib recipes; `TOKEN_RESTRAINT_PATH` |
| `ad_provider/`, `ldap_provider/`, `krb_provider/` | domain-specific restraint/pytest variants |

`test-plan/mh_jobs.yaml`, `pytest_jobs.yaml`, `bash_jobs.yaml` reference these paths.

### `sudo-fork-master/metadata/`

Two patterns only:

- `upstream_singlehost.yaml` — restraint on one `ipaclient`, `TOKEN_RESTRAINT_PATH`
- `pytest_client_ipa_ad.yaml` — pytest-mh multihost (sssd-ci-containers), same layout as sssd-qe pytest_mh

Jobs in `test-plan/jobs.yaml`; OS versions applied via qualification `IDMCI_REPLACE_OS` (see `test-plan/qualifications.yaml`).

### `idmci-fork-master/metadata/`

Upstream **reference implementations** and infra jobs — copy playbooks paths from here when unsure of valid `init/` / `prep/` names.

---

## pytest-mh metadata checklist

When using pytest-mh (SSSD/sudo system tests):

1. Set `config.outputs: [ansible-inventory, pytest-mh]` and copy `config.ansible.layout` from `pytest-mh-full-env.yaml` or `pytest_client_ipa_ad.yaml`.
2. Per host: `hostname`, `group`, `groups: [...]`, `role`, `os`, and `pytest_mh.conn` (and `config` / `artifacts` where needed).
3. **Init**: `init/testrunner-dir.yaml` + `init/sssd-upstream-pytest.yaml` with `repo` / `branch` (and `repo_loc` if not default).
4. **Provision**: `provision/mrack-up.yaml`, `provision/wait.yaml`.
5. **Prep** (typical): `redhat-base`, `repos`, `set-root-ssh-password`, `prefer-ipv4`, `win-domain-setup`, `win-get-ad-cert`, `sssd-dns`, then a **sssd-ci-containers** playbook with suite-specific `extra_vars`.
6. **Test**:

```yaml
  - name: test
    steps:
      - pytest-mh: ../sssd/src/tests/system/   # CI / Jenkins: init clone under twd
        args: "TOKEN_SUITE"
        name: "TOKEN_NAME"
```

### Local @TESTRUNS: run tests from `~/git/<worktree>` (skip sync)

For ad-hoc LTE under `~/git/@TESTRUNS/<campaign>/twd`, point the **test phase** at the developer's **git worktree** under `~/git/<worktree>` instead of the init clones (`../sssd`, `../sudo-tests`, …). `te` executes `pytest-mh:` / `pytests:` from that path directly — edit the worktree and re-run `te --phase test`; no `sync-twd-tests` overlay.

Init may still check out `../sssd` (or other repos) in the campaign workspace; **ignore those clones for the test phase** when metadata points at the worktree. Prep/container playbooks can use the same pattern.

| Step | Jenkins / committed metadata | Local @TESTRUNS only |
|------|------------------------------|---------------------|
| `pytest-mh:` | `../sssd/src/tests/system/` or `../sudo-tests/pytest/` | `~/git/sssd-fork-<topic>/src/tests/system/` |
| `pytests:` + `git:` | `pytests: TOKEN_TEST_PATH`, `git: ../sssd` | `pytests: ~/git/sssd-fork-<topic>/src/tests/...` — omit `git:` or point `git:` at the same worktree if the step needs it |
| sssd-ci-containers prep | `../sssd-ci-containers/src/ansible/playbook_vm.yml` | `~/git/cont-fork-<topic>/src/ansible/playbook_vm.yml` or `../../../cont-fork-<topic>/src/ansible/playbook_vm.yml` |

`~/git/...` and `../../../<worktree>/...` (three levels up from `twd` to `~/git`) both resolve from `twd`. Prefer `~/git/<worktree>` when the name is known.

**Jenkins / CI:** Keep `../sssd/...`, `git: ../sssd`, and init-clone paths in **committed** `sssd-qe` / `sudo` metadata and test-plan jobs. The modifier and Jenkins controller have no access to your `~/git/<worktree>`; CI runs the pushed branch from init clones only.

Example (local AD forest campaign):

```yaml
- name: prep2
  steps:
  - playbook: ~/git/cont-fork-adforest/src/ansible/playbook_vm.yml
    extra_vars:
      skip_schema: true
- name: test
  steps:
  - pytest-mh: ~/git/sssd-fork-adforest/src/tests/system/
    args: -k test_adforest --mh-topology=ad-forest
    name: adforest
```

Example (local upstream `pytests:` — worktree path, no sync):

```yaml
- name: test
  steps:
  - pytests: ~/git/sssd-fork-myfix/src/tests/integration/test_example.py
    args: -v
    ssh_transport: openssh
```

7. **Collect / teardown**: `collect/sssd-logs.yaml`, `collect/win-logs.yaml`, `teardown/fetch-logs.yaml`, `teardown/check-rpm-version.yaml`, `teardown/mrack-destroy.yaml`.

Windows AD hosts: `host_type: 'windows'`, `group: ad_root` (or `ad_subdomain` / `ad_treedomain`), `netbios`, `pytest_mh.conn` with `Administrator`. Use `rnd-ld-5-1-` style random strings for unique AD names — see [random strings](https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/random_strings_metadata.html).

---

## restraint metadata checklist

1. Client host(s) with `restraint_id: <n>` (unique per participating host).
2. **Prep** includes `prep/restraint.yaml`, often `prep/set-hostname.yaml`.
3. **Test**:

```yaml
      - restraint: TOKEN_RESTRAINT_PATH
        stop-on-error: 'False'
        git: ../sssd-qe          # or ../sudo
      - playbook: test/restraint-results.yaml
        extra_vars:
          team: sssd
```

4. For AD: add `prep/win-domain-setup.yaml`, `prep/restraint-ad-env.yaml`, `prep/sssd-add-users.yaml` as in `restraint/restraint-client-ad.yaml`.

---

## pytests (upstream) metadata checklist

Simpler topology — IPA install playbooks in prep, no `config.outputs`.

**Jenkins / committed metadata** — test path relative to init clone; `git:` required:

```yaml
  - name: test
    steps:
      - pytests: TOKEN_TEST_PATH
        git: ../sssd
        args: TOKEN_SUITE
        ssh_transport: openssh
```

**Local @TESTRUNS only** — point `pytests:` at `~/git/<worktree>/...`; init's `../sssd` clone is unused for the test phase (no `sync-twd-tests`):

```yaml
  - name: test
    steps:
      - pytests: ~/git/sssd-fork-<topic>/src/tests/some_suite
        args: TOKEN_SUITE
        ssh_transport: openssh
```

See `sssd-qe-fork/metadata/pytest/pytest-client-ipa-ad.yaml` (CI shape).

---

## TOKEN_ placeholders and jobs.yaml

Design **one metadata file, many jobs** by leaving tokens in the YAML and setting `options` in `test-plan/jobs.yaml`:

| Token in metadata | Typical job option |
|-------------------|-------------------|
| `TOKEN_SUITE`, `TOKEN_NAME` | `IDMCI_REPLACE_TOKEN: 'SUITE:--importance=high\|NAME:alltest-high'` |
| `TOKEN_RESTRAINT_PATH` | `IDMCI_REPLACE_TOKEN: 'RESTRAINT_PATH:restraint/upstream_tier1_rhel9.xml'` |
| `TOKEN_TEST_PATH` | `IDMCI_REPLACE_TOKEN: 'TEST_PATH:src/tests/some_suite'` |
| `client_os`, `rhel`, `windows` (as `os:` values) | `IDMCI_REPLACE_OS: 'rhel:rhel-9.4\|windows:win-2022'` in qualifications |
| `TOKEN_OS_MASTER` / `TOKEN_OS_CLIENT` | per-job `IDMCI_REPLACE_TOKEN` or `IDMCI_SET_OS` |

Delimiter for multiple replacements: `|` (pipe). Format: `KEY:VALUE` replaces `TOKEN_KEY`.

**sssd-qe example** (`test-plan/mh_jobs.yaml`):

```yaml
- name: pytest-mh-alltests-high
  owner: sssd-qe@redhat.com
  metadata: metadata/pytest_mh/pytest-mh-noSamba.yaml
  options:
    IDMCI_REPLACE_TOKEN: 'SUITE:--importance=high -k="not passkey and not smartcard"|NAME:alltest-high'
```

**sudo example** (`test-plan/jobs.yaml`):

```yaml
- name: upstream_tier1_pytest
  owner: jvavra@redhat.com
  metadata: metadata/pytest_client_ipa_ad.yaml
  options:
    IDMCI_REPLACE_TOKEN: 'SUITE:"--importance=critical --importance=high"|NAME:pytest_tier1'
```

Job `name`: lowercase alphanumeric and dashes only. `metadata:` path is relative to repo root.

---

## Creation workflow

Copy this checklist when authoring:

```
Task progress:
- [ ] 1. Classify runner (pytest-mh / pytests / restraint / playbook-only)
- [ ] 2. List required hosts and domain types (ipa, ad, sssd, ldap)
- [ ] 3. Copy closest metadata from table above; keep phase/playbook names
- [ ] 4. Adjust domains (hosts, os tokens, pytest_mh / restraint_id)
- [ ] 5. Adjust init repo checkout (repo URL, branch, repo_loc)
- [ ] 6. Adjust test step path and TOKEN_ placeholders (local @TESTRUNS: `~/git/<worktree>/...`, ignore init clone; Jenkins/CI: `../sssd/...` + `git: ../sssd`)
- [ ] 7. Add test-plan job(s) with IDMCI_* options if CI-scheduled
- [ ] 8. Validate YAML (sanity check)
- [ ] 9. Local smoke: copy to ~/git/@TESTRUNS/<campaign>/twd/metadata.yaml and `te --upto prep`
```

### Validate before commit

From an idm-ci checkout:

```bash
~/git/idmci-fork-master/scripts/metadata_sanity_check.py path/to/metadata.yaml
```

Optional dry-run of modifier tokens:

```bash
IDMCI_REPLACE_TOKEN='SUITE:--collect-only|NAME:dryrun' \
  ~/git/idmci-fork-master/scripts/metadata_modifier.py path/to/metadata.yaml
```

### Playbook path resolution

| Path form | Resolves to |
|-----------|-------------|
| `prep/redhat-base.yaml` | `$IDMCI/playbooks/prep/...` (built-in) |
| `../sssd-ci-containers/src/ansible/playbook_vm.yml` | Init clone sibling under `@TESTRUNS/<campaign>/` (CI default) |
| `~/git/cont-fork-<topic>/src/ansible/playbook_vm.yml` | Developer working copy (local @TESTRUNS; no sync) |
| `../../../cont-fork-<topic>/src/ansible/playbook_vm.yml` | Same fork, relative from `twd` → `~/git/<fork>/` |
| `../my-repo/playbooks/foo.yaml` | Relative to `twd` (other sibling checkouts) |
| Inline `\| multiline yaml` | Embedded playbook (debug / one-off prep) |

`pytest-mh:` / `pytests:` paths follow the same rule: `../sssd/...` (+ `git: ../sssd` for pytests) on Jenkins; `~/git/<worktree>/...` for local LTE only (init clone ignored, no sync).

Built-in playbooks are in `idmci-fork-master/playbooks/`. Prefer existing names over new playbooks.

---

## Common mistakes

- Missing `init/testrunner-dir.yaml` — no `twd/config/metadata.yaml`, SSH keys, or mrack config.
- pytest-mh without `config.outputs` — no `pytest-mh.yaml`, tests cannot connect.
- Mismatched `git:` on test step vs init checkout path (`../sssd` vs `../sudo-tests`).
- Duplicate `restraint_id` on multiple hosts.
- Forgetting `provision/wait.yaml` after `mrack-up.yaml`.
- Hard-coding pytest `-k` / importance in metadata instead of `TOKEN_SUITE` + jobs.yaml (harder to reuse).
- Using `~/git/<worktree>/...` in committed metadata or Jenkins jobs — CI cannot see local worktrees; use `../sssd/...` there. Worktree paths are for `@TESTRUNS` metadata only.
- AD host without trailing `-` on random string placeholders (`rnd-ld-5-1-`).

---

## Additional reference

For step-type attribute tables, multidomain AD `parent`/`domain_level`, bootc gating metadata, and qualification layout samples, see [reference.md](reference.md).
