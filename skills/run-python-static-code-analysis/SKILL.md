---
name: run-python-static-code-analysis
description: >-
   Runs lint and format checks on edited Python files using the project's configured tools. Discovers settings from pyproject.toml, pre-commit, or CI; falls back to ruff when nothing is configured. Applies flake8 to all edits; applies isort and Black only when the file already followed those tools. Use when modifying Python code or verifying lint and format after changes.
---

# Python edits: lint and format (ruff, flake8, isort, Black)

## Before running any lint or format tool

Do **not** assume default CLI flags until you have checked the repo. Discover how this project expects linting to run, then invoke tools so they pick up that configuration.

1. **In-repo configuration (prefer this)** — Look for settings that define ruff, flake8, isort, Black, or related tools, and follow them when choosing commands and arguments:

   - **Ruff**: `[tool.ruff]` in `pyproject.toml` (and `ruff.toml` / `.ruff.toml` if present).
   - **flake8**: `.flake8`, `setup.cfg`, `tox.ini`, `pyproject.toml` (e.g. `[flake8]` / `[tool.flake8]` where supported), or `[flake8]` in other supported locations.
   - **Black**: `[tool.black]` in `pyproject.toml`, or `black` options in `setup.cfg` / `tox.ini` if present.
   - **isort**: `[tool.isort]` in `pyproject.toml`, `.isort.cfg`, `setup.cfg`, `tox.ini`.
   - **Orchestration**: `.pre-commit-config.yaml` (hooks often show the exact checker and args the maintainers use).

   When a config file exists, prefer running the tool **without** overriding those settings (e.g. plain `flake8 path/to/file.py` so `.flake8` / `pyproject.toml` applies). Only add explicit flags when they match the discovered config or when you must point at a config path the tool would not find by default.

2. **If project lint configuration is missing or unclear** — Inspect CI for what the project actually runs in automation:

   - **GitHub Actions**: `.github/workflows/*.yml` (and reusable workflows under `.github/` if referenced). Look for steps that run `flake8`, `black`, `isort`, `ruff`, `pre-commit`, `tox`, `nox`, or `make` targets that lint Python.
   - **GitLab CI**: `.gitlab-ci.yml`, `.gitlab-ci.yaml`, and includes under `.gitlab/ci/*.yml`. Same signals: jobs that invoke linters or `pre-commit run`, `tox`, etc.

   Mirror CI’s choice of tools and substantive arguments (line length, profiles, config files) when running locally after edits. If CI uses **ruff** (or another tool) instead of flake8/Black/isort, follow CI for that project rather than forcing this skill’s default stack.

3. **Fallback (nothing configured)** — If there is **no** usable in-repo lint/format config and **no** CI clues for Python linting, do **not** default to flake8 + Black + isort. Prefer **ruff** on changed files:

   ```bash
   ruff check path/to/changed_file.py
   ruff format path/to/changed_file.py
   ```

   Run `ruff check` again after `ruff format` if needed until clean. Use conservative defaults (no extra ignores) unless the user asks. If **ruff** is not installed, install it when practical (`pip install ruff` or project toolchain); only if ruff truly cannot be used, fall back to the flake8 / isort / Black flow in the sections below.

## After any Python change

Treat this section as **project-defined tooling**. If **Fallback (nothing configured)** applies, use **ruff** there and skip subsections 1–3 below unless you had to fall back from ruff.

1. **flake8** — On every `.py` file you modified in this turn, run flake8 and fix reported issues before considering the task done.

   ```bash
   flake8 path/to/changed_file.py
   ```

   If no project config applies and you need an explicit line length, you may use `flake8 --max-line-length 119 path/to/changed_file.py` as a last resort.

   If multiple files changed, pass all of them (or the smallest sensible scope, e.g. the package directory you touched). Respect discovered flake8 config; do not override with ad-hoc ignores unless the user asks.

2. **isort** — Only for files that were already isort-compliant **before** your edits (or when the project standard is clearly isort per discovered config or CI — e.g. `[tool.isort]` in `pyproject.toml`, `isort` in `.pre-commit-config.yaml`, or an `isort` step in GitHub Actions / GitLab CI — then treat matching import style as expected for new/edited files unless the user says otherwise):

   - **Establish baseline** — Before you change a file, run:

     ```bash
     isort --check-only path/to/file.py
     ```

     If exit code is 0, treat that file as “isort baseline: yes.” If you cannot run a pre-edit check, infer from repo signals and CI as in **Before running any lint or format tool**.

   - **After your edits** — For every file with isort baseline “yes” (or inferred project standard), run isort, then continue with Black (if applicable) and flake8. Prefer **`isort path/to/file.py`** so discovered `pyproject.toml` / `.isort.cfg` applies. When the project uses **Black** and config does not already set it, pass **`--profile black`** (or set `profile = "black"` in `pyproject.toml`) so import layout stays compatible with Black.

     ```bash
     isort path/to/file.py
     ```

     If the project does not use Black, omit `--profile black` unless CI or config requires it.

   - **If `isort --check-only` failed before your edit** — Do not run isort to resort the whole file’s imports unless the user asked to sort imports or adopt isort. Still run flake8 and fix issues.

3. **Black** — Only for files that were already Black-compliant **before** your edits:

   - **Establish baseline** — Before you change a file, run a check that respects project config, for example:

     ```bash
     black --check path/to/file.py
     ```

     If exit code is 0, treat that file as “Black baseline: yes.” If you cannot run a pre-edit check (e.g. single-shot edit), infer from discovered config or CI: `[tool.black]` in `pyproject.toml`, `black` in `.pre-commit-config.yaml`, or a `black` job in GitHub Actions / GitLab CI — for those projects, assume new/edited files should match Black unless the user says otherwise.

   - **After your edits** — For every file with Black baseline “yes” (or inferred project standard above), run Black on that file **after** isort (when you ran isort on that file), then re-run flake8:

     ```bash
     black path/to/file.py
     flake8 path/to/file.py
     ```

     Use explicit `--target-version` or other flags only when they match discovered `pyproject.toml`, pre-commit, or CI (e.g. if CI runs `black --target-version py311`, mirror that).

   - **If `black --check` failed before your edit** — Do not run Black to reformat the whole file unless the user asked to format or adopt Black. Still run flake8 and fix issues.

## Order of operations

1. **Discover** lint/format expectations (in-repo config, then CI if needed), as in **Before running any lint or format tool**.
2. Edit the Python file(s).
3. **Branch:**
   - **Nothing configured** (no usable repo config and no CI lint hints) — Run **`ruff check`** and **`ruff format`** on changed `.py` files; repeat until `ruff check` is clean. If ruff cannot be used, fall through to the flake8 / isort / Black steps in **After any Python change**.
   - **Something configured** (ruff, flake8, Black, isort, pre-commit, tox, or CI) — Follow that stack. If the stack is **only** ruff in config or CI, use **`ruff check`** / **`ruff format`** per discovered settings. If the stack is **flake8 / isort / Black** (or a subset), follow subsections 1–3 in **After any Python change**: when using explicit baselines, you already know whether `isort --check-only` and `black --check` passed pre-edit; for each changed file run **isort** (if applicable) → **Black** (if applicable) → **flake8**; fix flake8 findings and re-run flake8 after isort or Black.

## Tools missing

If **ruff** is missing in the unconfigured case, prefer installing it (`pip install ruff` or the project’s dev extra). If `flake8`, `isort`, or `black` is required by the project stack and not installed, say so and suggest installing them (e.g. `pip install flake8 isort black` or the project’s dev extra). Prefer using the project’s documented toolchain (venv, poetry, pipenv) when known.
