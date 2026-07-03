---
name: write-sssd-system-tests
description: Writes and edits SSSD multihost system tests using sssd-test-framework and pytest-mh (sudo, adcli, realmd, identity providers). After any Python edits, follows the run-python-static-code-analysis skill. Use when adding or changing tests under SSSD src/tests/system, or on components using the same framwork.
---

# SSSD system tests (pytest-mh + sssd-test-framework)

## Stack and references

| Layer | Role | Links |
|--------|------|--------|
| **pytest-mh** | Multihost plugin: SSH to test hosts, fixtures, cleanup | [pytest-mh](https://github.com/next-actions/pytest-mh), [docs](https://pytest-mh.readthedocs.io) |
| **sssd-test-framework** | High-level roles (`Client`, providers), topology marks, utilities (`adcli`, `realm`, SSSD) | [sssd-test-framework](https://github.com/SSSD/sssd-test-framework), [tests.sssd.io](https://tests.sssd.io) |
| **SSSD upstream tests** | Canonical test tree and conventions | [src/tests/system](https://github.com/SSSD/sssd/tree/master/src/tests/system) |

Pin **`pytest-mh`** to a specific version in project requirements when possible; upstream warns of possible minor breaking changes.

## Where tests live

- Upstream: `src/tests/system/tests/test_*.py` (see [readme.rst](https://github.com/SSSD/sssd/blob/master/src/tests/system/tests/readme.rst) in that tree for file purposes).
- Match the right module: `test_sudo.py` (sudo responder), `test_ad.py` / AD-specific markers, `test_tools.py` for CLI helpers, etc.

## Topology and markers

- Import `KnownTopology`, `KnownTopologyGroup` from `sssd_test_framework.topology`.
- Declare required layout with **`@pytest.mark.topology(...)`** (repeat the decorator to run the same test on several topologies).
- Common patterns:
  - **`KnownTopologyGroup.AnyProvider`** — run against all configured identity backends when the scenario is generic.
  - **`KnownTopology.AD`**, **`KnownTopology.LDAP`**, **`KnownTopology.IPA`**, **`KnownTopology.Samba`**, etc. — provider-specific tests.
- Upstream AD testing typically uses **Samba AD**; the readme notes using **`AnyAD`** when broader AD coverage is needed early.
- Use **`@pytest.mark.importance`**, **`@pytest.mark.ticket(bz=..., gh=...)`**, and **`@pytest.mark.require`** when matching existing tests.

## Fixtures and types

- Use injected fixtures: **`client: Client`**, **`provider`** as **`GenericProvider`** or a specific role (`GenericADProvider`, `AD`, `LDAP`, …) depending on topology.
- Configure SSSD via **`client.sssd`** (e.g. `client.sssd.common.sudo()`, `client.sssd.start()`, domain keys).
- Identity and sudo rules: **`provider.user(...)`**, **`provider.group(...)`**, **`provider.sudorule(...)`** on the generic/provider API.
- Authentication and sudo checks: **`client.auth.sudo.list`**, **`client.auth.sudo.run`**, **`client.auth.parametrize(...)`** for login methods where applicable.

## Docstrings (required shape)

Each test should use RST-style fields in the docstring so tooling and reviewers stay consistent:

- **`:title:`** — short descriptive name (required).
- **`:setup:`** — numbered preconditions.
- **`:steps:`** — numbered actions (start with the scenario under test).
- **`:expectedresults:`** — numbered outcomes aligned with steps.
- **`:customerscenario:`** — `True` or `False`.
- **`:requirement:`** — traceability id or `None` when allowed by project rules.

Optional **`:description:`** for extra context. Keep test code aligned in order with **setup → steps** so the docstring matches execution.

## Sudo tests

- Enable the sudo service in SSSD configuration (e.g. **`client.sssd.common.sudo()`** before **`client.sssd.start()`**).
- Model rules with **`provider.sudorule(...).add(...)`**; create users/groups as needed.
- Assert with **`client.auth.sudo.*`** rather than shelling out manually unless the test is explicitly about command-line behavior.
- Prefer **small, single-purpose tests**; merge overlapping cases when it reduces maintenance without losing clarity.

## adcli and realmd

- Both are exposed on the **`Client`** role: **`client.adcli`** ([`AdcliUtils`](https://github.com/SSSD/sssd-test-framework)), **`client.realm`** ([`RealmUtils`](https://github.com/SSSD/sssd-test-framework)) — join, leave, discover, `testjoin`, password operations, etc.
- Typical usage: **AD-class topologies** where the client must join or interrogate a domain; use framework helpers for consistent auth and **`ProcessResult`** handling (`rc`, `stdout`, `stderr`).
- Prefer framework wrappers over raw **`client.host.conn.exec([...])`** unless testing a specific failure mode or missing wrapper.

## After editing Python test files

**Always apply the [run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md) skill** when this skill is used and any `.py` file was created or modified (discover config and CI first; then ruff or flake8 / isort / Black as that skill describes). Use the target tree’s config (`setup.cfg`, `tox.ini`, `pyproject.toml`, `.flake8`, `ruff.toml` under `src/tests/system` or repo root).

Do not treat the task as finished until that workflow is satisfied for all touched Python files.

## Style and naming

- Broader CI for framework and SSSD trees may also run **isort**, **mypy**, **pycodestyle** (e.g. **`tox`**). Match surrounding imports in `src/tests/system` when the project enforces them.
- Test and function names: **`test_<file_topic>__<behavior>`** (double underscore between file theme and case) per existing `test_*.py` files.

## What not to mix in

- Legacy **`sssd.testlib`** / paramiko-style multihost tests are a different stack; for new SSSD system tests in `src/tests/system`, use **pytest-mh + sssd-test-framework** only.
- Avoid breaking **sssd-test-framework** public APIs without strong justification; consumers include multiple projects.

## Quick checklist for new tests

1. Correct **`test_*.py`** file and **`@pytest.mark.topology`** for the scenario.
2. Full docstring fields (**title**, **setup**, **steps**, **expectedresults**, **customerscenario**, **requirement**).
3. Minimal provider objects and SSSD settings; **`client.sssd.start()`** after configuration.
4. Assertions that match documented **expectedresults** line by line.
5. Run lint/format on all changed `.py` files per [run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md); run any additional project checks (mypy, etc.) if required by that tree.

For deeper concepts and examples, prefer [Writing system tests](https://tests.sssd.io/en/latest/concepts.html) and the pytest-mh **example** tree in its repository.
