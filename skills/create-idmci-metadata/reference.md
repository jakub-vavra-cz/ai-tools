# IdM-CI metadata — extended reference

## Step types (phase `steps`)

Each step is a dict with **one** keyword attribute naming the step type.

| Keyword | Purpose | Key fields |
|---------|---------|------------|
| `playbook:` | Ansible play on inventory or localhost | `extra_vars`, `extra_args`, `timeout`, `stop-on-error` |
| `pytest-mh:` | pytest with sssd-test-framework config | `args`, `name` (path is the value) |
| `pytests:` | `run-pytests.py` wrapper | `git`, `args`, `ssh_transport`, `version` |
| `restraint:` | beakerlib via restraint harness | `git`, `stop-on-error` |
| `command:` | shell on runner or remote host | `host`, `cwd`, `user` |
| `module:` | single ansible module (stdout visible) | `arguments`, `hosts` |

Phase-level `timeout` (seconds, default 4h). Step-level `stop-on-error: 'False'` continues phase on failure.

---

## Host `group` → VM flavor (common)

| group | Typical use |
|-------|-------------|
| `ipaserver` | IPA master/replica |
| `ipaclient` | IPA/SSSD client |
| `ad_root` | AD forest root DC |
| `ad_subdomain` | AD child domain DC |
| `ad_treedomain` | AD tree-trust DC |
| `ldap` | 389 DS |
| `medium` / `client` / `xsmall` | Generic sssd-ci-containers sizes |
| `runner` | Controller / test runner |

Override size with host `size:` (flavor from `provisioning-config.yaml`).

`provider:` `openstack` (default), `aws`, `beaker`, or `static` (fixed IP).

---

## Domain types

| type | Meaning |
|------|---------|
| `ipa` / `IPA` | FreeIPA realm |
| `ad` | Active Directory forest/domain |
| `sssd` | Logical grouping for SSSD test clients (may host IPA master role) |
| `ldap` | 389 Directory Server |

Multi-domain AD: use `parent:` on child domains and `domain_level:` (`top`, `sub1`, `tree1`) on DC hosts — see `sssd-qe-fork/metadata/ad_provider/ad_forest.yaml`.

---

## `config.ansible.layout` (pytest-mh)

The layout defines Ansible groups used by sssd-ci-containers and prep playbooks. Standard hierarchy from sssd-qe:

- `all` → `base` → `base_ground` → `services` → per-role children (`client`, `ipa`, `ldap`, `samba`, `dns`, …)
- `dns_server` children: `ipa`, `samba`, `ad_root`
- `ad` group with `ansible_become: no`, `user: Administrator`, children for AD DC roles

Do not simplify this tree unless you know the prep playbooks you use do not need the groups.

---

## Init playbooks (by project)

| Playbook | Clones |
|----------|--------|
| `init/testrunner-dir.yaml` | Sets up twd, keys, installs metadata copy |
| `init/sssd-upstream-pytest.yaml` | SSSD git (+ optional sssd-ci-containers) |
| `init/sssd-tests.yaml` | sssd-qe git |
| `init/git-clone.yaml` | Arbitrary repo (`extra_vars.url`, `branch`, `dest`) |
| `init/ipa-pytests.yaml` | ipa-pytests |

---

## Prep playbooks frequently combined

| Playbook | Role |
|----------|------|
| `prep/redhat-base.yaml` | Base RHEL config |
| `prep/repos.yaml` | Yum repos (`extra_vars` for buildroot, CRB, …) |
| `prep/set-root-ssh-password.yaml` | Root SSH for pytest-mh |
| `prep/prefer-ipv4.yaml` | IPv4 preference |
| `prep/win-domain-setup.yaml` | Promote Windows DCs, trusts |
| `prep/win-get-ad-cert.yaml` | AD CA cert for LDAPS |
| `prep/sssd-dns.yaml` | Point DNS at dns host (`dns_ip_address` from inventory) |
| `prep/install-ipa-packages.yaml` | IPA packages on master |
| `prep/ipa-server-install.yaml` | ipa-server-install |
| `prep/ipa-adtrust-install.yaml` / `prep/ipa-add-trust.yaml` | IPA–AD trust |
| `prep/restraint.yaml` | Install restraint |
| `prep/sssd-add-users.yaml` | AD test users (`extra_vars.testsuite`) |
| `../sssd-ci-containers/src/ansible/playbook_vm.yml` | Containerized LDAP/IPA/Samba/NFS/KDC |

