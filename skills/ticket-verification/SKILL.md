---
name: ticket-verification
description: >-
  Verifies an IDM "[Testing Task]: <name>" ticket against local test code when
  the Fixed in Build NVR is already in the compose: In Progress, @TESTRUNS
  campaign, confirm NVR on the client after prep, then expect PASS on the
  first te --phase test. Never update Jira (comments, fields, transitions)
  without explicit user confirmation. Use when the user asks for ticket
  verification, verify a Testing Task, or to run verification with the build
  already in the nightly/compose (not pre-verification / fail-first).
---

# Ticket verification

Start from an **IDM** Jira ticket whose summary is **`[Testing Task]: <name>`** (colon after the prefix; a space-only form is also valid) and a **local directory with test code**. Transition the ticket if needed, then create a new `@TESTRUNS` campaign.

Unlike [ticket-pre-verification](../ticket-pre-verification/SKILL.md), the **Fixed in Build** NVR **must already be present** on the client after prep (from the compose/nightlies in metadata). The **first** `te --phase test` **must PASS**. There is no fail-first unpatched run and no routine brew install step. If the client NVR is older than Fixed in Build, stop and fix the compose or metadata before testing. Training walkthrough: [examples.md](examples.md).

## Jira — do not update without asking

**Never** post comments, change fields, close tickets, set Preliminary Testing, or call `jira_update_issue` on the IDM or RHEL ticket for test results until the user has seen your draft and **explicitly confirmed** they want those changes applied.

Draft only: show the comment text and every planned transition/field change, then **wait**. Do not write to Jira because tests passed or failed — ask first, every time.

The only Jira writes allowed without that confirmation are **read** calls (`jira_get_issue`, `jira_search`, `jira_list_issue_links`, …) and transitioning the IDM ticket to **In Progress** at workflow start (§2).

Related skills (read and follow; do not duplicate):

- [ticket-pre-verification](../ticket-pre-verification/SKILL.md) — fail-first when the compose does not yet have the build; brew install path
- [jira-cli-mcp](../jira-cli-mcp/SKILL.md) — fetch ticket, apply `In Progress`
- [create-idmci-metadata](../create-idmci-metadata/SKILL.md) — author `twd/metadata.yaml`
- [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md) — campaign layout, `te`, AWS, teardown

Do not invent Jira transition names or `te` flags; those skills are authoritative.

Approved CLIs in `ai-tools/tools` (use these instead of ad-hoc `rsync` / `curl` / `ansible`):

- `sync-twd-tests` — overlay local tests onto the campaign sibling
- `twd-rpm query` — `rpm -q` vs NVR on `--hosts` (default `client`)
- `te-test-summary` — last pytest/te short summary for the Jira draft (does not post)

---

## Inputs

Require both. Ask for whichever is missing.

| Input | What it is |
|-------|------------|
| **Ticket** | IDM issue key (`IDM-1234`) **or** the `<name>` from the summary |
| **Test directory** | Absolute or workspace path to the test code to run |

Summary pattern: `[Testing Task]: <name>`.

---

## Checklist

```
Verification progress:
- [ ] Ticket resolved and summary validated
- [ ] Transitioned to In Progress (or already there)
- [ ] Campaign directory created; twd/metadata.yaml authored (compose includes Fixed in Build)
- [ ] te --upto prep
- [ ] rpm -q on client matches Fixed in Build (required — stop if older)
- [ ] Local test code synced into the campaign (unpushed WIP)
- [ ] te --phase test (expect PASS on first run)
- [ ] If FAIL: verify NVR, restart services if needed, re-run
- [ ] Draft Jira updates (PASS or confirmed Fail); apply only after user confirms
```

---

## 1. Resolve the ticket

Use MCP server **`user-jira-cli`**. Read [jira-cli-mcp](../jira-cli-mcp/SKILL.md) first.

**If the user gave a key** (`IDM-…`): `jira_get_issue` with `issue_key`.

**If the user gave a name** (or full summary): `jira_search` with JQL:

```
project = IDM AND summary ~ "\\[Testing Task\\]" AND summary ~ "<name>" ORDER BY updated DESC
```

Then `jira_get_issue` on the matching key. If several match, list them and ask which one.

