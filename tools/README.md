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

### clean-twd

```bash
cd ~/git/@TESTRUNS/<campaign>/twd
clean-twd              # remove logs/, runner.log, pytest-run.rc, *junit.xml
clean-twd -n           # dry-run
clean-twd /path/to/twd # explicit twd path
```

## Tests

```bash
cd tools
python -m unittest discover -s tests -v
```
