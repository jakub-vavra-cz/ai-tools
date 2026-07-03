---
name: ticket-verification
description: >-
  Verifies an IDM "[Testing Task]: <name>" or "[QE Task]: <name>" ticket against
  local test code when the Fixed in Build NVR is already in the compose: In
  Progress, @TESTRUNS campaign, confirm NVR on the client after prep, then
  expect PASS on the first te --phase test. On apply: set RHEL Test Coverage
  (Automated/Manual) and Test Link (upstream repo for automated runs). Never
  update Jira without explicit user confirmation. Use when the user asks for
  asks for ticket verification, verify a Testing/QE Task, or to run
  verification with the build already in the nightly/compose (not
  pre-verification / fail-first).
---

# Ticket verification

Start from an **IDM** Jira ticket whose summary is **`[Testing Task]: <name>`** or **`[QE Task]: <name>`** (colon after the prefix; a space-only form is also valid) and a **local directory with test code**. Transition the ticket if needed, then create a new `@TESTRUNS` campaign.

Unlike [ticket-pre-verification](../ticket-pre-verification/SKILL.md), the **Fixed in Build** NVR **must already be present** on the client after prep (from the compose/nightlies in metadata). The **first** `te --phase test` **must PASS**. There is no fail-first unpatched run and no routine brew install step. If the client NVR is older than Fixed in Build, stop and fix the compose or metadata before testing. Training walkthrough: [examples.md](examples.md).

## Jira — do not update without asking

**Never** post comments, change fields, close tickets, transition RHEL, or call `jira_update_issue` on the IDM or RHEL ticket for test results until the user has seen your draft and **explicitly confirmed** they want those changes applied.

Draft only: show the comment text and every planned transition/field change, then **wait**. Do not write to Jira because tests passed or failed — ask first, every time.

**Do not touch `Preliminary Testing`** on the RHEL ticket in this workflow (that field is for [ticket-pre-verification](../ticket-pre-verification/SKILL.md) only). For verification, suggest a RHEL **comment**, set **`Test Coverage`**, and on PASS a transition to **`Release Pending`**. On automated runs, also set **`Test Link`** to the upstream test repo (§ **RHEL Test Coverage / Test Link**).

The only Jira writes allowed without that confirmation are **read** calls (`jira_get_issue`, `jira_search`, `jira_list_issue_links`, …) and transitioning the IDM ticket to **In Progress** at workflow start (§2).

Related skills (read and follow; do not duplicate):

- [ticket-pre-verification](../ticket-pre-verification/SKILL.md) — fail-first when the compose does not yet have the build; brew install path
- [jira-cli-mcp](../jira-cli-mcp/SKILL.md) — fetch ticket, apply `In Progress`
- [create-idmci-metadata](../create-idmci-metadata/SKILL.md) — author `twd/metadata.yaml`
- [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md) — campaign layout, `te`, AWS, teardown
- **git-worktrees** MCP (`user-git-worktrees`) — resolve upstream repo URL from a worktree / main clone (see § **RHEL Test Coverage / Test Link**)

Do not invent Jira transition names or `te` flags; those skills are authoritative.

Approved CLIs in `ai-tools/tools` (use these instead of ad-hoc `rsync` / `curl` / `ansible`):

- `sync-twd-tests` — overlay local tests onto the campaign sibling
- `twd-rpm query` — `rpm -q` vs NVR on `--hosts` (default `client`)
- `te-test-summary` — last pytest/te short summary for the Jira draft (does not post)

---

## Inputs

| Input | What it is |
|-------|------------|
| **Ticket** | IDM issue key (`IDM-1234`) **or** the `<name>` from the summary — **required** |
| **Test directory** | Absolute or workspace path to the test code to run — **required unless manual** |

Summary pattern: `[Testing Task]: <name>` or `[QE Task]: <name>` (either prefix is valid).

### Manual verification (no automated tests)

When the user says verification is **manual** (no pytest/restraint suite):

- Do **not** require a test directory.
- Still create the campaign, author provision metadata (topology/OS from a similar campaign is fine), run `te --upto prep`, and confirm client NVR vs Fixed in Build.
- Omit or leave empty the automated `test` step; do **not** run `te --phase test` or `sync-twd-tests`.
- After NVR matches, hand the hosts to the user for manual checks. Draft Jira updates only after they report PASS/FAIL (same confirmation rule).

---

## Checklist

```
Verification progress:
- [ ] Ticket resolved and summary validated
- [ ] Transitioned to In Progress (or already there)
- [ ] Campaign directory created; twd/metadata.yaml authored (compose includes Fixed in Build)
- [ ] te --upto prep
- [ ] rpm -q on client matches Fixed in Build (required — stop if older)
- [ ] Automated path: local test code synced; te --phase test (expect PASS)
      OR manual path: skip sync/test; hand hosts to user
- [ ] If automated FAIL: verify NVR, restart services if needed, re-run
- [ ] Draft Jira updates (PASS or confirmed Fail); include RHEL Test Coverage (+ Test Link if automated)
- [ ] Apply only after user confirms
```

---

## 1. Resolve the ticket

Use MCP server **`user-jira-cli`**. Read [jira-cli-mcp](../jira-cli-mcp/SKILL.md) first.

**If the user gave a key** (`IDM-…`): `jira_get_issue` with `issue_key`.

**If the user gave a name** (or full summary): `jira_search` with JQL:

```
project = IDM AND (summary ~ "\\[Testing Task\\]" OR summary ~ "\\[QE Task\\]") AND summary ~ "<name>" ORDER BY updated DESC
```

