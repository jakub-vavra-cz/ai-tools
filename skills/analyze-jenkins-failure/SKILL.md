---
name: analyze-jenkins-failure
description: >-
  Analyzes failed IdM-CI / SSSD Jenkins jobs from a job URL: fetches Jenkins
  console output, extracts RD_JR_ARTIFACTS_URL, downloads diagnostic logs and
  metadata.mod.yaml from the artifact server, diagnoses the failure, and outlines
  local reproduction via @TESTRUNS and `te`. Use when the user pastes a Jenkins
  build link, asks why a CI job failed, or wants to reproduce an IdM-CI test run.
---

# Analyze Jenkins job failure

## When this applies

User provides a **Jenkins job/build URL** (or asks to debug a failed IdM-CI / SSSD / sudo multihost job). Fetch console + artifacts, diagnose, and — when feasible — set up local reproduction.

Related skills:

- [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md) — run `te`, read twd logs, `clean-twd`
- [create-idmci-metadata](../create-idmci-metadata/SKILL.md) — edit metadata when reproduction needs tweaks

---

## Input

A Jenkins **build URL**, e.g.:

`https://jenkins-csb-idmops-ci.dno.corp.redhat.com/job/SSSD/job/tier1/123/`

Normalize: ensure trailing `/`, strip fragments (`#…`) and query strings unless needed.

---

## 1. Parse the build URL

From the URL extract:

| Part | Rule |
|------|------|
| **Base** | Scheme + host, e.g. `https://jenkins-csb-idmops-ci.dno.corp.redhat.com` |
| **Build number** | Last path segment before trailing `/` (must be numeric) |
| **Job path** | Everything between first `/job/` and the build number, with `/job/` segments collapsed to `/` for API helpers |

Console log endpoint:

```text
{BUILD_URL}consoleText
```

Optional: use MCP **`user-jenkins`** / **`get_build_status`** with `job_name` = folder path (e.g. `SSSD/tier1`) and `build_number` for result/duration — but **console text is not in MCP**; always fetch via HTTP (below).

---

## 2. Fetch Jenkins console output

Prefer the **`pull-jenkins-artifacts`** CLI from [ai-tools/tools](../../tools/README.md) (install: `pip install -e ~/git/ai-tools/tools`):

```bash
export JENKINS_USERNAME=… JENKINS_PASSWORD=…   # API token
export REQUESTS_CA_BUNDLE=~/git/certs/combined-certifi.pem  # when needed

pull-jenkins-artifacts 'https://jenkins…/job/…/123/' -o /tmp/jenkins-123
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --url-only
```

Without install: `python -m ai_tools.jenkins_artifacts …`

Manual `curl` fallback — use credentials from the environment (Cursor `jenkins` MCP config sets these):

| Variable | Purpose |
|----------|---------|
| `JENKINS_URL` | Default Jenkins host when URL host matches |
| `JENKINS_USERNAME` / `JENKINS_PASSWORD` | Basic auth (API token as password when `JENKINS_USE_API_TOKEN=true`) |
| `REQUESTS_CA_BUNDLE` or `SSL_CERT_DIR` | Corp CA for `curl` |

```bash
BUILD_URL='https://…/job/…/123/'
CONSOLE_URL="${BUILD_URL}consoleText"

curl -sS -u "${JENKINS_USERNAME}:${JENKINS_PASSWORD}" \
  ${REQUESTS_CA_BUNDLE:+--cacert "$REQUESTS_CA_BUNDLE"} \
  "$CONSOLE_URL" -o /tmp/jenkins-console-123.txt
```

If `curl` fails (401/403), report auth/CA issue — do not guess artifact URLs.

Scan the console for:

- **Failed stage** (`Stage "test" skipped`, `ERROR:`, `Finished: FAILURE`)
- **`TE_PHASE_*`** env lines — last failed phase (`init`, `provision`, `prep`, `test`, …)
- **`IDMCI_*`** params (metadata URL, SUT version, job name, skip flags)
- **Exception/traceback** near the end

