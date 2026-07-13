# ai-tools CLI

Standalone command-line helpers from the [ai-tools](https://github.com/jakub-vavra-cz/ai-tools) repository.

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

### clean-twd

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

## Tests

```bash
cd tools
python -m unittest discover -s tests -v
```
