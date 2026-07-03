# CVSS v4.0 reference (for sudo triage)

Authoritative sources (FIRST.Org):

| Resource | URL |
|----------|-----|
| Calculator | https://www.first.org/cvss/calculator/4.0 |
| Example empty Base vector in calculator | https://www.first.org/cvss/calculator/4.0#CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N |
| Specification | https://www.first.org/cvss/v4-0/specification-document |
| User Guide | https://www.first.org/cvss/v4-0/user-guide |
| Hub | https://www.first.org/cvss/ |

CVSS is an open framework for communicating vulnerability characteristics and severity. Prefer this file when suggesting severity during [triage-sudo](SKILL.md); re-check FIRST docs if metrics are disputed.

---

## What to produce in triage

Score **Base metrics only (CVSS-B)** unless the user asks for Threat / Environmental / Supplemental.

Always include:

1. Full Base **vector string**
2. Calculator URL with the vector in the `#` hash
3. Numeric score when known + **qualitative** rating
4. **Per-metric reasoning** (why that value, not alternatives)
5. Comparison to any CVSS already on the Jira ticket (often 3.1)

Do **not** write CVSS into Jira unless the user explicitly asks.

### Qualitative severity (numeric → label)

| Rating | Score |
|--------|-------|
| None | 0.0 |
| Low | 0.1 – 3.9 |
| Medium | 4.0 – 6.9 |
| High | 7.0 – 8.9 |
| Critical | 9.0 – 10.0 |

### Nomenclature

| Label | Metrics used |
|-------|----------------|
| CVSS-B | Base |
| CVSS-BT | Base + Threat |
| CVSS-BE | Base + Environmental |
| CVSS-BTE | Base + Threat + Environmental |

Assessment providers typically publish **CVSS-B**. Threat/Environmental are for consumers.

### Vector string form

```text
CVSS:4.0/AV:x/AC:x/AT:x/PR:x/UI:x/VC:x/VI:x/VA:x/SC:x/SI:x/SA:x
```

- All **Base** metrics are required, in that order.
- Optional Threat / Environmental / Supplemental may follow; omitted optional metrics = Not Defined (`X`).
- Embed in calculator: `https://www.first.org/cvss/calculator/4.0#` + vector string.

---

## Base — Exploitability

Assume perfect attacker knowledge of the vulnerability. Built-in/default defenses of the product count for Base; site-specific hardenings belong in Environmental.

**Configuration rule:** if a specific configuration is required to exploit, Base scoring **assumes that configuration is present**. Do not lower Base only because the setting is non-default. Mention rarity separately (RH product severity / operational context).

### Attack Vector (AV)

| Value | Meaning |
|-------|---------|
| **N** Network | Bound to network stack; remotely exploitable across networks |
| **A** Adjacent | Limited to logically adjacent topology (same LAN segment, Bluetooth, limited admin domain) |
| **L** Local | Local login/console/SSH, or via another user’s local interaction path |
| **P** Physical | Requires physical touch/manipulation of the device |

### Attack Complexity (AC)

Captures **evasion of security-enhancing techniques**, not “hard to find” or race luck.

| Value | Meaning |
|-------|---------|
| **L** Low | No measurable evasion; repeatable success |
| **H** High | Must bypass mitigations (e.g. ASLR/DEP) or obtain target-specific secrets |

Authentication barriers → **PR**, not AC.

### Attack Requirements (AT)

Deployment/execution conditions (races, on-path injection). **Not** “admin enabled a non-default option” (that is still assumed present for Base).

| Value | Meaning |
|-------|---------|
| **N** None | Succeeds in all/most instances of the vulnerable deployment |
| **P** Present | Needs race win, on-path position, or similar non-fully-controlled conditions |

### Privileges Required (PR)

Privileges the attacker must **already** have before the exploit.

| Value | Meaning |
|-------|---------|
| **N** None | Unauthenticated / no prior access to the vulnerable system |
| **L** Low | Basic user-level privileges / non-sensitive resources |
| **H** High | Administrative / significant control before attack |

### User Interaction (UI)

Interaction by a **human other than the attacker**.

| Value | Meaning |
|-------|---------|
| **N** None | Attacker alone can exploit |
| **P** Passive | Limited involuntary interaction (e.g. render malicious page) |
| **A** Active | Conscious targeted actions (import file, accept warning, etc.) |

---

## Base — Impact

Score only **gained** impact vs pre-exploit access. Separate:

- **Vulnerable System** — the component of interest (e.g. `sudo`, `sudo_logsrvd`)
- **Subsequent System** — impact outside that boundary; use **N** if confined

### Confidentiality / Integrity / Availability

For each of VC, VI, VA (Vulnerable) and SC, SI, SA (Subsequent):

| Value | Meaning (summary) |
|-------|-------------------|
| **H** High | Total or seriously consequential loss for that property |
| **L** Low | Partial / limited loss without direct serious consequence |
| **N** None | No loss for that property (for Subsequent: also if all impact is confined to Vulnerable System) |

Integrity = unauthorized modification of data/protection. Availability = loss of service/resource access (CPU, disk, network), not merely data confidentiality.

---

## Optional groups (summary)

Only if the user asks:

| Group | Role |
|-------|------|
| **Threat** (e.g. Exploit Maturity **E**) | Adjusts for PoC / active exploit over time |
| **Environmental** | Consumer mitigations, modified Base metrics, CIA requirements |
| **Supplemental** | Extra context; does **not** change the numeric score by itself |

---

## Sudo-oriented scoring hints

| Situation | Typical Base lean |
|-----------|-------------------|
| `sudo_logsrvd` reachable listener / AcceptMessage | `AV:N` often |
| Local `sudo` / session dir / tty / policy | `AV:L` often |
| Needs race or on-path | `AT:P` |
| Needs only low local account | `PR:L` |
| Root/daemon follows attacker symlink → chmod arbitrary file | Integrity (and maybe Availability) on Vulnerable or host filesystem — argue VC/VI/VA carefully |
| Audit log integrity only (truncated I/O logs) | Often `VI:H` or `VI:L`, `VC:N`, limited/no RCE |
| Non-default `iolog_user` / path templates | Still score Base as configured; note rarity for RH Moderate vs Important |

Compare to ticket CVSS 3.1 when present: v4 splits Scope into Subsequent impacts and adds **AT** / richer **UI**. Explain mapping, do not silently copy 3.1 letters into v4.

---

## Chat output template

```text
*CVSS v4.0 (proposed, CVSS-B):*
Vector: CVSS:4.0/AV:…/AC:…/AT:…/PR:…/UI:…/VC:…/VI:…/VA:…/SC:…/SI:…/SA:…
Calculator: https://www.first.org/cvss/calculator/4.0#CVSS:4.0/AV:…/…
Score / severity: <n.n> <None|Low|Medium|High|Critical>   # or “see calculator” if uncomputed
Reasoning:
- AV: …
- AC: …
- AT: …
- PR: …
- UI: …
- VC/VI/VA: …
- SC/SI/SA: …
vs ticket CVSS: <agree | adjust because …>
RH product severity (informal): <Low|Moderate|Important|Critical> — <one line; may differ from CVSS when config is rare>
```

Numeric score: prefer the [official calculator](https://www.first.org/cvss/calculator/4.0). If the agent cannot evaluate the formula, ship the vector + reasoning and defer the number to the calculator link.
