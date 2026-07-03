# Training example: IDM-7486

Canonical walkthrough. Live tickets follow the same shapes.

**IDM:** [IDM-7486](https://redhat.atlassian.net/browse/IDM-7486)
**RHEL:** [RHEL-212546](https://redhat.atlassian.net/browse/RHEL-212546)

## IDM ticket

| Field | Value |
|-------|--------|
| Summary | `[Preliminary Testing Task]: Use canonicalized path if user path contains ".." ` |
| Type | Task |
| Label | `preliminary_testing_task` |
| Prefix | `[Preliminary Testing Task]:` (colon after `]`) |

`jira_list_issue_links` on `IDM-7486`:

| Field | Value |
|-------|--------|
| `type` | Work item split |
| `relationship` | `split from` (`inward`) |
| `other_issue` | `RHEL-212546` |

The RHEL bug lists this IDM ticket as **split to**.

## RHEL ticket

`jira_get_issue` on `RHEL-212546`:

| Field | Value |
|-------|--------|
| Summary | `Use canonicalized path if user path contains ".." [RHEL-10.2.z]` |
| Component | sudo |
| **Fixed in Build** | `sudo-1.9.17-5.p2.el10_2` |
| `short: true` line | `Build: sudo-1.9.17-5.p2.el10_2` |

NVR split (`rsplit("-", 2)`):

- name: `sudo`
- version: `1.9.17`
- release: `5.p2.el10_2`

## Brewroot

Directory:

`https://download-01.beak-001.prod.iad2.dc.redhat.com/brewroot/packages/sudo/1.9.17/5.p2.el10_2/`

Contains: `aarch64/`, `ppc64le/`, `s390x/`, `x86_64/`, `src/`, `data/`, `metadata.json`.

Client arch `x86_64` listing:

| RPM | Action |
|-----|--------|
| `sudo-1.9.17-5.p2.el10_2.x86_64.rpm` | install |
| `sudo-devel-1.9.17-5.p2.el10_2.x86_64.rpm` | install |
| `sudo-python-plugin-1.9.17-5.p2.el10_2.x86_64.rpm` | install |
| `sudo-debuginfo-1.9.17-5.p2.el10_2.x86_64.rpm` | skip |
| `sudo-debugsource-1.9.17-5.p2.el10_2.x86_64.rpm` | skip |
| `sudo-python-plugin-debuginfo-1.9.17-5.p2.el10_2.x86_64.rpm` | skip |

Install all non-debug RPMs on the **client** (`dnf install -y`), not only the main `sudo` package.

Completed ticket comment on IDM-7486 showed the upgrade of `sudo` and `sudo-python-plugin` to that NVR, then:

`PASSED ../sudo-tests/pytest/tests/test_misc_issues.py::test__regex_non_canonical_path (bare_client)`

A **rhel-10.2 nightly** may already have `sudo-1.9.17-5.p2.el10_2` after prep. `rpm -q sudo` on the client **before** treating a first-run PASS as a problem: if it matches Fixed in Build, PASS is expected (compose already patched). Do not call that a pre-verify failure; skip brew install.

## Expected sequence

1. Unpatched `te --phase test` → FAIL on `test__regex_non_canonical_path`.
2. `sync-twd-tests` local sudo-tests; install the three x86_64 RPMs above on `client.test`.
3. `clean-twd` + `sync-twd-tests` + `te --phase test` → PASS. Draft comment via `te-test-summary --upgraded …`.
4. **Suggest** (do not write to Jira until the user confirms) the same comment on IDM-7486 and RHEL-212546, plus:

- IDM-7486: `transition: "Closed"`, `resolution: "Done"`
- RHEL-212546: `field_pairs: ["Preliminary Testing=Pass"]`

If the patched run **fails**: check `rpm -q` vs `sudo-1.9.17-5.p2.el10_2`, restart the relevant service if the daemon could still be old, re-run. Only if the NVR is right and the failure matches the RHEL-212546 reproduce steps, **suggest** the same comment style with `Preliminary Testing=Fail` on RHEL (do not close IDM). Still wait for confirmation.

```
Upgraded:
  sudo-1.9.17-5.p2.el10_2.x86_64                 sudo-python-plugin-1.9.17-5.p2.el10_2.x86_64

Complete!

=========================== short test summary info ============================
PASSED ../sudo-tests/pytest/tests/test_misc_issues.py::test__regex_non_canonical_path (bare_client)
================ 1 passed, 116 deselected, 2 warnings in 10.04s ================
```
