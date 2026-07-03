---
name: run-idm-jenkins
description: >-
  Uploads IdM-CI job metadata as a GitLab snippet on sssd/sssd-qe and triggers
  Jenkins User-Tools/trigger-test-suite-tool via MCP with IDMCI_METADATA_URL
  (snippet raw URL), or via Jenkins REST --trigger when MCP is unavailable.
  Supports a custom IdM-CI fork/branch via IDMCI_GITREPO and IDMCI_GITBRANCH
  (Jenkins param IDMCI_BRANCH). Use when running metadata on
  Jenkins, trigger-test-suite-tool, IDMCI_METADATA_URL, or a custom idm-ci
  git repo/branch.
---

# Run IdM-CI metadata on Jenkins

Upload a job metadata file as an **sssd/sssd-qe** GitLab snippet, then trigger
**`User-Tools/trigger-test-suite-tool`** with the snippet **raw** URL as
`IDMCI_METADATA_URL`.

Related skills (read and follow; do not duplicate):

- [create-idmci-metadata](../create-idmci-metadata/SKILL.md) — author the YAML
- [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md) — local `te` / `@TESTRUNS` (not Jenkins)
- [analyze-jenkins-failure](../analyze-jenkins-failure/SKILL.md) — debug the build after it runs

Approved CLI: **`run-idm-jenkins`** from [ai-tools/tools](../../tools/README.md)
(`pip install -e ~/git/ai-tools/tools`). Use it instead of ad-hoc `glab snippet`
/ `curl`. Prefer MCP `trigger_build`; if MCP is unavailable, pass **`--trigger`**
so the CLI POSTs `buildWithParameters` itself.

---

## Checklist

```
Jenkins metadata run:
- [ ] Metadata YAML authored (create-idmci-metadata) or path given
- [ ] Optional sanity check (metadata_sanity_check.py)
- [ ] run-idm-jenkins <file> --json (plus IDMCI_GITREPO / IDMCI_GITBRANCH if custom IdM-CI)
- [ ] Trigger: MCP user-jenkins trigger_build, or run-idm-jenkins --trigger if MCP is down
- [ ] Report snippet URL and Jenkins build to the user
```

---

## Checklist

```
Jenkins metadata run:
- [ ] Metadata YAML authored (create-idmci-metadata) or path given
- [ ] Optional sanity check (metadata_sanity_check.py)
- [ ] run-idm-jenkins <file> --json (plus IDMCI_GITREPO / IDMCI_GITBRANCH if custom IdM-CI)
- [ ] MCP user-jenkins trigger_build with jenkins_job + jenkins_parameters
- [ ] Report snippet URL and Jenkins build to the user
```

---

## 1. Author metadata

If the user did not give an existing file, follow
[create-idmci-metadata](../create-idmci-metadata/SKILL.md) and write a YAML file
(campaign `twd/metadata.yaml` or a temp path). Tokens (`TOKEN_SUITE`, …) stay in
the file; pass replacements as Jenkins params (`--param IDMCI_REPLACE_TOKEN=…`).

Optional:

```bash
~/git/idmci-fork-master/scripts/metadata_sanity_check.py path/to/metadata.yaml
```

---

## 2. Upload snippet

```bash
run-idm-jenkins path/to/metadata.yaml --json
```

Custom IdM-CI fork/branch (both needed for Jenkins to clone a non-default tree):

```bash
# Explicit URL + branch (user-facing name: IDMCI_GITBRANCH)
run-idm-jenkins path/to/metadata.yaml --json \
  --idmci-gitrepo https://gitlab.cee.redhat.com/<user>/idm-ci.git \
  --idmci-gitbranch <branch>

# Or infer origin HTTPS URL + current branch from a local checkout
run-idm-jenkins path/to/metadata.yaml --json \
  --idmci-checkout ~/git/idmci-fork-<branch>
```

`--dry-run` / `-n` prints params without creating a snippet.

Named Jenkins flags match `trigger-test-suite-tool` / artifact `envvar.txt`.
`--help` lists all. Common ones from a typical run:

| Flag | Jenkins param | Example |
|------|---------------|---------|
| `--idmci-replace-os` | `IDMCI_REPLACE_OS` | `rhel:rhel-10.2\|client_os:rhel-10.3\|windows:win-2025` |
| `--idmci-replace-token` | `IDMCI_REPLACE_TOKEN` | `SUITE:-k="test_gpo"\|NAME:gpo` |
| `--idmci-compose-url` | `IDMCI_COMPOSE_URL` | compose `/compose/` URL |
| `--idmci-provider` | `IDMCI_PROVIDER` | `openstack`, `aws`, `beaker` |
| `--idmci-test-repo-branch` | `IDMCI_TEST_REPO_BRANCH` | test git branch |
| `--idmci-brew-task-id` | `IDMCI_BREW_TASK_ID` | brew task id |
| `--idmci-extra-repo-url` | `IDMCI_EXTRA_REPO_URL` | extra yum repo |
| `--idmci-is-fips` / `--idmci-is-nightly` | `IDMCI_IS_FIPS` / `IDMCI_IS_NIGHTLY` | `true` / `false` |
| `--idmci-skip-teardown` | `IDMCI_SKIP_TEARDOWN` | `true` to keep SUTs |