---

## 3. Extract `RD_JR_ARTIFACTS_URL`

IdM-CI Jenkins jobs print Release Dashboard env vars during `rdJob` (`printenv | sort | grep RD_`). The artifacts base URL is:

```text
RD_JR_ARTIFACTS_URL=https://idm-artifacts.psi.redhat.com/{path}/
```

Extract from console (try in order):

```bash
# Primary — last RD_JR_ARTIFACTS_URL wins (results stage re-prints)
grep -oE 'RD_JR_ARTIFACTS_URL=https?://[^[:space:]]+' /tmp/jenkins-console-123.txt \
  | tail -1 | cut -d= -f2-

# Fallback — error xunit / RunTe messages
grep -oE 'Artifacts url: https?://[^[:space:]]+' /tmp/jenkins-console-123.txt \
  | tail -1 | sed 's/Artifacts url: //'
```

Trailing `/` on the URL is required when appending relative paths.

If neither pattern appears, the job may have failed before `rdJob`, or `IDMCI_SKIP_ARTIFACT_SERVER` was set. Check whether the **artifact-server** stage ran; search console for `Upload the artifacts` or `idm-artifacts upload`.

---

## 4. Download artifacts from the artifact server

`pull-jenkins-artifacts` downloads the default file set into `-o` (preserving paths like `config/metadata.yaml`). Override with repeated `-f PATH`, or pass `--artifacts-url` when you already have the base URL.

Manual download when you only need a few files:

Artifact files live under `{RD_JR_ARTIFACTS_URL}{relative_path}`. Upload uses `idm-artifacts upload --compress` — **most text files are gzip-encoded on the server** at the plain path (no `.gz` suffix); `metadata.mod.yaml` and `metadata.orig.yaml` are exceptions on some runs. Try plain URL first, then `.gz` suffix; decompress when payload has gzip magic.

### Download helper

Try gzipped first, then plain (same logic as `IdMUtils.downloadArtifact`):

```bash
ARTIFACTS_URL='https://idm-artifacts.psi.redhat.com/…/123/'

fetch_artifact() {
  local relpath="$1" dest="$2"
  if curl -sf "${ARTIFACTS_URL}${relpath}.gz" -o "${dest}.gz" \
     && gunzip -f "${dest}.gz"; then
    return 0
  fi
  curl -sf "${ARTIFACTS_URL}${relpath}" -o "$dest"
}
```

### Priority files

Download to a scratch dir, e.g. `/tmp/jenkins-artifacts-123/`:

| Relative path | Use |
|---------------|-----|
| **`metadata.mod.yaml`** | **Reproduction** — modified metadata Jenkins passed to `te` |
| `metadata.orig.yaml` | Pre-modifier source |
| `config/metadata.yaml` | Canonical copy after init |
| `pytest-run.rc` | `0` = tests passed |
| `junit.xml`, `pytests_junit.xml`, `*junit.xml` | Failed cases, errors |
| `runner.log` | Phase/step execution, return codes |
| `mrack.log` | Provision/teardown failures |
| `logs/*_pytest-run.log` | pytest + mh tracebacks |
| `config/test.inventory.yaml` | Live topology |
| `config/pytest-mh.yaml` | pytest-mh config |
| `artifacts.html` | Index of uploaded files (if present) |

Start with **junit**, **runner.log**, and **metadata.mod.yaml**; widen if the failure phase is unclear.

If individual downloads 404, fetch `artifacts.html` when available — it links key files. S3-backed artifact URLs have no directory listing; rely on the table above.

---

## 5. Analyze the failure

Work **narrowest signal first**:

1. **`pytest-run.rc`** + **junit** — failing test names, messages, stack traces
2. **`runner.log`** — which `te` phase/step failed and exit code
3. **`mrack.log`** — OpenStack/Beaker/AWS provision errors
4. **Console** — Jenkins infra (timeout, agent, credentials) when artifacts are empty

