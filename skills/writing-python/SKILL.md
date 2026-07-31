---
name: writing-python
description: >-
  Writes and edits Python modules, CLIs, libraries, and tests with workspace coding
  standards: prefer Click over argparse for new CLIs, typed dataclasses, pathlib,
  from __future__ import annotations, and brief caveman-lite comments/docstrings.
  After any Python change, follows run-python-static-code-analysis (ruff/flake8/Black/isort
  per project config). Use when creating or modifying Python code, Click CLIs, ai-tools
  helpers, argparse migrations, or Python packaging entry points.
---

# Python edits: standards, Click CLIs, and lint

## When this applies

Creating or changing **Python** (modules, packages, CLIs, tests). Prefer this skill
for **authoring conventions**; always finish with
[run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md) for
the lint/format gate.

Match **existing file and package conventions** first (import style, naming,
logging, test layout). The rules below apply especially to **new** code and to
`ai-tools/tools` helpers; do not rewrite unrelated argparse CLIs unless the user
asked or you are already editing that entry point.

---

## Comments and docstrings (caveman lite)

All comments and docstrings are **brief and to the point**. Style matches
[caveman **lite**](https://github.com/JuliusBrussee/caveman/blob/main/skills/caveman/SKILL.md):
no filler or hedging; keep articles and full sentences; professional but tight.
Technical terms, API names, and error strings stay exact.

| Do | Don't |
|----|--------|
| One short sentence for the purpose | Restate the function name in prose |
| Note non-obvious constraints, units, side effects | Narrate every line ("increment i by one") |
| `# Merge-base vs origin/main for lint scope.` | `# Basically we just really need to find the merge base here so that…` |
| `"""Clone PR/MR under reviews path; list changed files."""` | Multi-paragraph essays that repeat the signature |

**Module docstring** — one or two tight sentences: what the module does, any
important boundary (CLI vs library).

**Public functions / classes / Click commands** — one line when behavior is clear
from the name + types; add a second sentence only for non-obvious returns, raises,
or side effects. Prefer a single summary line over Args/Returns/Raises sections
unless the project already uses that format nearby.

**Inline comments** — only when the *why* is non-obvious. Delete comments that
duplicate the code. Do not add decorative banners or section-divider comment blocks
in new code.

**Click `help=` strings** — same lite tone: short, concrete, no hedging.

Examples:

```python
# Bad
def prepare_review(reference: str) -> ReviewCheckout:
    """This function is responsible for preparing a review checkout by cloning
    the pull request or merge request if needed and then computing the set of
    files that changed relative to the default branch so that linters can run.
    """

# Good
def prepare_review(reference: str) -> ReviewCheckout:
    """Clone or refresh a PR/MR under the reviews root; return changed files."""
```

```python
# Bad — narrates the code
# Loop through each path and check if it exists on disk
for path in paths:
    ...

# Good — only if the why matters
# Refuse paths outside *reviews* so agents cannot clone into arbitrary trees.
assert_reviews_path(dest)
```

When editing existing verbose docstrings in files you already touch, tighten them
to lite style. Do not drive-by rewrite unrelated modules for voice alone.

---

## Prefer Click over argparse

For **new** command-line tools, use **Click** — not `argparse`.

| Do | Don't |
|----|--------|
| `import click` and `@click.command` / `@click.group` | New `argparse.ArgumentParser` |
| `click.Path(path_type=Path, …)` for filesystem args | Manual `type=Path` + ad-hoc validation only |
| `is_flag=True` for booleans | `action="store_true"` in new CLIs |
| `click.Choice([...])` for enums | Hand-rolled choice lists on argparse |
| `raise click.ClickException(...)` (set `exit_code` when needed) | `print(..., file=sys.stderr); return 2` as the only error path |
| Console `main()` that calls `cli.main(..., standalone_mode=False)` and maps exit codes | Only `if __name__ == "__main__": cli()` with no testable entry point |

### CLI shape (ai-tools style)

Single command:

```python
@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("reference")
@click.option("--root", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
@click.option("-q", "--quiet", is_flag=True)
def cli(reference: str, root: Path | None, as_json: bool, quiet: bool) -> None:
    """One-line summary for --help."""
    ...


def main(argv: list[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="my-tool", standalone_mode=False)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 130
    return 0
```

Subcommands: use `@click.group()` plus `@cli.command("name")` (see `beetlejuice`).

Wire the entry point in `pyproject.toml`:

```toml
[project.scripts]
my-tool = "mypackage.my_module:main"
```

Declare **`click>=8`** in project dependencies when adding a Click CLI.

### Migrating argparse

When editing an existing argparse CLI in scope of the task, **convert it to Click**
rather than extending argparse — unless the surrounding package standard is
explicitly argparse-only and the user forbids migration.

---

## Coding standards

Follow nearby code; for new modules (especially under `ai-tools/tools`) prefer:

1. **`from __future__ import annotations`** at the top of every new module.
2. **Type hints** on public functions and Click command parameters (`Path | None`,
   `list[str]`, etc.).
3. **`pathlib.Path`** for filesystem paths; resolve/expand user paths at boundaries.
4. **`@dataclass`** (or `frozen=True` where values are immutable keys) for structured
   results; expose `to_dict()` via `dataclasses.asdict` when JSON output is needed.
5. **Small pure helpers** + one orchestration function; keep Click commands thin
   (parse → call library → print).
6. **Explicit errors**: domain `SomethingError(RuntimeError)` for library code;
   map to `click.ClickException` (and a stable `exit_code`) at the CLI boundary.
7. **Subprocess**: prefer `subprocess.run(..., capture_output=True, text=True)` with
   checked return codes; do not shell out through `shell=True` unless required.
8. **No secrets** in source; read tokens from the environment like sibling tools.
9. **Tests**: `unittest` under `tests/` for parsers, path safety, and CLI exit
   mapping; mock network/subprocess at the boundary.
10. **Comments / docstrings**: caveman **lite** — brief, full sentences, no filler
    (see **Comments and docstrings** above).

Avoid: bare `except:`, mutable default args, importing `*` , new argparse parsers,
and reformatting unrelated files.

---

## Lint and format (required after edits)

After **any** Python change in this turn, follow
[run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md)
**immediately** (discover project config / CI, then ruff or flake8/isort/Black as
that skill directs). Do not mark the task done while lint/format fails on files
you changed.

Summary of that skill’s gate (details live there):

1. Discover in-repo / CI lint config — do not invent flags that fight the project.
2. Fallback when nothing is configured: `ruff check` + `ruff format` on changed files.
3. Otherwise: project stack (ruff-only, or flake8 → isort → Black as applicable).

---

## Order of operations

1. Match existing package layout and naming (`ai_tools/`, tests, `pyproject.toml` scripts).
2. Implement library logic (typed, pathlib, dataclasses).
3. Add or update the **Click** CLI (not argparse); keep `main()` returning an exit code.
4. Add/adjust unit tests for pure helpers and safety rails.
5. Run **run-python-static-code-analysis** on every touched `.py` file until clean.

---

## Related

| Skill / tree | Role |
|--------------|------|
| [run-python-static-code-analysis](../run-python-static-code-analysis/SKILL.md) | Lint/format after Python edits |
| [caveman lite](https://github.com/JuliusBrussee/caveman/blob/main/skills/caveman/SKILL.md) | Voice reference for comments/docstrings |
| [writing-ansible](../writing-ansible/SKILL.md) | Ansible YAML (not Python) |
| `ai-tools/tools/ai_tools/clone_review.py`, `beetlejuice.py` | Reference Click CLIs |
| `ai-tools/tools/README.md` | How to install and document approved tools |
