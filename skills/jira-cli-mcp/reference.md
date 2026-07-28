# IDM / RHEL issue types and transitions

Captured from `redhat.atlassian.net` via `jira_get_transitions` / `jira-cli transitions --expand-fields` (2026-07-28).

Prefer this file over calling `jira_get_transitions` for **IDM** and **RHEL**. Re-fetch only if a transition fails, the project/type is not listed, or workflows drift.

Transitions below are **global** (`isGlobal: true`): from any current status you can apply any listed transition name. Use the transition **name** (not id) in `jira_update_issue.transition`.

---

## Common issue types

| Project | Type | Type id | Typical use |
|---------|------|---------|-------------|
| IDM | Task | `10014` | QE/eng work items, sprint tasks |
| IDM | Bug | `10016` | Defects tracked in IDM |
| IDM | Story | `10009` | User-facing work |
| IDM | Epic | `10000` | Large groupings / CTC epics |
| RHEL | Bug | `10016` | Product bugs |
| RHEL | Vulnerability | `10172` | CVE / Product Security vulns |

Other types may share the same project workflow; if unsure, fall back to `jira_get_transitions`.

---

## IDM workflow (Task, Bug, Story, Epic)

Verified on: Task (`IDM-7062`/`IDM-6823`), Bug (`IDM-7460`), Story (`IDM-7468`), Epic (`IDM-6164`).

### Transitions (any → target)

| Transition name | Id | Target status | Status id | Screen |
|-----------------|----|---------------|-----------|--------|
| New | `11` | New | `10142` | — |
| Refinement | `21` | Refinement | `10143` | — |
| Backlog | `31` | Backlog | `10013` | — |
| In Progress | `41` | In Progress | `3` | — |
| Review | `51` | Review | `10145` | — |
| Closed | `61` | Closed | `6` | yes (see below) |

### Typical paths

| Intent | `transition` |
|--------|--------------|
| Start work | `In Progress` |
| Hand off for review / QE | `Review` |
| Park for later | `Backlog` or `Refinement` |
| Finish | `Closed` (+ `resolution`) |

### Closed screen (IDM)

| Field | Required | Notes |
|-------|----------|-------|
| Resolution | **yes** | Pass `resolution` on `jira_update_issue` |
| Fix versions | no | Optional |
| Assignee | no | Optional |
| Linked Issues | no | Optional |
| Log Work | no | Optional |
| Start date | no | Optional |

No VEX Justification on IDM Closed.

### Resolutions (Closed — shared allow-list)

`Done`, `Won't Do`, `Cannot Reproduce`, `Can't Do`, `Duplicate`, `Not a Bug`, `Done-Errata`, `MirrorOrphan`, `Obsolete`, `Test Pending`, `Declined`

**Common defaults:** completed work → `Done`; not a defect → `Not a Bug`.

---

## RHEL workflow (Bug, Vulnerability)

Verified on: Bug (`RHEL-217993`), Vulnerability (`RHEL-188797` / `RHEL-217423`).

### Transitions (any → target)

| Transition name | Id | Target status | Status id | Screen |
|-----------------|----|---------------|-----------|--------|
| New | `11` | New | `10142` | — |
| Planning | `81` | Planning | `10149` | — |
| Refinement | `121` | Refinement | `10143` | — |
| In Progress | `111` | In Progress | `3` | — |
| Integration | `41` | Integration | `10435` | — |
| Release Pending | `101` | Release Pending | `10158` | — |
| Closed | `61` | Closed | `6` | yes (see below) |

Note: RHEL **In Progress** transition id is `111` (not `41`). Prefer the **name** `"In Progress"` anyway. Id `41` is **Integration**.

RHEL has **no** `Review` or `Backlog` transition in this workflow (unlike IDM).

### Typical paths

| Intent | `transition` |
|--------|--------------|
| Start engineering | `In Progress` |
| In compose / nightly | `Integration` |
| Fix done, awaiting release | `Release Pending` |
| Close (wontfix / not shipped / duplicate) | `Closed` (+ `resolution`, and VEX when applicable) |

### Closed screen (RHEL Bug)

| Field | Required | Notes |
|-------|----------|-------|
| Resolution | **yes** | Pass `resolution` |
| Linked Issues | no | Optional |

### Closed screen (RHEL Vulnerability)

Same as Bug, plus:

| Field | Required | Notes |
|-------|----------|-------|
| VEX Justification | no | Pass `vex_justification` when closing as not applicable / not present |

### Resolutions (Closed — same allow-list as IDM)

`Done`, `Won't Do`, `Cannot Reproduce`, `Can't Do`, `Duplicate`, `Not a Bug`, `Done-Errata`, `MirrorOrphan`, `Obsolete`, `Test Pending`, `Declined`

**Common defaults for Product Security close-outs:** `Not a Bug` (component not shipped / not applicable).

### VEX Justification options (Vulnerability Closed)

| Option value (use as `vex_justification`) |
|-------------------------------------------|
| `Component not Present` |
| `Inline Mitigations already Exist` |
| `Vulnerable Code cannot be Controlled by Adversary` |
| `Vulnerable Code not in Execute Path` |
| `Vulnerable Code not Present` |

---

## Quick recipes

**IDM → Review with MR**

```json
{
  "issue_key": "IDM-6823",
  "comment": "https://gitlab.cee.redhat.com/.../merge_requests/2718",
  "transition": "Review"
}
```

**IDM → Closed (Done)**

```json
{
  "issue_key": "IDM-7305",
  "transition": "Closed",
  "resolution": "Done"
}
```

**RHEL Vulnerability → Closed (not shipped)**

```json
{
  "issue_key": "RHEL-217423",
  "comment": "Only logsrvd is affected; not packaged for RHEL.",
  "transition": "Closed",
  "resolution": "Not a Bug",
  "vex_justification": "Component not Present"
}
```

---

## Refresh

```bash
jira-cli transitions IDM-6823 --expand-fields
jira-cli transitions RHEL-217423 --expand-fields
jira-cli transitions RHEL-217993 --expand-fields
```

Or MCP `jira_get_transitions` with `issue_key` (and expand fields via CLI if the MCP tool omits them). Update this file when names/ids change.