### Classify

| Type | Signals |
|------|---------|
| **Test bug** | Assertion in pytest log; test-only change fixes it |
| **Product bug** | Daemon/client traceback, regression in SUT |
| **Environment / infra** | mrack, DNS, image, quota, timeout, missing repo |
| **Metadata / config** | `metadata_modifier`, sanity check, wrong topology |
| **Pipeline** | Failure before `te`, RD upload, or artifact upload |

Report:

- Failed phase and step
- Failing test(s) or infra error (one-line cause each)
- Key log excerpt (last useful traceback, not full console)
- Link to artifacts URL for humans

---

## 6. Reproduce locally

Use [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md).

### Set up campaign

```bash
CAMPAIGN="jenkins-<job-slug>-<build>"   # e.g. jenkins-tier1-123
mkdir -p ~/git/@TESTRUNS/${CAMPAIGN}/twd
cp /tmp/jenkins-artifacts-123/metadata.mod.yaml \
   ~/git/@TESTRUNS/${CAMPAIGN}/twd/metadata.yaml
```

Inspect `metadata.yaml` init steps for **sibling repo clones** (`../sssd`, `../sudo-tests`, `init/git-clone.yaml`, …) and ensure those checkouts exist beside `twd`.

### Run

```bash
cd ~/git/@TESTRUNS/${CAMPAIGN}/twd
te --upto prep metadata.yaml      # provision cloud VMs
te --phase test metadata.yaml     # first test run — no clean-twd
# On re-run after fixes (hosts still up):
clean-twd && te --phase test metadata.yaml
```

**Do not teardown automatically** when the test phase has failures or errors (`pytest-run.rc` ≠ 0, failed/errored cases in junit, or a non-zero `te --phase test` exit). Leave the provisioned hosts up so the next iteration can re-run with `clean-twd && te --phase test` without provisioning again.

Teardown only when:

- All targeted tests **passed**, or
- The user explicitly asks to release hosts / abandon the campaign

```bash
te --phase teardown metadata.yaml   # only after pass or explicit request
```

Re-run only the failing pytest args from metadata (`pytest-mh:` / `pytests:` `args:`) when iterating.

If reproduction needs metadata edits (TOKEN_ values, domains), see [create-idmci-metadata](../create-idmci-metadata/SKILL.md).

### When not to reproduce

- Failure in **provision** with expired cloud resources and no inventory backup
- **Prep** package/repo drift — note SUT version from console `IDMCI_SUT_OS_VERSION` / brew task links
- User only wanted a **diagnosis**, not a re-run

State blockers explicitly.

---

## Order of operations

1. Parse build URL → fetch **consoleText**
2. Extract **`RD_JR_ARTIFACTS_URL`**
3. Download **junit**, **runner.log**, **metadata.mod.yaml** (+ phase-specific logs)
4. **Diagnose** — phase, tests, classification
5. **Reproduce** — `@TESTRUNS` + `te` when metadata is available and user wants a re-run
6. **Keep hosts** on test failure/error — skip teardown; only teardown after pass or explicit user request
7. **Report** — summary, artifacts link, reproduction commands run or suggested

Run independent fetches (console + artifact files) in parallel when possible.

---

## Report template

```markdown
## Jenkins failure: {job name} #{build}

**Build:** {BUILD_URL}
**Artifacts:** {RD_JR_ARTIFACTS_URL}
**Result:** {FAILURE|UNSTABLE|…}

### Root cause
{one paragraph}

### Failed phase / tests
- Phase: {prep|test|…}
- Tests: {file::test — message}

### Evidence
{short log excerpt}

### Reproduction
{commands or "blocked because …"}
{If tests failed/errored: note hosts left up — no teardown; next run is clean-twd + te --phase test}
```