**Validate** before changing anything:

- Project is **IDM** (reject other projects).
- Summary starts with **`[Testing Task]`**, optional **`:`**, then the name. Extract `<name>` after that prefix.

If validation fails, stop and tell the user why.

---

## 2. Transition to In Progress

Current status from `fields.status.name`.

| Status | Action |
|--------|--------|
| `New`, `Refinement`, `Backlog` | `jira_update_issue` with `issue_key` and `transition: "In Progress"` |
| `In Progress` | Skip transition; continue |
| Anything else (`Review`, `Closed`, …) | Stop. Report status and do not create a campaign unless the user confirms |

Do **not** call `jira_get_transitions` for this IDM path — the name is **`In Progress`** (see [jira-cli-mcp/reference.md](../jira-cli-mcp/reference.md)). If the transition fails, then fetch live transitions and retry.

Optional comment on the same update: campaign path you are about to create (if already chosen).

---

## 3. Create the campaign

Follow **New campaign workflow** in [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md).

**Campaign name:** `<issue-key>-<slug>` where `<slug>` is `<name>` lowercased, spaces/`/` to `-`, keep `[a-z0-9-]`.

```
~/git/@TESTRUNS/<campaign>/twd/metadata.yaml
```

If that campaign directory already exists, ask before overwriting `metadata.yaml`.

### Wire metadata (git clone is upstream-only)

Inspect the given path: pytest-mh (`conftest.py`, `mhc.yaml`, `sssd-test-framework`), upstream `src/tests/system`, restraint XML, or a single test file.

`mkdir -p ~/git/@TESTRUNS/<campaign>/twd`. Author **`twd/metadata.yaml`** with [create-idmci-metadata](../create-idmci-metadata/SKILL.md): copy the closest template; set the test step path **relative to `twd`** (e.g. `../sssd/src/tests/system/` or `../sudo-tests/pytest/`). Scope `args:` to the tests in that directory when a full-suite run is too broad.

**Compose must include the fix.** Pick a nightly/compose URL (or image stream) known to ship the **Fixed in Build** NVR from the split-from RHEL ticket (§4). If the user’s metadata points at an older compose, stop and ask for an updated compose before prep.

Let **init** clone test/framework repos from git as the template does. Do **not** symlink the user’s checkout into the campaign.

### Run: prep, confirm NVR, overlay local tests, test

