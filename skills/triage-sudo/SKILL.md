---
name: triage-sudo
description: >-
  Triages RHEL sudo Vulnerability / Bug tickets against upstream sudo-project:
  scope (sudo_logsrvd / sudo_sendlog vs sudo/sudoers), whether fixed upstream,
  CVSS v4.0 severity suggestion with full reasoning, Jira comment with commit
  links, move valid sudo-affecting issues to Planning, and close-out when
  logsrvd/sendlog are not shipped. Use when the user asks to triage RHEL-
  sudo tickets, sudo vulnerabilities, EMBARGOED sudo reports, component sudo
  unfinished issues, or to close sudo flaws as not shipped.
---

# Triage RHEL sudo tickets

## Jira write policy (required)

**Read-only by default.** Present findings in chat first.

Do **not** call `jira_update_issue` (or any other write: comment, transition, labels, field edit, assignee change) unless the user **explicitly** asks in this turn — e.g. “comment on the ticket”, “add the label”, “move to Planning”, “close it”, “update Jira”.

- Triage alone ≠ permission to write.
- “Looks good” / silence after findings ≠ permission to write.
- Draft the proposed comment or close payload in chat and wait for confirmation when intent is unclear.
- Allowed without asking: `jira_get_issue`, `jira_list_mine`, `jira_search`, and other read-only tools.

## Related skills

- [jira-cli-mcp](../jira-cli-mcp/SKILL.md) — fetch/comment/transition via `user-jira-cli`
- [jira-cli-mcp/reference.md](../jira-cli-mcp/reference.md) — RHEL Closed + VEX values
- [cvss-reference.md](cvss-reference.md) — CVSS v4.0 metrics, vector form, sudo scoring hints

## Vulnerability-report statuses

Use these meanings when recommending transitions (Product Security vulnerability-report trackers):

| Status | Meaning |
|--------|---------|
| New | Not yet reviewed or correct team not yet identified |
| Planning | Engineering is reviewing, not yet disclosed upstream |
| In Progress | Disclosed to upstream |
| Release Pending | Accepted upstream, pending publication |
| Closed | Determined not a vulnerability, or published |

After local triage of a valid sudo/sudoers issue → **Planning** (still pre-upstream disclosure). Move to **In Progress** only once disclosed upstream; **Release Pending** when upstream has accepted and publication is pending.

## CVSS (Common Vulnerability Scoring System)

Use **CVSS v4.0 Base (CVSS-B)** when presenting triage severity. Read [cvss-reference.md](cvss-reference.md) for metric definitions, qualitative bands, sudo hints, and the chat template.

Quick links:

