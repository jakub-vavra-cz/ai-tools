# Training example: compose-ready verification

Canonical walkthrough when the nightly already ships **Fixed in Build**. Contrast with [ticket-pre-verification/examples.md](../ticket-pre-verification/examples.md) (fail-first + brew install).

**IDM:** [IDM-7486](https://redhat.atlassian.net/browse/IDM-7486) (same bug; use a `[Testing Task]:` ticket in practice)
**RHEL:** [RHEL-212546](https://redhat.atlassian.net/browse/RHEL-212546)

## RHEL ticket

| Field | Value |
|-------|--------|
| **Fixed in Build** | `sudo-1.9.17-5.p2.el10_2` |

## Metadata

Point `metadata.yaml` at a **rhel-10.2** compose/nightly that already includes `sudo-1.9.17-5.p2.el10_2` (not an older nightly used for pre-verification).

## Expected sequence

1. `te --upto prep metadata.yaml`
2. `twd-rpm query --nvr sudo-1.9.17-5.p2.el10_2 --twd . --json` → **matches** (required; stop if older)
3. `sync-twd-tests` local sudo-tests
4. `te --phase test metadata.yaml` → **PASS** on first run (e.g. `test__regex_non_canonical_path`)
5. **Draft** the Jira comment and planned updates (IDM Closed/Done, RHEL `Preliminary Testing=Pass`). **Ask the user before writing anything to Jira** — do not post, transition, or change fields without explicit confirmation.

No `brew-fetch-nvr` / `twd-rpm install` step. No expected FAIL before PASS.

If step 2 shows an **older** NVR: stop — wrong compose. Update metadata or use [ticket-pre-verification](../ticket-pre-verification/SKILL.md).

If step 4 **fails** with the correct NVR: restart `sudo`/relevant service, re-overlay, re-run. Only then suggest Fail on RHEL if the failure matches RHEL-212546.

```
Complete!

=========================== short test summary info ============================
PASSED ../sudo-tests/pytest/tests/test_misc_issues.py::test__regex_non_canonical_path (bare_client)
================ 1 passed, 116 deselected, 2 warnings in 10.04s ================
```
