---
name: ticket-pre-verification
description: >-
  Pre-verifies an IDM "[Preliminary Testing Task]: <name>" ticket against local
  test code: In Progress, @TESTRUNS campaign, fail-first without the patch, then
  install Fixed in Build RPMs from the split-from RHEL ticket onto the client.
  Use when the user asks for ticket pre-verification, preliminary testing,
  pre-verify, or to start a Preliminary Testing Task with a local test directory.
---

# Ticket pre-verification

Start from an **IDM** Jira ticket whose summary is **`[Preliminary Testing Task]: <name>`** (colon after the prefix; a space-only form is also valid) and a **local directory with test code**. Transition the ticket if needed, then create a new `@TESTRUNS` campaign.

The first test run is against whatever prep installed from repos/nightlies. **Check** `rpm -q` on the client against **Fixed in Build** — nightlies often already contain that NVR. If the patched build is already present, a first-run **PASS is expected** (not a pre-verify failure); skip brew install and treat it as the patched run. If the NVR is older, tests **must fail**, then install brew RPMs and re-run (expect PASS). A patched FAIL needs investigation (NVR, service restart) before any Jira Fail. Suggest Jira updates only after that, and **wait for confirmation** before writing. Training walkthrough: [examples.md](examples.md) ([IDM-7486](https://redhat.atlassian.net/browse/IDM-7486)).

Related skills (read and follow; do not duplicate):

- [jira-cli-mcp](../jira-cli-mcp/SKILL.md) — fetch ticket, apply `In Progress`
- [create-idmci-metadata](../create-idmci-metadata/SKILL.md) — author `twd/metadata.yaml`
- [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md) — campaign layout, `te`, AWS, teardown

Do not invent Jira transition names or `te` flags; those skills are authoritative.

Approved CLIs in `ai-tools/tools` (use these instead of ad-hoc `rsync` / `curl` / `ansible`):

- `sync-twd-tests` — overlay local tests onto the campaign sibling
- `brew-fetch-nvr` — download Fixed in Build RPMs into `twd/brew-rpms/`
- `twd-rpm query` / `twd-rpm install` — `rpm -q` vs NVR, then copy+dnf on `--hosts` (default `client`)
- `te-test-summary` — last pytest/te short summary for the Jira draft (does not post)


---

## Inputs

Require both. Ask for whichever is missing.

| Input | What it is |
|-------|------------|
| **Ticket** | IDM issue key (`IDM-1234`) **or** the `<name>` from the summary |
| **Test directory** | Absolute or workspace path to the test code to run |

Summary pattern: `[Preliminary Testing Task]: <name>` (see [IDM-7486](https://redhat.atlassian.net/browse/IDM-7486)).

---

## Checklist

```
Pre-verification progress:
- [ ] Ticket resolved and summary validated
- [ ] Transitioned to In Progress (or already there)
- [ ] Campaign directory created; twd/metadata.yaml authored
- [ ] te --upto prep
- [ ] rpm -q on client vs Fixed in Build (patch may already be in the compose)
- [ ] Local test code synced into the campaign (unpushed WIP)
- [ ] te --phase test (expect FAIL only if NVR is older than Fixed in Build)
- [ ] Confirm first-run FAIL is the product bug, not infra — or first-run PASS because patch already present
- [ ] If NVR older: install brew RPMs on client (no debuginfo/debugsource)
- [ ] te --phase test again if brew install ran (expect PASS)
- [ ] If patched FAIL: verify NVR, restart services if needed, re-run
- [ ] Draft Jira updates (PASS or confirmed Fail); apply only after user confirms
```

---

## 1. Resolve the ticket

Use MCP server **`user-jira-cli`**. Read [jira-cli-mcp](../jira-cli-mcp/SKILL.md) first.

**If the user gave a key** (`IDM-…`): `jira_get_issue` with `issue_key`.

**If the user gave a name** (or full summary): `jira_search` with JQL:

```
project = IDM AND summary ~ "\\[Preliminary Testing Task\\]" AND summary ~ "<name>" ORDER BY updated DESC
```

Then `jira_get_issue` on the matching key. If several match, list them and ask which one.

**Validate** before changing anything:

- Project is **IDM** (reject other projects).
- Summary starts with **`[Preliminary Testing Task]`**, optional **`:`**, then the name. Extract `<name>` after that prefix.

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

**Campaign name:** `<issue-key>-<slug>` where `<slug>` is `<name>` lowercased, spaces/`/` to `-`, keep `[a-z0-9-]`. Example: ticket `IDM-1234` with name `sudo logsrvd` → `IDM-1234-sudo-logsrvd`.

```
~/git/@TESTRUNS/<campaign>/twd/metadata.yaml
```

If that campaign directory already exists, ask before overwriting `metadata.yaml`.

### Wire metadata (git clone is upstream-only)

Inspect the given path: pytest-mh (`conftest.py`, `mhc.yaml`, `sssd-test-framework`), upstream `src/tests/system`, restraint XML, or a single test file.

`mkdir -p ~/git/@TESTRUNS/<campaign>/twd`. Author **`twd/metadata.yaml`** with [create-idmci-metadata](../create-idmci-metadata/SKILL.md): copy the closest template; set the test step path **relative to `twd`** (e.g. `../sssd/src/tests/system/` or `../sudo-tests/pytest/`). Scope `args:` to the tests in that directory when a full-suite run is too broad.

Let **init** clone test/framework repos from git as the template does (`init/sssd-upstream-pytest.yaml`, `init/git-clone.yaml`, …). That clone is the **pushed** tree. Do **not** symlink the user’s checkout into the campaign — init `git` with `force: yes` replaces `dest`.

Clone other siblings (`sssd-ci-containers`, …) only when the chosen metadata template requires them.

### Run: prep, then overlay local tests, then test

Follow run-sssd-tests-idmci for AWS/Kerberos when `provider: aws`. Order is mandatory:

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
te --upto prep metadata.yaml
sync-twd-tests "<local-test-dir>" --twd . --json
te --phase test metadata.yaml
te-test-summary --twd . --json
```

Do **not** run `te --phase test` (or a full `te metadata.yaml`) until the overlay has landed. Local tests are often unpushed; prep’s git clone will not contain them.

Do **not** add a patched RPM/build to prep. After prep, **check whether the compose already has it** (next subsection).

### Patched build may already be present

Resolve **Fixed in Build** from the split-from RHEL ticket (§4) as soon as prep has inventory. On the **client** (or another `--hosts` group when the package lives there):

```bash
twd-rpm query --nvr <nvr> --twd . --json
# equivalent: ansible -i config/test.inventory.yaml client -b -m shell -a "rpm -q <name>"
```

Compare the installed NEVRA to the Jira NVR (`name-version-release`). Nightlies/composes often already include that build.

| Client RPM vs Fixed in Build | First `te --phase test` | Next step |
|------------------------------|-------------------------|-----------|
| **Older** (unpatched) | **FAIL** expected | §4 brew install, then patched re-run |
| **Same NVR already installed** | **PASS** expected | Not a pre-verify failure. Skip brew install. Treat this run as the **patched PASS**. |
| Same NVR, tests **FAIL** | Unexpected | Patched FAIL — investigate (§4) |
| Older NVR, tests **PASS** | Problem | Tests do not reproduce the bug. Stop; do not treat as success. |

Do **not** treat “first run passed” as a process failure when `rpm -q` already matches Fixed in Build.

### First-run outcome (unpatched compose only)

When the client NVR is **older** than Fixed in Build:

| Result | Meaning |
|--------|---------|
| **FAIL** on the cases that cover the ticket | Expected. Continue to §4 if the traceback/assert matches the bug (not DNS, SSH, missing module, collection error). |
| **PASS** on those cases | Problem. The tests do not reproduce the issue without the patch. Stop and report. |
| Infra / setup failure | Not a valid pre-verify. Diagnose per run-sssd-tests-idmci; re-run after the environment works. |

Do not iterate to make the tests green on an unpatched first pass. Keep the hosts; go to **§4** after an expected FAIL. Teardown only when the user wants hosts released, or when the campaign is abandoned.

### Sync local test code (after prep, before every test run)

Overlay the **given folder** onto the campaign copy of that tree. Repeat this before **every** `te --phase test` (including re-runs after `clean-twd`); skip it only if the user confirms the campaign already has the intended files.

**Destination:** the campaign path that the test step will execute.

1. Read the `pytest-mh:` / `pytests:` / `restraint:` path from `twd/metadata.yaml` (or `config/metadata.yaml` after init). That path is relative to `twd`.
2. If the given folder is that test root (or a repo root whose basename matches the sibling, e.g. `sudo-tests` → `../sudo-tests`), dest is `~/git/@TESTRUNS/<campaign>/<that-relative-path>`.
3. If the given folder is a **subtree** of the test repo, dest is the same relative path under the campaign sibling (`<campaign>/<repo-basename>/<path-inside-repo>`).

Use the approved CLI (excludes `.git` / `.venv` / `__pycache__` / `.pytest_cache`; dest inferred from metadata; dest must be a twd sibling; no `--delete`):

```bash
sync-twd-tests "<given-folder>" --twd . --json
```

Do not improvise `rsync`. Overlay only (prep may have installed `.venv`/requirements in the clone). If the given path is a single file, the CLI copies that file into the matching dest path.

Confirm dest exists and contains the expected local files (e.g. the new test module) before starting the test phase.

---

## 4. Patched RPMs from the RHEL ticket (after first FAIL)

Skip this install when the client **already** has the Fixed in Build NVR (see **Patched build may already be present**). Only download/install from brewroot when `rpm -q` is older.

The IDM ticket is **split from** a RHEL bug. That RHEL ticket’s **Fixed in Build** is the NVR to install. Default target is the **client**; use `twd-rpm --hosts` when the package lives on another group (`ipa`, `dns`, …).

### RHEL link and NVR

1. `jira_list_issue_links` on the IDM key. Take the link whose `relationship` is **`split from`** (type **Work item split**) and `other_issue` is `RHEL-…`. Stop if missing or not RHEL.
2. `jira_get_issue` on that RHEL key. Read **`Fixed in Build`** (string NVR). `short: true` prints it as `Build: <nvr>`. Stop if empty.
3. Parse NVR with `nvr.rsplit("-", 2)` → `name`, `version`, `release`. Example: `sudo-1.9.17-5.p2.el10_2` → `sudo` / `1.9.17` / `5.p2.el10_2`.

### Locate RPMs on brewroot

Base (do not invent another brew host):

`https://download-01.beak-001.prod.iad2.dc.redhat.com/brewroot/packages/<name>/<version>/<release>/`

List that directory. Arch dirs are `x86_64/`, `aarch64/`, `ppc64le/`, `s390x/`, `noarch/`, plus `src/` and `data/` — skip `src/` and `data/`.

From `config/test.inventory.yaml`, take the host with `meta_role: client`. Get its arch (`uname -m` via ansible, usually `x86_64`). Collect `*.rpm` from **that arch** and **`noarch/`** (if present).

**Exclude** any RPM whose name contains `debuginfo` or `debugsource`. Keep all other binary RPMs from those dirs (subpackages included).

Download on the **testrunner** (brewroot is often unreachable from the AWS guest) into `twd/brew-rpms/`:

```bash
brew-fetch-nvr <nvr> --twd . --json
```

### Install on the client

`cd` to `twd`. Inventory: `config/test.inventory.yaml`. User is typically `ec2-user` — become root.

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
brew-fetch-nvr <nvr> --twd . --json
twd-rpm install --twd . --json
# other machines: twd-rpm install --hosts ipa --twd .
```

Equivalent ansible (client only):

```bash
ansible -i config/test.inventory.yaml client -b \
  -m copy -a "src=brew-rpms/ dest=/root/brew-rpms/"
ansible -i config/test.inventory.yaml client -b \
  -m shell -a "dnf install -y /root/brew-rpms/*.rpm"
```

Confirm `dnf` upgraded the NVR (e.g. `sudo-1.9.17-5.p2.el10_2.x86_64`). Default `--hosts client`; do not install on ipa/dns/ad unless the ticket’s package belongs there.

### Second test run (patched)

Re-overlay local tests, `clean-twd`, then `te --phase test metadata.yaml`.

| Result | Meaning |
|--------|---------|
| **PASS** on the cases that failed unpatched | Expected. Go to **Suggest Jira updates**. |
| **FAIL** | Investigate before treating as a product miss (next subsection). Do not skip to Jira Fail. |
| Infra / setup failure | Not a valid patched result. Diagnose per run-sssd-tests-idmci. |

### Patched FAIL — investigate

Do this **on the client** (`ansible -i config/test.inventory.yaml client -b`) before concluding the fix is bad.

1. **Correct package?** `rpm -q` / `rpm -qa` for the component vs **Fixed in Build** NVR (name, version, release). Compare to the RPMs copied into `/root/brew-rpms/`. If the NVR is wrong or missing, reinstall from `brew-rpms/` and re-run tests.
2. **Stale process?** Some daemons keep the old binary in memory. Restart the service that loads the package (e.g. `sssd`, `httpd`, the component’s systemd unit — whatever the RHEL ticket / test uses). Then re-overlay, `clean-twd`, `te --phase test`.
3. **Same bug?** Read the RHEL ticket description and reproduce steps. The patched failure must match that original defect (same assertion / symptom), not a new crash, topology error, or infra issue.

If a wrong RPM or a missed restart was the cause and a later run **passes**, treat it as patched PASS.

If the NVR is correct, services were restarted as needed, and the failure is **consistent with the original RHEL bug**, go to **Suggest Jira updates** with the Fail row. If the failure is a *different* bug, stop and report; do not set Preliminary Testing.

### Suggest Jira updates (patched PASS, or confirmed Fail)

**Do not post, transition, edit fields, or call `jira_update_issue` until the user explicitly confirms.**

1. On the client, record installed versions (`rpm -q`) — NEVRA strings, not brew filenames.
2. Capture `te --phase test <metadata>` output with `te-test-summary --twd .` (command line is in `--json`; draft is `Complete!` + short test summary + PASSED/FAILED). Do not paste the entire `runner.log`. Optional `--upgraded <nevra>` for the `Upgraded:` block.
3. Show the user a draft **and** the planned field/status changes. Ask whether to apply **all of this** to **both** keys. Wait. If they say no or only one ticket, follow that.
4. Only after confirmation, `jira_update_issue` ([jira-cli-mcp](../jira-cli-mcp/SKILL.md)):

| Outcome | IDM `[Preliminary Testing Task]` | Split-from RHEL |
|---------|----------------------------------|-----------------|
| Patched **PASS** | `comment` **and** `transition: "Closed"`, `resolution: "Done"` (same call). | `comment` **and** `field_pairs: ["Preliminary Testing=Pass"]`. Do not transition RHEL. |
| Patched **FAIL** (NVR correct, same original bug) | `comment` only. Do **not** close IDM. | `comment` **and** `field_pairs: ["Preliminary Testing=Fail"]` (option value **`Fail`**). Do not transition RHEL. |

Do **not** close IDM or set Preliminary Testing until that confirmation. Do not invent other RHEL workflow moves.

Example payloads after confirm — PASS:

```json
{
  "issue_key": "IDM-7486",
  "comment": "<draft>",
  "transition": "Closed",
  "resolution": "Done"
}
```

```json
{
  "issue_key": "RHEL-212546",
  "comment": "<draft>",
  "field_pairs": ["Preliminary Testing=Pass"]
}
```

FAIL (after investigation): same comments; IDM has **no** `transition`; RHEL uses `"Preliminary Testing=Fail"`.

Draft shape (from [IDM-7486](https://redhat.atlassian.net/browse/IDM-7486); use FAILED lines when Fail):

```
Upgraded:
  <nevra>  <nevra>  …

Complete!
<te --phase test metadata.yaml short summary>
```

---

## Report

```markdown
# Pre-verification — <IDM-KEY>

- **Ticket:** [<KEY>](https://redhat.atlassian.net/browse/<KEY>) — `[Preliminary Testing Task]: <name>`
- **Status:** <before> → In Progress (or already In Progress)
- **RHEL:** [<RHEL-KEY>](https://redhat.atlassian.net/browse/<RHEL-KEY>) (split from) — Fixed in Build: `<nvr>`
- **RPMs on client:** <rpm list, debuginfo/debugsource omitted>
- **Tests:** `<local directory>` → `sync-twd-tests` overlay to `<campaign dest>` after prep
- **Campaign:** `~/git/@TESTRUNS/<campaign>/twd`
- **Unpatched:** expected FAIL if client NVR is older — or skipped if Fixed in Build already installed
- **Patched:** PASS (including first run when compose already has the NVR), or FAIL after NVR/restart check
- **Jira (after confirm only):** comments on IDM + RHEL; PASS → IDM Closed/Done + Preliminary Testing=Pass; confirmed Fail → IDM comment only + Preliminary Testing=Fail
```