Replay a previous job’s env dump (skips secrets, empties, and `IDMCI_METADATA_URL`):

```bash
run-idm-jenkins path/to/metadata.yaml --json \
  --envvar-file /path/to/envvar.txt \
  --idmci-replace-token 'SUITE:-k="test_gpo"|NAME:gpo'
```

CLI flags override `--envvar-file`; `--param KEY=VALUE` overrides the file and is overridden by named flags. Snippet raw URL always wins for `IDMCI_METADATA_URL`.

Env aliases: `IDMCI_GITREPO`, `IDMCI_GITBRANCH`, and each named `IDMCI_*` flag. Extra job params still accepted as `--param`.

Requires **`glab`** on `PATH`, authenticated to `gitlab.cee.redhat.com`, with
permission to create project snippets on **`sssd/sssd-qe`** (override with
`--repo GROUP/PROJ`). Default visibility is **`internal`**.

JSON fields to use next:

| Field | Use |
|-------|-----|
| `jenkins_job` | MCP `job_name` (default `User-Tools/trigger-test-suite-tool`) |
| `jenkins_parameters` | MCP `parameters` dict — copy as-is unless `--trigger` was used |
| `trigger` | Present after `--trigger`: `queue_url`, `build_url`, `build_number` |
| `snippet.raw_url` / `web_url` | Show the user |
| `idmci_gitrepo` / `idmci_gitbranch` | Echoed user-facing names |

---

## 3. Trigger Jenkins

**Prefer MCP** server **`user-jenkins`**, tool **`trigger_build`**:

- `job_name`: `jenkins_job` from the CLI (default `User-Tools/trigger-test-suite-tool`)
- `parameters`: the `jenkins_parameters` object

`IDMCI_METADATA_URL` must be the snippet **raw** URL (Jenkins `wget`s it).

Do **not** invent a different job. If `trigger_build` succeeds, report the build
number/URL from the MCP result. Do **not** also pass `--trigger` (that would
start a second build).

### REST fallback (`--trigger`)

Use when MCP `user-jenkins` is missing, needs auth, or `trigger_build` fails.
Same command uploads the snippet and POSTs Jenkins `buildWithParameters`:

```bash
export JENKINS_URL=https://jenkins-csb-idmops-ci.dno.corp.redhat.com
export JENKINS_USERNAME=…
export JENKINS_PASSWORD=…          # API token
export REQUESTS_CA_BUNDLE=~/git/certs/combined-certifi.pem   # if needed

run-idm-jenkins path/to/metadata.yaml --json --trigger
```

JSON `trigger.queue_url` / `trigger.build_url` / `trigger.build_number` are the
REST result. `--trigger-wait 0` returns the queue URL without polling.

Console text is not in MCP — use [analyze-jenkins-failure](../analyze-jenkins-failure/SKILL.md)
when the user wants a diagnosis.

---

## Custom IdM-CI (`IDMCI_GITREPO` / `IDMCI_GITBRANCH`)

Jenkins `prepareIdmCI` clones a custom tree only when **both** are set:

| User / CLI | Jenkins parameter |
|------------|-------------------|
| `IDMCI_GITREPO` / `--idmci-gitrepo` | `IDMCI_GITREPO` |
| `IDMCI_GITBRANCH` / `--idmci-gitbranch` | **`IDMCI_BRANCH`** |

Pass **`IDMCI_BRANCH`** to MCP (or `--trigger`), not `IDMCI_GITBRANCH`. The CLI maps it.

If only one is given, the CLI fills the other: default repo
`https://gitlab.cee.redhat.com/identity-management/idm-ci.git`, default branch
`master`. SSH remotes from `--idmci-checkout` are converted to HTTPS.

Use a custom fork/branch when the user is testing unmerged IdM-CI (playbooks,
`te`, metadata modifier) — not for ordinary sssd-qe metadata on production
idm-ci.

---

## Do not

- Trigger Jenkins without a snippet raw URL (local file paths are not valid
  `IDMCI_METADATA_URL` values).
- Pass `IDMCI_GITBRANCH` as the Jenkins parameter name.
- Run this skill for a local `@TESTRUNS` / `te` campaign — that is
  [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md).
- Delete the GitLab snippet after the run unless the user asks.
