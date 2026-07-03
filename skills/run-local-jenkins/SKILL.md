---
name: run-local-jenkins
description: >-
  Configures and starts a local IdM Jenkins CSB controller (podman) for any
  fork/branch of idm-jenkins, idm-jenkins-libs, and idm-ci. Uses a full git
  clone for the local CasC tree (not a linked worktree), local-develop.sh,
  jenkins-csb local.sh, job seeding, and optional custom agent images. Use when
  the user asks to run local Jenkins, jenkins-<change>, jenkins-csb local.sh,
  local-develop.sh, or develop jenkinslib/idm-jenkins/idm-ci on a local
  controller.
---

# Run local IdM Jenkins

Bring up a **local Jenkins CSB controller** against chosen forks/branches of
**idm-jenkins** (CasC), **idm-jenkins-libs** (shared library), and optionally
**idm-ci** (agent image / job params).


## Hostnames (`~/git/ai-tools.env`)

Resolve `${GITLAB_HOST}`, `${JENKINS_URL}`, `${DOCS_IDMCI_URL}`, and other Scope A
hosts from `~/git/ai-tools.env` (see [ai-tools README](../../README.md#internal-hostnames-gitai-toolsenvironment)).
Do not invent or hardcode internal hostnames in commands or tracked files.

Related skills (do not duplicate):

- [run-idm-jenkins](../run-idm-jenkins/SKILL.md) — trigger jobs on **remote** Jenkins via snippet
- [analyze-jenkins-failure](../analyze-jenkins-failure/SKILL.md) — debug a failed build
- [about-idmci](../about-idmci/SKILL.md) — IdM-CI concepts

Upstream: `idm-jenkins` README § Local development; `jenkins-csb` `cci-jd/docs/setup.md`.
Machine notes: `~/git/local-jenkins.md`.

---

## Inputs (ask if missing)

| Param | Meaning | Example |
|-------|---------|---------|
| `CHANGE` | Short name for this local instance (branch or topic) | `beetlejuice`, `buildjobs` |
| `GITLAB_FORK` | GitLab username owning the forks | `jvavra` |
| `JENKINS_BRANCH` | Branch of **idm-jenkins** (CasC) under test | `beetlejuice`, `master` |
| `JENKINSLIB_BRANCH` | Branch of **idm-jenkins-libs** | same or different |
| `IDMCI_BRANCH` | Branch of **idm-ci** (optional; image or job params) | `beetlejuice` |
| `LOCAL_JENKINS` | Full-clone path for local CasC + secrets | `~/git/jenkins-<CHANGE>` |
| `CSB_TAG` | jenkins-csb tag | `csb-2.541.3` |
| `LOCAL_PASS` | `--local-user-password` (≥6 chars, ≥2 classes) | `LocalDev1` |

Default CasC tree: **`LOCAL_JENKINS=~/git/jenkins-$CHANGE`**. One directory per
change so instances do not rewrite each other’s `casc.yaml` / secrets / working
tree. Prefer `CHANGE=$JENKINS_BRANCH` (or a topic slug) when the user does not
name it. Do **not** reuse a shared path like `my-jenkins` across changes.

Other defaults: `GITLAB_FORK=jvavra`, `CSB_TAG=csb-2.541.3`, `LOCAL_PASS=LocalDev1`.

---

## Layout

| Path | Role | Clone type |
|------|------|------------|
| `~/git/jenkins-<CHANGE>` (`$LOCAL_JENKINS`) | CasC + secrets; `local-develop.sh` edits; `local.sh` cwd | **Full git clone only** |
| `~/git/jenkins-fork-<branch>` | Clean/push clone of idm-jenkins | Worktree OK |
| `~/git/jenkinslib-fork-<branch>` | Shared library under test; must be **pushed** to origin | Worktree OK |
| `~/git/idmci-fork-<branch>` | IdM-CI for agent rebuild / `IDMCI_GITREPO` | Worktree OK |
| `~/git/jenkins-csb` | CSB (`self-service/local.sh`) on `$CSB_TAG` | Full clone OK |

`$LOCAL_JENKINS` is **not** the same as `jenkins-fork-*` (push/worktree). Naming:
`jenkins-<CHANGE>` = local CasC instance; `jenkins-fork-<branch>` = clean clone.

Repos naming for forks matches [repos.ini](../../../ai-tools/mcp/git-worktrees/git_worktrees_mcp/repos.ini)
(`jenkins-fork-`, `jenkinslib-fork-`, `idmci-fork-`).

### Full clone for `$LOCAL_JENKINS` (required)

`local.sh` / git-crypt / local CasC edits need a **real repository**, not a
linked worktree (`.git` file pointing at another clone).

```bash
CHANGE=<change-name>   # e.g. beetlejuice
LOCAL_JENKINS=~/git/jenkins-${CHANGE}

# OK: .git is a directory
test -d "$LOCAL_JENKINS/.git"

# Reject: linked worktree
test -f "$LOCAL_JENKINS/.git" && echo "FAIL: worktree — use a full clone"
```

Create if missing (do **not** use `create_worktree_branch` / `git worktree add`):

```bash
git clone git@${GITLAB_HOST}:${GITLAB_FORK}/idm-jenkins.git "$LOCAL_JENKINS"
cd "$LOCAL_JENKINS"
git fetch origin
git checkout "$JENKINS_BRANCH"
```

Keep the push/worktree clone (`jenkins-fork-$JENKINS_BRANCH`) separate; sync CasC
from it into `$LOCAL_JENKINS` when needed (see below).

Do **not** commit `casc.yaml` after `local-develop.sh`.

---

## Checklist

```
Local Jenkins:
- [ ] Inputs: CHANGE + fork + jenkins / jenkinslib / (optional) idmci branches
- [ ] LOCAL_JENKINS=~/git/jenkins-$CHANGE is a full clone on JENKINS_BRANCH; git-crypt unlock
- [ ] Not reusing another change’s CasC tree (no shared my-jenkins)
- [ ] `oc-login-sso` (Kerberos TGT required; refreshes oc credentials)
- [ ] jenkins-csb on CSB_TAG; optional local_disable_jobs.groovy tweak
- [ ] Firewall if --export-container-ports
- [ ] Reset casc.yaml; local-develop.sh -f FORK -b JENKINSLIB_BRANCH
- [ ] Push jenkinslib to origin/JENKINSLIB_BRANCH
- [ ] Start local.sh in tmux; verify X-Jenkins + live library fork/branch
- [ ] generate-idmci-jobs (disableJobs=true); confirm User-Tools
- [ ] Optional: custom agent image + CasC tag / IDMCI_GITREPO params
```

---

## 1. Prerequisites

### Secrets

```bash
cd "$LOCAL_JENKINS"
git-crypt unlock
file secrets/prod-scale-spoke1-dc-rdu3-k8s-sa-token   # plaintext JWT, not binary
```

Ensure secret files CasC `readFile`s exist (e.g. `secrets/idm-ci-jira-api-token`)
before start.

### OpenShift (DnO / IdM Jenkins namespace)

Needs a live Kerberos TGT (`klist`). Approved CLI (no browser):

```bash
pip install -e ~/git/ai-tools/tools[ocp]   # once
oc-login-sso                               # SSO + oc login + project
oc-login-sso --force                       # refresh even if whoami works
```

Skips SSO when `oc whoami` already works unless `--force`. Manual console
“Copy login command” only if SSO/SPNEGO fails. Do not paste cluster API URLs
into chat; defaults live in the tool (`OC_LOGIN_SSO_API_URL` /
`OC_LOGIN_SSO_PROJECT` override when needed).

### jenkins-csb

```bash
cd ~/git/jenkins-csb
git fetch origin
git checkout "$CSB_TAG"
```

**Optional but usual:** comment out / wrap the disable body in
`jenkins-csb/image-app/files/init.groovy.d/local_disable_jobs.groovy` so new
jobs stay enabled. Rebuild/restart after changing — baked into the image.

### Firewall (Fedora) for agents

Needed with `--export-container-ports`. Re-apply after VPN reconnect if agents
cannot connect:

```bash
sudo firewall-cmd --zone=FedoraWorkstation --add-port=8080/tcp --permanent
sudo firewall-cmd --zone=FedoraWorkstation --add-port=50000/tcp --permanent
# if redhat zone exists:
# sudo firewall-cmd --zone=redhat --add-port=8080/tcp --permanent
# sudo firewall-cmd --zone=redhat --add-port=50000/tcp --permanent
# sudo firewall-cmd --zone=redhat --add-port=50022/tcp --permanent
sudo firewall-cmd --reload
```

---

## 2. Configure CasC

From a clean `casc.yaml` on `$JENKINS_BRANCH`:

```bash
cd "$LOCAL_JENKINS"
git checkout -- casc.yaml    # if previously patched
./tools/local-develop.sh -f "$GITLAB_FORK" -b "$JENKINSLIB_BRANCH"
```

`local-develop.sh` points the shared library at
`https://${GITLAB_HOST}/${GITLAB_FORK}/idm-jenkins-libs.git` with
`defaultVersion: $JENKINSLIB_BRANCH`, switches SAML → local users, reverts K8s
cloud to in-cluster DnO (`OCPonBM`), prefixes agents with `${GITLAB_FORK}-`,
sets dummy `DEFAULT_PROJECTS_YAML_URL` and fresh gating UUIDs.

### Sync CasC from the push clone

When `jenkins-fork-$JENKINS_BRANCH` advances:

```bash
cd "$LOCAL_JENKINS"
cp ~/git/jenkins-fork-${JENKINS_BRANCH}/casc.yaml ./casc.yaml
./tools/local-develop.sh -f "$GITLAB_FORK" -b "$JENKINSLIB_BRANCH"
# optional custom agent tag:
# sed -i "s|idm-ci-jenkins:latest|idm-ci-jenkins:${AGENT_TAG}|" casc.yaml
```

---

## 3. Start Jenkins

Run `local.sh` in **tmux** (or equivalent) so an SSH/VPN disconnect does not
SIGHUP and stop the controller (`podman run --rm` dies with the session).

```bash
tmux new -s "jenkins-${CHANGE}"
cd "$LOCAL_JENKINS"
../jenkins-csb/self-service/local.sh \
  --export-container-ports \
  --local-user-password "$LOCAL_PASS"
# detach: Ctrl-b d — reattach: tmux attach -t "jenkins-${CHANGE}"
```

- Binds `8080` / `50000` on VPN/LAN IP; `JENKINS_URL=http://<ip>:8080/`.
- Engine: podman. Container: `jenkins-csb-local`.
- First run builds `localhost/jenkins-csb-controller-local:<ver>` (slow).
- Leave `local.sh` running in the tmux session; do not start it in a bare SSH shell.

### Log in

| User | Password |
|------|----------|
| `admin` | `admin` |
| `dev` | `$LOCAL_PASS` (when ports exported) |
| CasC locals (`davherna`, `user`, …) | same as username |

### Verify

```bash
podman ps --filter name=jenkins-csb-local
curl -sI http://127.0.0.1:8080/ | head -5   # expect X-Jenkins: …
```

---

## 4. Shared library must match CasC (restart)

**Global shared library** (`defaultVersion` / remote URL) often does **not**
apply via CasC reload. After changing fork/branch in casc, **full restart**:

```bash
podman stop jenkins-csb-local   # or Ctrl-C local.sh
# re-run local.sh as in §3
```

Confirm live library (Script Console or UI) before seeding:

```text
idm-jenkins-libs default=<JENKINSLIB_BRANCH>
remote=https://${GITLAB_HOST}/<GITLAB_FORK>/idm-jenkins-libs.git
```

If seed logs show `Loading library idm-jenkins-libs@main` (or wrong remote),
Job DSL from the fork will not run — restart and re-seed.

Push the library first so Jenkins can clone it:

```bash
cd ~/git/jenkinslib-fork-${JENKINSLIB_BRANCH}
git push -u origin "$JENKINSLIB_BRANCH"
```

---

## 5. Seed jobs (`generate-idmci-jobs`)

CasC creates seed jobs only. `User-Tools/*` come from library Job DSL via
`createBaseJobs()`.

Prefer `disableJobs=true` locally so CRON/listener jobs stay disabled:

```bash
# UI: Build with Parameters, or crumb + curl:
curl -u 'admin:admin' -H "Jenkins-Crumb: $CRUMB" \
  -X POST \
  'http://127.0.0.1:8080/job/generate-idmci-jobs/buildWithParameters?disableJobs=true'
```

List tools:

```bash
curl -sS -u 'admin:admin' \
  'http://127.0.0.1:8080/job/User-Tools/api/json?tree=jobs%5Bname%5D' \
  | python3 -c "import sys,json; print('\n'.join(j['name'] for j in json.load(sys.stdin)['jobs']))"
```

---

## 6. IdM-CI under test (optional)

### Prefer job params (no image rebuild)

For Python / idm-ci **code** changes:

```text
IDMCI_GITREPO=https://${GITLAB_HOST}/<GITLAB_FORK>/idm-ci
IDMCI_BRANCH=<IDMCI_BRANCH>
```

(Jenkins maps branch via `IDMCI_BRANCH`; see [run-idm-jenkins](../run-idm-jenkins/SKILL.md).)

### Rebuild agent image (Dockerfiles / OS packages)

Only when changing `idm-ci/agent/`. Corporate **squid proxy required** (oc client
download fails without it). Makefile expects `docker` — use a podman shim:

```bash
mkdir -p /tmp/docker-as-podman
printf '%s\n' '#!/bin/bash' 'exec podman "$@"' > /tmp/docker-as-podman/docker
chmod +x /tmp/docker-as-podman/docker
export PATH="/tmp/docker-as-podman:$PATH"

export ANSIBLE_VAULT_PASSWORD_FILE="${ANSIBLE_VAULT_PASSWORD_FILE:-$HOME/ansible-vault-password-idmci}"
export http_proxy="${HTTP_PROXY}"
export https_proxy="${HTTPS_PROXY:-$HTTP_PROXY}"
export HTTP_PROXY="$http_proxy" HTTPS_PROXY="$https_proxy"
export no_proxy="${NO_PROXY}"
export NO_PROXY="$no_proxy"

AGENT_TAG="${AGENT_TAG:-${GITLAB_FORK}-test}"
cd ~/git/idmci-fork-${IDMCI_BRANCH}
make build TAG="$AGENT_TAG"
make build-jenkins TAG="$AGENT_TAG"
```

Push to **${INTERNAL_REGISTRY}** (not quay for this path):

| Secret | Use |
|--------|-----|
| `$LOCAL_JENKINS/secrets/internal-registry-token` | password |
| Username | `${INTERNAL_REGISTRY_USER}` |

```bash
TOKEN=$(tr -d '\n' < "$LOCAL_JENKINS/secrets/internal-registry-token")
echo "$TOKEN" | podman login -u "${INTERNAL_REGISTRY_USER}" --password-stdin "${INTERNAL_REGISTRY}"
podman tag "idmops/idm-ci-jenkins:${AGENT_TAG}" \
  "${INTERNAL_REGISTRY_AGENT_IMAGE}:${AGENT_TAG}"
podman push "${INTERNAL_REGISTRY_AGENT_IMAGE}:${AGENT_TAG}"
```

Do **not** overwrite `:latest` or shared `:testing` unless intentional for the team.

Point CasC `idm-ci` image (YAML anchor for jnlp/maintenance/extended/smartcard):

```yaml
image: "${INTERNAL_REGISTRY_AGENT_IMAGE}:<AGENT_TAG>"
```

Reload CasC (agent image / credentials) or restart. `testing-agent` keeps its own
`:testing` override unless changed.

---

## 7. CasC reload vs restart

| Change | Action |
|--------|--------|
| Agent image, many credentials, env vars | CasC reload often enough (`/configuration-as-code/reload` + crumb) |
| Global shared library URL / `defaultVersion` | **Full controller restart** |

---

## 8. Stop / reset

```bash
podman stop jenkins-csb-local          # or Ctrl-C local.sh
cd "$LOCAL_JENKINS" && git checkout -- casc.yaml
# hard-align local clone to pushed tip (destructive to local commits):
# git fetch origin && git reset --hard "origin/${JENKINS_BRANCH}"
```

---

## Jira importer credential (when testing that tool)

| Piece | Detail |
|-------|--------|
| Secret file | `secrets/idm-ci-jira-api-token` (git-crypt) |
| CasC credential id | `idm-ci-jira-api-token` |
| Pipeline | `IDMCI_JIRA_API_TOKEN = credentials('…')` in library `jiraImportTool.groovy` |

Do not put the API token in a string build parameter.

---

## Do not

- Use a **git worktree** as `$LOCAL_JENKINS` (full clone only).
- Reuse one CasC tree (`my-jenkins`, etc.) for different changes — use
  `~/git/jenkins-<CHANGE>` per instance.
- Commit `casc.yaml` after `local-develop.sh`.
- Seed jobs while the controller still loads `idm-jenkins-libs@main` / wrong remote.
- Push custom agent tags over team `:latest` / `:testing` without explicit ask.
- Confuse this with [run-idm-jenkins](../run-idm-jenkins/SKILL.md) (remote trigger-test-suite).