---

## Useful `IDMCI_*` env vars (jobs / qualifications)

| Variable | Effect |
|----------|--------|
| `IDMCI_REPLACE_TOKEN` | `TOKEN_<KEY>` → value (`KEY:val\|KEY2:val2`) |
| `IDMCI_REPLACE_OS` | Replace host `os` values (`old:new\|...`) |
| `IDMCI_SET_OS` | Set `os` by host pattern / group / role |
| `IDMCI_IS_FIPS` | FIPS mode |
| `IDMCI_OPENSTACK_TENANT` | Quota tenant (often needed for Windows) |
| `IDMCI_PROVIDER` | `aws`, `beaker`, … |

Full list: `idmcidoc-fork-main/user_docs/guides/workflow_and_architecture/ENVVARS.adoc`.

---

## test-plan files

| File | Role |
|------|------|
| `test-plan/jobs.yaml` | Flat job list → metadata path + per-job options |
| `test-plan/qualifications.yaml` | Project, versions, stages, triggers, qualification-level options |
| `test-plan/mh_jobs.yaml` | sssd-qe split: pytest-mh jobs only |

Qualification `options` (e.g. `IDMCI_REPLACE_OS`) apply to all jobs in that qualification unless overridden at job level.

---

## File index (investigated repos)

### sssd-qe-fork/metadata (52 files)

| Path | Pattern |
|------|---------|
| `pytest_mh/pytest-mh-full-env.yaml` | Full multihost + samba + AD |
| `pytest_mh/pytest-mh-noSamba.yaml` | Full env without samba DC |
| `pytest_mh/pytest-mh-noAD.yaml` | No AD domain |
| `pytest_mh/pytest-mh-noSamba-img-gating.yaml` | Bootc gating image variant |
| `pytest/pytest-client-ipa-ad.yaml` | Upstream pytests, IPA+AD |
| `pytest/pytest-client-master-ad.yaml` | Master + AD variants |
| `restraint/restraint-client-ad.yaml` | Restraint + AD |
| `restraint/restraint-client.yaml` | Restraint client only |
| `ad_provider/*.yaml` | AD-specific suites |

### sudo-fork-master/metadata (2 files)

| Path | Pattern |
|------|---------|
| `upstream_singlehost.yaml` | Restraint single host |
| `pytest_client_ipa_ad.yaml` | pytest-mh IPA+LDAP+AD |

### idmci-fork-master/metadata (23 files)

| Path | Pattern |
|------|---------|
| `pytests-example-metadata.yaml` | Minimal IPA pytests |
| `restraint-example-metadata.yaml` | Restraint sample |
| `mix-master-replica-metadata.yaml` | IPA master + replica |
| `infra/bootc-metadata.yaml` | Bootc image build |
| `infra/win-*-build.yaml` | Windows image builds |

---

## Local iteration vs repo metadata

| Context | Path |
|---------|------|
| Committed job definition | `<test-repo>/metadata/<suite>.yaml` |
| Ad-hoc local run | `~/git/@TESTRUNS/<campaign>/twd/metadata.yaml` |

After `init`, canonical copy is `twd/config/metadata.yaml`. Named snapshots (`103metadata.yaml`, `metadata.mod.yaml`) are for iterating with `te -f <file>`.

---

## Docs map (idmcidoc-fork-main)

| Topic | Path under `user_docs/guides/workflow_and_architecture/` |
|-------|-----------------------------------------------------------|
| Job metadata intro | `job_files.adoc` |
| Domains / hosts | `pipeline_domains_specifications.adoc` |
| Phases / steps | `pipeline_phases_steps.adoc` |
| Test plans | `test_plan.adoc`, `creating_testplans.adoc` |
| Modifier | `metadata_modifier.adoc` |
| Sanity check | `metadata_sanity_checker.adoc` |
| Random strings | `random_strings_metadata.adoc` |
| Bootc / pytest-mh gating | `use_case_examples/bootc_user.adoc` |
| Annotated YAML samples | `notebooklm/metadata-samples.txt` |
| Annotated test-plan samples | `notebooklm/testplan-samples.txt` |
