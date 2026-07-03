---
name: linux-oob-troubleshoot
description: >-
  Sets up lab-only Linux out-of-band access (telnet :23, socat root shell :2323)
  and remote rsyslog to the controller for IdM-CI / @TESTRUNS SSH-death debugging.
  Uses playbook under ai-tools/skills/linux-oob-troubleshoot/playbooks/. Detects
  controller IP dynamically; takes telnet root password from inventory
  ansible_password. Use when SSH hangs or dies mid-test, host health is unclear,
  or the user asks for OOB, telnet, socat login, serial-alternative, or remote
  syslog on provisioned Linux SUTs.
---

# Linux OOB troubleshooting (IdM-CI lab)

**Lab-only.** Never apply these patterns to production.

When pytest-mh / SSH looks dead, prove whether the **host** is hung vs the **session** is stale: configure non-SSH access + remote syslog **before** or at first suspicion, then probe with telnet/socat + rsyslog while tests run.

Related: [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md), [analyze-jenkins-failure](../analyze-jenkins-failure/SKILL.md), [writing-ansible](../writing-ansible/SKILL.md).

---

## Playbook placement (ai-tools)

| Path | Role |
|------|------|
| **`~/git/ai-tools/skills/linux-oob-troubleshoot/playbooks/configure-linux-oob.yaml`** | Canonical playbook (keep here; edit in place) |
| **`…/playbooks/files/rsyslog.conf`** | Podman collector config (UDP/TCP 5514) |
| Campaign `twd/oob/` | Optional **copy** of playbook + local collector dir (`oob/rsyslog/{config,log}`) for a single campaign — do not invent a second source of truth |

Prefer running the playbook by **absolute path** from `twd`. Copy into `twd/oob/` only when the campaign needs a self-contained tree (handoff, sharing).

Not under `ai-tools/tools/` unless a CLI wrapper is added later — this is agent/workflow content, not a packaged console script.

---

## Workflow

### 1. Prerequisites

- Provisioned IdM-CI campaign with `twd/config/test.inventory.yaml` and SSH key (`config/id_rsa`)
- Linux SUTs in inventory (`hosts: all:!ad` — AD/WinRM skipped)
- Inventory has **`ansible_password`** somewhere (IdM-CI usually on the AD host). That value is used as the telnet **root** password via `chpasswd`
- Controller can reach SUT IPs (`meta_ip` / OpenStack private net); SUTs must reach **controller IPv4** for rsyslog

### 2. Start rsyslog collector on the controller

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
mkdir -p oob/rsyslog/{config,log}
cp ~/git/ai-tools/skills/linux-oob-troubleshoot/playbooks/files/rsyslog.conf oob/rsyslog/config/
# Build once if needed: podman build -t localhost/idmci-rsyslog:latest -f Containerfile …
cd oob/rsyslog
podman rm -f idmci-rsyslog 2>/dev/null || true
podman run -d --name idmci-rsyslog --network host \
  -v "$PWD/config/rsyslog.conf:/etc/rsyslog.conf:ro,Z" \
  -v "$PWD/log:/var/log/remote:Z" \
  docker.io/rsyslog/rsyslog-collector:latest
# Or localhost/idmci-rsyslog:latest if a local image exists
```

Open firewall on the controller for the SUT subnet → **5514/udp+tcp** (rich rules / firewalld). Detect controller IP the same way the playbook does (default IPv4), e.g. `ip -4 route get 1.1.1.1`.

If no suitable collector image is available, use any rsyslog container that mounts the skill’s `rsyslog.conf` and binds `log/` to `/var/log/remote`.

### 3. Configure OOB on Linux SUTs

From **twd** (inventory paths are relative):

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
ansible-playbook -i config/test.inventory.yaml \
  ~/git/ai-tools/skills/linux-oob-troubleshoot/playbooks/configure-linux-oob.yaml \
  --private-key=config/id_rsa -b
```

| Variable | Source |
|----------|--------|
| `controller_ip` | Default: this machine’s `ansible_default_ipv4.address`. Override: `-e controller_ip=…` |
| `root_password` | Default: host `ansible_password`, else first inventory `ansible_password` (typically AD). Override: `-e root_password=…` |
| `rsyslog_port` | Default `5514` |

Playbook enables:

| Method | Port | Auth |
|--------|------|------|
| **telnet** | 23 | `root` / inventory password |
| **socat root shell** | 2323 | none (lab) |
| **rsyslog forward** | UDP → controller:5514 | — |

### 4. When SSH looks dead

1. Tail collector: `tail -f oob/rsyslog/log/<short-hostname>/messages`
2. Prefer **socat/nc :2323**, then **telnet :23** — do not rely on pytest-mh’s persistent SSH alone
3. Fresh SSH in a new terminal is still useful as a control
4. Record load, `systemctl is-active sshd`, memory, journal around the failure window under `twd/oob/monitor/` (or campaign notes)

### 5. Interpret

| Probe | Meaning |
|-------|---------|
| OOB / fresh SSH **OK**, pytest-mh `LibsshChannelException [-2]` | Stale pylibssh session / framework — not host hang |
| OOB **dead**, rsyslog silent, console dead | Likely host hang / network / cloud issue |
| rsyslog shows OOM / sshd crash | Host-side failure |

Update `twd/AGENT-HANDOFF.md` with probe results.

---

## Safety

- Telnet + passwordless socat root shell are **lab-only**
- Tear down hosts when done (`te --phase teardown`); do not leave OOB ports on long-lived machines
- `no_log: true` on `chpasswd`; do not paste inventory passwords into tickets/chat

---

## After editing the playbook

Follow [writing-ansible](../writing-ansible/SKILL.md): `check-ansible` on `playbooks/configure-linux-oob.yaml` (syntax-check with a sample inventory when practical).