Then `jira_get_issue` on the matching key. If several match, list them and ask which one.

**Validate** before changing anything:

- Project is **IDM** (reject other projects).
- Summary starts with **`[Testing Task]`** or **`[QE Task]`**, optional **`:`**, then the name. Extract `<name>` after that prefix.

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
| **Same NVR** | Continue — overlay tests and run (or hand off for manual checks) |
| **Older** (unpatched) | **Stop.** Compose/metadata does not have the build. Update compose URL or use [ticket-pre-verification](../ticket-pre-verification/SKILL.md) with brew install — do not proceed with verification. |
| **Newer** | **OK.** Report installed NEVRA vs Jira NVR and continue (nightlies often move past Fixed in Build). |

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

If the NVR is correct, services were restarted as needed, and the failure is **consistent with the original RHEL bug**, go to **Suggest Jira updates** with the Fail row. If the failure is a *different* bug, stop and report; do not close IDM or transition RHEL.

### RHEL Test Coverage / Test Link

When drafting or applying RHEL updates, set **`Test Coverage`** from how verification was done:

| Verification | `Test Coverage` | `Test Link` |
|--------------|-----------------|-------------|
| **Automated** (`te --phase test`, pytest/restraint) | `Automated` | upstream test repo URL (below) |
| **Manual** (user checks on hosts) | `Manual` | omit — do not set |

**`Release Pending` requires `Test Coverage`.** Include it in the same `jira_update_issue` call as the comment and transition (on PASS). Never set `Preliminary Testing` in this workflow.

#### Upstream repo URL for `Test Link` (automated only)

Resolve from the **local test directory** (or the git root that contains the tests you ran):

1. Git root: `git -C "<test-dir>" rev-parse --show-toplevel`
2. Upstream remote: `git -C "<root>" remote get-url upstream`
3. If there is no `upstream` remote on the worktree, use **git-worktrees** MCP `list_repos`: match the directory name to `worktree_prefix` / `main_clone_path`, then run step 2 on **`main_clone_path`**.
4. Normalize for Jira (HTTPS, no `.git` suffix): e.g. `git@github.com:RedHat-SP-Security/sudo-tests.git` → `https://github.com/RedHat-SP-Security/sudo-tests`

Use the **upstream** URL (product test repo), not your fork `origin` URL.

Set both fields via `field_pairs` on `jira_update_issue`:

```json
"field_pairs": [
  "Test Coverage=Automated",
  "Test Link=https://github.com/RedHat-SP-Security/sudo-tests"
]
```

Manual verification:

```json
"field_pairs": ["Test Coverage=Manual"]
```

### Suggest Jira updates (PASS, or confirmed Fail)

See **Jira — do not update without asking** above. **Do not post, transition, edit fields, or call `jira_update_issue` until the user explicitly confirms.**

1. On the client, record installed versions (`rpm -q`) — NEVRA strings.
2. Capture `te --phase test` output with `te-test-summary --twd .` (draft is `Complete!` + short test summary + PASSED/FAILED). For manual verification, draft from NVR + what was checked instead. Do not paste the entire `runner.log`.
3. Resolve RHEL **`Test Coverage`** / **`Test Link`** per § **RHEL Test Coverage / Test Link** (include both in the draft when automated).
4. Show the user a draft **and** every planned field/status change. Ask whether to apply to IDM and/or RHEL (user may want comment-only on RHEL). Wait.
5. Only after confirmation, `jira_update_issue` ([jira-cli-mcp](../jira-cli-mcp/SKILL.md)):

| Outcome | IDM `[Testing Task]` / `[QE Task]` | Split-from RHEL |
|---------|-------------------------------------|-----------------|
| **PASS** (automated) | `comment` **and** `transition: "Closed"`, `resolution: "Done"` (same call). | `comment`, `field_pairs: ["Test Coverage=Automated", "Test Link=<upstream-url>"]`, **and** `transition: "Release Pending"` (same call). Never set `Preliminary Testing`. |
| **PASS** (manual) | same IDM row | `comment`, `field_pairs: ["Test Coverage=Manual"]`, **and** `transition: "Release Pending"`. Never set `Preliminary Testing`. |
| **FAIL** (NVR correct, same original bug) | `comment` only. Do **not** close IDM. | `comment` only; still set `Test Coverage` if not already set (`Automated` or `Manual` as appropriate). Do **not** transition RHEL. Never set `Preliminary Testing`. |

Do **not** close IDM, transition RHEL to Release Pending, or change any RHEL fields until that confirmation. **Never** update `Preliminary Testing` in this skill.

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

- **Ticket:** [<KEY>](https://redhat.atlassian.net/browse/<KEY>) — `[Testing Task]: <name>` or `[QE Task]: <name>`
- **Status:** <before> → In Progress (or already In Progress)
- **RHEL:** [<RHEL-KEY>](https://redhat.atlassian.net/browse/<RHEL-KEY>) (split from) — Fixed in Build: `<nvr>`
- **RPMs on client:** <rpm list> — matches Fixed in Build (from compose)
- **Tests:** `<local directory>` → `sync-twd-tests` overlay to `<campaign dest>` after prep
- **Campaign:** `~/git/@TESTRUNS/<campaign>/twd`
- **First run:** PASS (expected), or FAIL after NVR/restart check
- **Jira (after confirm only):** comments on IDM + RHEL; PASS → IDM Closed/Done + RHEL `Test Coverage` (+ `Test Link` if automated) + `Release Pending`; confirmed Fail → comments only (+ `Test Coverage` if unset). **Never** touch `Preliminary Testing`.
```