Follow run-sssd-tests-idmci for AWS/Kerberos when `provider: aws`. Order is mandatory:

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
te --upto prep metadata.yaml
```

Resolve **Fixed in Build** from the split-from RHEL ticket (§4). On the **client**:

```bash
twd-rpm query --nvr <nvr> --twd . --json
```

| Client RPM vs Fixed in Build | Action |
|------------------------------|--------|
| **Same NVR** | Continue — overlay tests and run |
| **Older** (unpatched) | **Stop.** Compose/metadata does not have the build. Update compose URL or use [ticket-pre-verification](../ticket-pre-verification/SKILL.md) with brew install — do not proceed with verification. |
| **Newer** | Unusual. Report installed NEVRA vs Jira NVR; continue only if the user confirms. |

Then overlay and test:

```bash
sync-twd-tests "<local-test-dir>" --twd . --json
te --phase test metadata.yaml
te-test-summary --twd . --json
```

Do **not** run `te --phase test` until the overlay has landed and NVR matches Fixed in Build.

### Sync local test code (after prep, before every test run)

Overlay the **given folder** onto the campaign copy of that tree. Repeat before **every** `te --phase test` (including re-runs after `clean-twd`).

Read the `pytest-mh:` / `pytests:` / `restraint:` path from `twd/metadata.yaml`. Dest rules match [ticket-pre-verification](../ticket-pre-verification/SKILL.md) §3 (sync subsection).

```bash
sync-twd-tests "<given-folder>" --twd . --json
```

Confirm dest exists and contains the expected local files before starting the test phase.

---

## 4. Fixed in Build from the RHEL ticket

The IDM ticket is **split from** a RHEL bug. That RHEL ticket’s **Fixed in Build** is the NVR the compose must ship.

1. `jira_list_issue_links` on the IDM key. Take the link whose `relationship` is **`split from`** and `other_issue` is `RHEL-…`. Stop if missing or not RHEL.
2. `jira_get_issue` on that RHEL key. Read **`Fixed in Build`** (string NVR). Stop if empty.
3. Parse NVR with `nvr.rsplit("-", 2)` → `name`, `version`, `release`.

Use this NVR only for `twd-rpm query` confirmation — **do not** brew-fetch/install unless the user explicitly overrides verification and asks for a manual patched install (that is the pre-verification workflow).

### First-run outcome

| Result | Meaning |
|--------|---------|
| **PASS** on the cases that cover the ticket | Expected. Go to **Suggest Jira updates**. |
| **FAIL** | Investigate before treating as a product miss (next subsection). |
| Infra / setup failure | Not a valid result. Diagnose per run-sssd-tests-idmci; re-run after the environment works. |

### FAIL — investigate

Do this **on the client** before concluding the fix is bad.

1. **Correct package?** `rpm -q` / `rpm -qa` for the component vs **Fixed in Build** NVR. If the NVR is wrong, the compose was not actually patched — stop verification and fix compose/metadata (or switch to pre-verification with brew install if the user directs).
2. **Stale process?** Restart the service that loads the package (e.g. `sssd`, `httpd`, the component’s systemd unit). Re-overlay, `clean-twd`, `te --phase test`.
3. **Same bug?** Read the RHEL ticket description and reproduce steps. The failure must match that original defect, not a new crash, topology error, or infra issue.

If a missed restart was the cause and a later run **passes**, treat it as PASS.

If the NVR is correct, services were restarted as needed, and the failure is **consistent with the original RHEL bug**, go to **Suggest Jira updates** with the Fail row. If the failure is a *different* bug, stop and report; do not set Preliminary Testing.

### Suggest Jira updates (PASS, or confirmed Fail)

See **Jira — do not update without asking** above. **Do not post, transition, edit fields, or call `jira_update_issue` until the user explicitly confirms.**

1. On the client, record installed versions (`rpm -q`) — NEVRA strings.
2. Capture `te --phase test` output with `te-test-summary --twd .` (draft is `Complete!` + short test summary + PASSED/FAILED). Do not paste the entire `runner.log`.
3. Show the user a draft **and** the planned field/status changes. Ask whether to apply **all of this** to **both** keys. Wait.
4. Only after confirmation, `jira_update_issue` ([jira-cli-mcp](../jira-cli-mcp/SKILL.md)):

| Outcome | IDM `[Testing Task]` | Split-from RHEL |
|---------|----------------------|-----------------|
| **PASS** | `comment` **and** `transition: "Closed"`, `resolution: "Done"` (same call). | `comment` **and** `field_pairs: ["Preliminary Testing=Pass"]`. Do not transition RHEL. |
| **FAIL** (NVR correct, same original bug) | `comment` only. Do **not** close IDM. | `comment` **and** `field_pairs: ["Preliminary Testing=Fail"]` (option value **`Fail`**). Do not transition RHEL. |

Do **not** close IDM or set Preliminary Testing until that confirmation.

Draft shape:

```
Complete!
<te --phase test metadata.yaml short summary>
```

When brew was not used, omit an `Upgraded:` block (compose already had the NVR).

---

## Report

```markdown
# Verification — <IDM-KEY>

- **Ticket:** [<KEY>](https://redhat.atlassian.net/browse/<KEY>) — `[Testing Task]: <name>`
- **Status:** <before> → In Progress (or already In Progress)
- **RHEL:** [<RHEL-KEY>](https://redhat.atlassian.net/browse/<RHEL-KEY>) (split from) — Fixed in Build: `<nvr>`
- **RPMs on client:** <rpm list> — matches Fixed in Build (from compose)
- **Tests:** `<local directory>` → `sync-twd-tests` overlay to `<campaign dest>` after prep
- **Campaign:** `~/git/@TESTRUNS/<campaign>/twd`
- **First run:** PASS (expected), or FAIL after NVR/restart check
- **Jira (after confirm only):** comments on IDM + RHEL; PASS → IDM Closed/Done + Preliminary Testing=Pass; confirmed Fail → IDM comment only + Preliminary Testing=Fail
```