- [Calculator](https://www.first.org/cvss/calculator/4.0#CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N)
- [Specification](https://www.first.org/cvss/v4-0/specification-document)

In findings: vector + calculator URL + per-metric reasoning + vs ticket CVSS + informal RH severity. Do **not** write CVSS to Jira unless asked.

## Source trees

| Path | Use |
|------|-----|
| `~/git/sudo-project` | **Only** tree for code/commit triage |
| `sudo-*`, `sudoup-*`, `sudo-fork-*` | **Ignore** for vuln triage — tests / packaging forks, not upstream product code |

**Upstream:** [https://github.com/sudo-project/sudo.git](https://github.com/sudo-project/sudo.git)

If `~/git/sudo-project` (or `$GIT_PATH/sudo-project`) is missing, clone it first:

```bash
git clone https://github.com/sudo-project/sudo.git ~/git/sudo-project
```

Always `cd` into that tree for `git log` / `git show` / greps. Prefer `git fetch origin` before searching for recent fixes.

---

## 1. Find unfinished RHEL sudo tickets

MCP `user-jira-cli` → `jira_list_mine`:

```json
{
  "unfinished_only": true,
  "extra_jql": "project = RHEL AND component = sudo",
  "max_results": 50
}
```

Or a single key: `jira_get_issue` with `issue_key` (e.g. `RHEL-220365`).

Parse description for: flaw summary, affected files, package version (e.g. `sudo-1.9.17p2`), exploit preconditions, proposed patch.

**Embargo:** keep discussion on the tracker; do not open public issues/commits about EMBARGOED flaws.

### RHEL packages (binary + source)

Compose BaseOS trees hold sudo RPMs and source RPMs. Adjust the stream/version to match the ticket (e.g. RHEL-10.3, RHEL-9.7):

```text
http://download.eng.brq.redhat.com/rhel-10/nightly/RHEL-10/latest-RHEL-10.3/compose/BaseOS/
```

Typical layout under that URL:

- `<arch>/os/Packages/` — binary RPMs (`sudo-…`) for each shipped arch (`x86_64`, `aarch64`, `ppc64le`, `s390x`, …)
- `source/tree/Packages/` — source RPMs (`sudo-….src.rpm`)

Example for RHEL 10.3 nightly: [latest-RHEL-10.3 BaseOS](http://download.eng.brq.redhat.com/rhel-10/nightly/RHEL-10/latest-RHEL-10.3/compose/BaseOS/). Use the NVR from the ticket (or the compose `sudo` package) when comparing against upstream tags.

### Compiler flags / architecture-dependent flaws

If the report depends on **compiler flags**, **CPU arch**, **ABI**, **seccomp**, **ptrace**, **fortify**, or similar build/arch specifics: do not assume all RHEL arches match the reporter’s environment. Check **shipped** packages.

1. Download the relevant binary RPM(s) from the compose for **each shipped arch** that matters (at least the arch in the report, plus others if impact may differ).
2. Unpack **without installing** into a temp dir:

```bash
mkdir -p /tmp/sudo-rpm-check && cd /tmp/sudo-rpm-check
curl -LO '<compose>/…/Packages/sudo-<NVR>.<arch>.rpm'
mkdir -p root && rpm2cpio sudo-*.rpm | (cd root && cpio -idm)
```

3. Inspect binaries/libs under `root/` (paths like `usr/bin/sudo`, `usr/libexec/sudo/…`, `usr/lib64/sudo/…`):

```bash
# symbols / hardening / arch
file root/usr/bin/sudo
readelf -h root/usr/bin/sudo          # ELF class / machine
readelf -d root/usr/bin/sudo | head   # NEEDED, FLAGS
nm -D root/usr/bin/sudo 2>/dev/null | rg '<symbol>'
eu-readelf -s root/usr/bin/sudo 2>/dev/null | rg '<symbol>'

# presence of code paths / format strings / feature markers
strings -a root/usr/bin/sudo | rg -i '<marker|function|error string>'
```

4. For build options, also check the **src.rpm** / `%configure` flags in the spec, or `rpm -qp --scripts` / changelog only as supporting evidence — prefer what is actually linked into the binary.

5. Report per-arch conclusions in chat (e.g. symbol present on x86_64 only; feature compiled out on s390x).

---

## 2. Scope: logsrvd vs sudo itself

Decide which binary/path is in the attack surface:

| Signal | Likely scope |
|--------|----------------|
| `sudo_logsrvd`, `logsrvd/`, `AcceptMessage`, `RestartMessage`, remote listener | **logsrvd only** |
| `sudo_sendlog`, `logsrvd/sendlog.c`, client that pushes I/O logs to logsrvd | **sendlog only** |
| `sudoers`, `plugins/sudoers/`, local policy, `sudo` client, exec/ptrace/intercept | **sudo / sudoers** |
| Shared `lib/iolog/` | Check **callers** — shared code ≠ both products affected |

RHEL does **not** ship `sudo_logsrvd` or `sudo_sendlog`. If the flaw is logsrvd-only and/or sendlog-only, recommend close-as-not-present (step 5) **in chat**; do not close until the user asks. Still record upstream status for awareness.

Default `sudo_logsrvd` config uses static `iolog_dir` and `iolog_file=%{seq}`; path-escape configs are non-default (often AC:H).

Local sudoers I/O path escapes live in `plugins/sudoers/iolog_path_escapes.c` (historically `strlcpy_no_slash`). logsrvd path escapes live in `logsrvd/iolog_writer.c` — do not assume they stay in sync.

---

## 3. Check upstream for a fix

In `sudo-project`:

```bash
git fetch origin   # if network available
git log --oneline --all --grep='<keywords>' -20
git log --oneline --all -- <path> | head -40
git show <commit> --stat
```

Useful keywords: flaw title words, `path traversal`, `logsrvd`, `AcceptMessage`, `ZeroPath`, CVE id, function names from the report.

Confirm the fix is **ancestors of current `main`** and whether it is in the RHEL version cited (e.g. `SUDO_1_9_17p2` / `git merge-base --is-ancestor <fix> <tag>`).

Prefer GitHub links:

`https://github.com/sudo-project/sudo/commit/<full-sha>`

Do not confuse distinct bugs (e.g. RestartMessage `log_id` `..` vs AcceptMessage path expansion) even if both are “logsrvd path traversal”.

### Label `fixed_upstream`

When triage confirms an **upstream fix already exists** (commit on upstream main / a release that contains it), recommend adding the Jira label `fixed_upstream`.

**Ask first** (same as other writes). When applying:

1. `jira_get_issue` and read current `labels` (do not assume empty).
2. If `fixed_upstream` is already present → skip.
3. Otherwise set labels to **existing ∪ {fixed_upstream}**.  
   `jira_update_issue` / `field_pairs` `Labels=…` **replaces** the whole labels list — never pass only `fixed_upstream` or you will wipe others.

```json
{
  "issue_key": "RHEL-…",
  "field_pairs": ["Labels=existing_label_a,existing_label_b,fixed_upstream"]
}
```

Build the comma-separated value from the fetched labels plus `fixed_upstream`. Preserve order of existing labels; append `fixed_upstream` at the end. Can be combined with a comment in the same call if the user asked for both.

---

## 4. Comment findings on the ticket

**Ask first.** Show the draft comment in chat; call `jira_update_issue` only after an explicit request to post it.

MCP `jira_update_issue` with `issue_key` + `comment`. Template:

```text
Triage findings (reviewed against upstream sudo-project/sudo main):

*<one-line verdict: logsrvd-only / sendlog-only / affects sudo / not a vuln / already fixed / needs backport>*

<2–5 sentences: attack path, files, config preconditions if any>

*Upstream:* <fixed on main | not fixed | N/A>
Fix commits:
* https://github.com/sudo-project/sudo/commit/<sha> — <one-line>
* …

*RHEL:* <shipped version status; if logsrvd/sendlog-only note we do not ship them>

*CVSS v4.0 (proposed):* <vector>; <severity>; see calculator link. Full metric reasoning in chat triage (keep comment brief: vector + one-line severity).
```

---

## 5. Close when logsrvd/sendlog-only (not shipped)

When scope is **sudo_logsrvd** and/or **sudo_sendlog** only (not the sudo binary / sudoers), recommend this close-out **in chat**. Apply it only when the user explicitly asks to close:

```json
{
  "issue_key": "RHEL-…",
  "comment": "We do not ship logsrvd or sudo_sendlog in RHEL.",
  "transition": "Closed",
  "resolution": "Not a Bug",
  "vex_justification": "Component not Present"
}
```

Adjust the comment to name only the unshipped piece(s) when one of them is clearly out of scope (e.g. `We do not ship logsrvd in RHEL.`). Use exact VEX string `Component not Present` (see jira-cli reference).

---

## 6. Valid sudo-affecting bugs → Planning

When triage concludes the issue is a **valid bug that affects shipped sudo / sudoers** (not logsrvd/sendlog-only, not “not a bug”), recommend moving it to **Planning**.

**Ask first.** Apply only when the user explicitly asks to transition:

```json
{
  "issue_key": "RHEL-…",
  "transition": "Planning"
}
```

Use transition name `"Planning"` (RHEL Bug / Vulnerability workflow — see jira-cli reference and status meanings above). Skip if already in Planning or a later status (e.g. In Progress). Can combine with comment and/or `fixed_upstream` label merge in the same `jira_update_issue` call when the user asked for those updates together.

If sudo/sudoers **is** affected: do **not** close; propose Planning (+ comment / `fixed_upstream` as appropriate). Do not invent VEX without user direction.

---

## Checklist

```
- [ ] Issue fetched (description + version) — read-only OK
- [ ] Scoped: logsrvd / sendlog / sudo/sudoers (callers checked)
- [ ] Only sudo-project used for code/commits
- [ ] Upstream fix SHAs verified vs RHEL version
- [ ] If arch/compiler-dependent: download+unpack RPMs, check symbols/strings per arch
- [ ] Findings shown in chat before any Jira write
- [ ] CVSS v4.0 vector + severity suggested with per-metric reasoning ([cvss-reference.md](cvss-reference.md))
- [ ] If fixed upstream: propose label `fixed_upstream` (merge with existing labels)
- [ ] If valid sudo/sudoers impact: propose transition to Planning
- [ ] Comment / labels / transitions posted only after explicit user ask
- [ ] Close only after explicit user ask (logsrvd/sendlog-not-shipped)
```
