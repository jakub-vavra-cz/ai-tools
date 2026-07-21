# ai-tools CLI

Standalone command-line helpers from the [ai-tools](https://github.com/jakub-vavra-cz/ai-tools) repository.
These are intended as tools both for manual ause and for agent to use as "approved" tools.

## Install

From a local checkout:

```bash
pip install -e /path/to/ai-tools/tools
```

## Commands

| Command | Description |
|---------|-------------|
| `clean-twd` | Remove stale IdM-CI `twd` logs and test artifacts before re-execution |
| `pull-jenkins-artifacts` | Fetch Jenkins console, extract `RD_JR_ARTIFACTS_URL`, download twd artifacts |
| `check-ansible` | yamllint + dual-stack ansible syntax-check / ansible-lint (writing-ansible) |
| `dump-polarion-testcase` | Fetch a Polarion testcase via REST API and dump it as `key=value` |
| `import-jira-testcase` | Import a jira-format dump into RHELTEST (match by ID, then summary) |
| `scan-python-testcase` | Scan local Python tests (Betelgeuse-style) into jira-format dumps |

### clean-twd

Allow ai agent to delete specific logs without giving it rights to run "rm" directly.

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
clean-twd              # remove logs/, runner.log, pytest-run.rc, *junit.xml
clean-twd -n           # dry-run
clean-twd /path/to/twd # explicit twd path
```

### pull-jenkins-artifacts

Fetches Jenkins `consoleText`, extracts `RD_JR_ARTIFACTS_URL`, and downloads
diagnostic twd files (`metadata.mod.yaml`, `runner.log`, junit, etc.) from the
artifact server. Gzip-compressed uploads are handled automatically.

Requires `JENKINS_USERNAME` and `JENKINS_PASSWORD` (API token) for console
fetch. Optional: `REQUESTS_CA_BUNDLE` for corp TLS.

```bash
export JENKINS_USERNAME=<username>
export JENKINS_PASSWORD=<api-token>
export REQUESTS_CA_BUNDLE=~/git/certs/combined-certifi.pem

pull-jenkins-artifacts 'https://jenkins…/job/…/123/' -o /tmp/jenkins-123
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --url-only
pull-jenkins-artifacts --artifacts-url 'https://idm-artifacts…/path/' -f metadata.mod.yaml
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --console-only
pull-jenkins-artifacts 'https://jenkins…/job/…/123/' --json
```

### check-ansible

Runs the [writing-ansible](../skills/writing-ansible/SKILL.md) check gate on
one or more Ansible YAML files:

1. Discover `$ANSIBLE_ROOT` (`ansible.cfg`, `.ansible-lint`, `.yamllint`, …)
2. **yamllint** (system, or `uvx` fallback)
3. **ansible-playbook --syntax-check** on playbooks — system + uvx
   (Python 3.12 + `ansible==9.13.0` by default); fails on `[DEPRECATION WARNING]`
4. **ansible-lint --strict** when the project uses ansible-lint, or for
   non-playbook role/tasks files — system + uvx
5. **ansible-lint --strict -t deprecations** always — system + uvx

```bash
check-ansible roles/facts/tasks/RedHat.yml
check-ansible playbook.yml -i inventory.yml
check-ansible roles/facts/tasks/RedHat.yml --skip-uvx -q
check-ansible roles/facts/tasks/RedHat.yml --json
check-ansible path.yml --ansible-version 9.8.0   # e.g. CentOS 8 pin
```

Exit `0` when all non-skipped checks pass; `1` on lint/syntax/deprecation
failure; `2` on bad arguments / missing paths.

### dump-polarion-testcase

Fetches a Polarion work item (testcase) and its test steps via the REST API
v1 (same endpoints/auth as `mcp-server-polarion`) and writes a one-line-per-
field `key=value` dump.

**Default `--format jira`** maps fields for RHELTEST Test Case import
([create-rheltest-testcase](../skills/create-rheltest-testcase/SKILL.md)):

| Dump key | Polarion source | Jira field |
|----------|-----------------|------------|
| `summary` | `title` | Summary |
| `assignee` | Polarion assignee email, else author email | Assignee |
| `components` | `casecomponent` | Components |
| `labels` | `tags` | Labels |
| `AssignedTeam` | `subsystemteam` | `customfield_10606` |
| `ID` | `testCaseID` | `customfield_10591` |
| `URL` | `automation_script` if valid http(s), else hyperlinks `testscript` | `customfield_10933` |
| `External issue URL` | Polarion browse URL | `customfield_10766` |
| `status` | Polarion status | Issue status (`Draft` / `Active` / `Retired`) |
| `description` | Polarion description + setup / steps / teardown + remaining fields as HTML (`created`/`updated` omitted) | Description |

Polarion status mapping: `draft` / `needs update` / `proposed` → `Draft`;
`inactive` → `Retired`; `approved` → `Active`. The import tool applies
`status` via a workflow transition after create/update.

Use `--format polarion` for the raw Polarion attribute dump. Newlines in
values are escaped as `\n`.

Requires `POLARION_URL` and `POLARION_TOKEN`. Optional: `POLARION_VERIFY_SSL`
(`false` to disable TLS verify), `REQUESTS_CA_BUNDLE` for corp TLS.

```bash
export POLARION_URL=https://polarion.engineering.redhat.com
export POLARION_TOKEN=<personal-access-token>
export REQUESTS_CA_BUNDLE=~/git/certs/combined-certifi.pem

dump-polarion-testcase -P RHEL_IDM -i RHEL-130263
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 -o /tmp/RHEL-130263.properties
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 --stdout
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 --format polarion
dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 --no-teststeps
```

### scan-python-testcase

Betelgeuse-style scanner: walks a local/cloned tree for `test_*.py` /
`*_test.py`, collects `test_*` functions/methods via AST, reads `:field:`
docstring metadata (and optional [pytest-output](https://github.com/next-actions/pytest-output)
`polarion.yaml` defaults), and writes one jira-format `key=value` dump per
test for `import-jira-testcase`.

Does expand ``@pytest.mark.parametrize`` (literal values) and
``@pytest.mark.topology`` / ``KnownTopology(Group)`` into one dump per
variant. Each variant gets a distinct ``ID`` (pytest-style
``…[param-id] (topology)``) and parameters are appended to
``summary`` / title.

```bash
# Auto-discovers polarion.yaml upward from the source path when present
scan-python-testcase ~/git/sssd-fork-master/src/tests/system/tests \
  -o /tmp/sssd-dumps --tests-url https://github.com/SSSD/sssd/tree/master/src/tests/system

scan-python-testcase path/to/test_foo.py -o /tmp/dumps --no-polarion-config \
  --id-prefix idm-sssd-tc --title-prefix 'IDM-SSSD-TC: ' \
  --component sssd --team rhel-idm-sssd --upstream yes

scan-python-testcase path/to/tests -n --json   # dry-run summary
import-jira-testcase /tmp/sssd-dumps/<id>.properties --dry-run
```

Optional: PyYAML when reading `--polarion-config` / auto-discovered
`polarion.yaml`.

### import-jira-testcase

Imports a `--format jira` dump into Jira (default project `RHELTEST`, issue
type `Test Case`):

1. Search for an existing Test Case with matching `customfield_10591` (`ID`)
2. If `ID` is set and no match → **create** (do not fall back to summary;
   parametrized tests often share titles)
3. If `ID` is absent → search by exact `summary`
4. Update on match; otherwise create

Requires `JIRA_URL`, `JIRA_EMAIL` (or `JIRA_USER`), and `JIRA_API_TOKEN`.
Optional: `REQUESTS_CA_BUNDLE`, `JIRA_VERIFY_SSL=false`.

```bash
export JIRA_URL=https://stage-redhat.atlassian.net
export JIRA_EMAIL=<you@redhat.com>
export JIRA_API_TOKEN=<token>

dump-polarion-testcase -P RHEL_IDM -i RHEL-130263 -o /tmp/tc.properties
import-jira-testcase /tmp/tc.properties --dry-run
import-jira-testcase /tmp/tc.properties --skip-assignee --skip-components
import-jira-testcase /tmp/tc.properties --json
```

## Tests

```bash
cd tools
python -m unittest discover -s tests -v
```
