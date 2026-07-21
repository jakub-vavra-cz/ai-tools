#!/usr/bin/env python3
"""Scan Python tests (Betelgeuse-style) and emit jira-format dump files.

Walks a local or cloned tree for ``test_*.py`` / ``*_test.py``, collects
``test_*`` functions/methods via AST (expanding ``parametrize`` and
``topology`` variants), reads ``:field:`` docstring metadata (and optional
``polarion.yaml`` defaults), then writes one ``key=value`` dump per variant
for :mod:`ai_tools.import_jira_testcase`.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ai_tools.dump_polarion_testcase import (
    JIRA_KEY_ORDER,
    format_key_value,
    merge_csv_labels,
    polarion_pairs_to_jira,
)

# Docstring field lists, same pattern as pytest-output.
_DOC_FIELD_RE = re.compile(
    r"^:(?P<field>[^:]+):(?P<data>((?!(^:|\n\n)).)*)",
    re.MULTILINE | re.DOTALL,
)
_NUMBERED_ITEM_RE = re.compile(
    r"^(?P<index>\d+)\.(?P<data>((?!^\d+\.).)*)",
    re.MULTILINE | re.DOTALL,
)
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        "build",
        "dist",
        ".eggs",
    }
)


class ScanError(RuntimeError):
    """Scan / mapping error."""


@dataclass
class TestLocation:
    file: str
    line: int


@dataclass
class CollectedTest:
    """One ``test_*`` function or method found in source (possibly expanded)."""

    nodeid: str
    name: str
    path: Path
    lineno: int
    parent_class: str | None
    fields: dict[str, str] = field(default_factory=dict)
    markers: dict[str, list[str]] = field(default_factory=dict)
    docstring: str = ""
    #: Relative module path used for ``{{ item.location.file }}`` templates.
    file_rel: str = ""
    #: Pytest-style param id fragment (e.g. ``root-ssh``), without brackets.
    param_id: str = ""
    #: pytest-mh topology mark name (e.g. ``ad``), without parentheses.
    topology: str = ""
    #: Ordered parametrize values for title/description (arg → display value).
    params: dict[str, str] = field(default_factory=dict)

    @property
    def location(self) -> TestLocation:
        file_rel = self.file_rel or self.nodeid.split("::", 1)[0]
        return TestLocation(file=file_rel, line=self.lineno)

    @property
    def variant_suffix(self) -> str:
        """Pytest-compatible nodeid/title suffix: ``[params] (topology)``."""
        parts: list[str] = []
        if self.param_id:
            parts.append(f"[{self.param_id}]")
        if self.topology:
            parts.append(f"({self.topology})")
        if not parts:
            return ""
        if len(parts) == 1:
            return f" {parts[0]}" if parts[0].startswith("(") else parts[0]
        return f"{parts[0]} {parts[1]}"

    def title_with_params(self, base_title: str) -> str:
        """Append human-readable parameters (and topology) to a title."""
        title = base_title.strip()
        extras: list[str] = []
        if self.params:
            extras.extend(f"{k}={v}" for k, v in self.params.items())
        if self.topology:
            extras.append(f"topology={self.topology}")
        if not extras:
            return title
        return f"{title} [{', '.join(extras)}]"


# SSSD / pytest-mh KnownTopology enum member → topology mark ``name``.
_KNOWN_TOPOLOGY_NAMES: dict[str, str] = {
    "BareClient": "bare_client",
    "Client": "client",
    "GDM": "gdm",
    "GDM_IPA": "gdm_ipa",
    "BareLDAP": "bare_ldap",
    "LDAP": "ldap",
    "LDAP_KRB5": "ldap_krb5",
    "BareIPA": "bareipa",
    "IPA": "ipa",
    "BareAD": "bare_ad",
    "AD": "ad",
    "Samba": "samba",
    "IPATrustAD": "ipa-trust-ad",
    "IPATrustSamba": "ipa-trust-samba",
    "Keycloak": "keycloak",
}

# KnownTopologyGroup member → list of topology mark names.
_KNOWN_TOPOLOGY_GROUPS: dict[str, list[str]] = {
    "AnyBareProvider": ["bare_ad", "bareipa", "bare_ldap", "bare_client"],
    "AnyProvider": ["ad", "ipa", "ldap", "samba"],
    "AnyAD": ["ad", "samba"],
    "AnyDC": ["ad", "samba", "ipa"],
    "IPATrust": ["ipa-trust-ad", "ipa-trust-samba"],
}


@dataclass
class ParametrizeMark:
    argnames: list[str]
    rows: list[tuple[Any, ...]]
    ids: list[str] | None = None


def _literal_value(node: ast.AST) -> tuple[bool, Any]:
    """Return ``(ok, value)`` for a statically known simple literal."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool)) or node.value is None:
            return True, node.value
        return False, None
    if isinstance(node, (ast.List, ast.Tuple)):
        values: list[Any] = []
        for elt in node.elts:
            ok, value = _literal_value(elt)
            if not ok:
                return False, None
            values.append(value)
        return True, tuple(values)
    return False, None


def _parse_argnames(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [part.strip() for part in node.value.split(",") if part.strip()]
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in node.elts:
            if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
                return None
            names.append(elt.value)
        return names
    return None


def _parse_parametrize(dec: ast.AST) -> ParametrizeMark | None:
    """Parse ``@pytest.mark.parametrize(...)`` when values are literals."""
    name = _decorator_name(dec)
    if not name or not name.endswith("parametrize"):
        return None
    if not isinstance(dec, ast.Call) or len(dec.args) < 2:
        return None
    argnames = _parse_argnames(dec.args[0])
    if not argnames:
        return None
    values_node = dec.args[1]
    if not isinstance(values_node, (ast.List, ast.Tuple)):
        return None

    rows: list[tuple[Any, ...]] = []
    for elt in values_node.elts:
        if len(argnames) == 1:
            ok, value = _literal_value(elt)
            if not ok:
                return None
            # Flatten accidental single-element nesting only for scalars.
            if isinstance(value, tuple):
                return None
            rows.append((value,))
        else:
            if not isinstance(elt, (ast.Tuple, ast.List)) or len(elt.elts) != len(
                argnames
            ):
                return None
            row_vals: list[Any] = []
            for cell in elt.elts:
                ok, value = _literal_value(cell)
                if not ok:
                    return None
                row_vals.append(value)
            rows.append(tuple(row_vals))

    ids: list[str] | None = None
    for kw in dec.keywords:
        if kw.arg == "ids" and isinstance(kw.value, (ast.List, ast.Tuple)):
            parsed_ids: list[str] = []
            for id_node in kw.value.elts:
                if not isinstance(id_node, ast.Constant) or not isinstance(
                    id_node.value, str
                ):
                    parsed_ids = []
                    break
                parsed_ids.append(id_node.value)
            if parsed_ids and len(parsed_ids) == len(rows):
                ids = parsed_ids
    return ParametrizeMark(argnames=argnames, rows=rows, ids=ids)


def parse_parametrize_marks(decorator_list: list[ast.expr]) -> list[ParametrizeMark]:
    """Return parametrize marks in pytest application order (bottom → top)."""
    marks: list[ParametrizeMark] = []
    for dec in reversed(decorator_list):
        mark = _parse_parametrize(dec)
        if mark is not None:
            marks.append(mark)
    return marks


def _pytest_id_fragment(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value)
    return re.sub(r"[^\w.\-+]+", "_", str(value))


def _display_param_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value)
    return str(value)


def expand_parametrize_combinations(
    marks: list[ParametrizeMark],
) -> list[tuple[dict[str, str], str]]:
    """Cartesian product of parametrize marks → ``(params, param_id)`` rows.

    *marks* must already be in pytest application order (bottom decorator first).
    """
    if not marks:
        return [({}, "")]

    combinations: list[tuple[dict[str, str], str]] = [({}, "")]
    for mark in marks:
        next_rows: list[tuple[dict[str, str], str]] = []
        for base_params, base_id in combinations:
            for index, row in enumerate(mark.rows):
                params = dict(base_params)
                for name, value in zip(mark.argnames, row):
                    params[name] = _display_param_value(value)
                if mark.ids is not None:
                    frag = mark.ids[index]
                else:
                    frag = "-".join(_pytest_id_fragment(v) for v in row)
                param_id = f"{base_id}-{frag}" if base_id else frag
                next_rows.append((params, param_id))
        combinations = next_rows
    return combinations


def _topology_attr(node: ast.AST) -> tuple[str, str] | None:
    """Return ``(enum_class, member)`` for ``KnownTopology.AD``-style refs."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    return None


def expand_topology_names(decorator_list: list[ast.expr]) -> list[str]:
    """Expand ``@pytest.mark.topology`` into pytest-mh topology mark names."""
    names: list[str] = []
    for dec in decorator_list:
        dec_name = _decorator_name(dec)
        if not dec_name or not dec_name.endswith("topology"):
            continue
        if not isinstance(dec, ast.Call) or not dec.args:
            continue
        arg = dec.args[0]
        attr = _topology_attr(arg)
        if attr is None:
            text = _const_str(arg)
            if text:
                names.append(text)
            continue
        enum_name, member = attr
        if "Group" in enum_name:
            group = _KNOWN_TOPOLOGY_GROUPS.get(member)
            if group:
                names.extend(group)
            else:
                names.append(member.lower())
        else:
            names.append(_KNOWN_TOPOLOGY_NAMES.get(member, member.lower()))
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def _merge_markers(
    class_markers: dict[str, list[str]],
    func_markers: dict[str, list[str]],
) -> dict[str, list[str]]:
    markers = {key: list(values) for key, values in class_markers.items()}
    for key, values in func_markers.items():
        markers.setdefault(key, [])
        for value in values:
            if value not in markers[key]:
                markers[key].append(value)
    return markers


def _make_variant_nodeid(base_nodeid: str, param_id: str, topology: str) -> str:
    if param_id and topology:
        return f"{base_nodeid}[{param_id}] ({topology})"
    if param_id:
        return f"{base_nodeid}[{param_id}]"
    if topology:
        return f"{base_nodeid} ({topology})"
    return base_nodeid


def _expand_collected_test(
    *,
    base_nodeid: str,
    name: str,
    path: Path,
    lineno: int,
    parent_class: str | None,
    fields: dict[str, str],
    markers: dict[str, list[str]],
    docstring: str,
    file_rel: str,
    decorator_list: list[ast.expr],
    class_decorator_list: list[ast.expr] | None = None,
) -> list[CollectedTest]:
    """Expand parametrize + topology into one CollectedTest per variant."""
    all_decorators = list(class_decorator_list or []) + list(decorator_list)

    param_marks = parse_parametrize_marks(class_decorator_list or [])
    param_marks.extend(parse_parametrize_marks(decorator_list))

    param_combos = expand_parametrize_combinations(param_marks)
    topologies = expand_topology_names(all_decorators) or [""]

    tests: list[CollectedTest] = []
    for params, param_id in param_combos:
        for topology in topologies:
            variant_fields = dict(fields)
            base_title = variant_fields.get("title", name)
            variant = CollectedTest(
                nodeid=_make_variant_nodeid(base_nodeid, param_id, topology),
                name=name,
                path=path,
                lineno=lineno,
                parent_class=parent_class,
                fields=variant_fields,
                markers=markers,
                docstring=docstring,
                file_rel=file_rel,
                param_id=param_id,
                topology=topology,
                params=params,
            )
            variant_fields["title"] = variant.title_with_params(base_title)
            tests.append(variant)
    return tests


@dataclass
class PolarionFieldSpec:
    name: str
    required: bool = False
    default: str | None = None
    validate: str | None = None
    transform_pattern: str | None = None
    transform_replace: str = ""
    transform_unless: str | None = None
    format: str | None = None
    multiline: bool | None = None


@dataclass
class PolarionScanConfig:
    """Subset of pytest-output ``polarion.yaml`` used for field defaults."""

    project: str = ""
    tests_url: str = ""
    fields: dict[str, PolarionFieldSpec] = field(default_factory=dict)


def is_test_module(filename: str) -> bool:
    return fnmatch.fnmatch(filename, "test_*.py") or fnmatch.fnmatch(
        filename,
        "*_test.py",
    )


def parse_docstring_fields(docstring: str | None) -> dict[str, str]:
    """Parse ``:field: value`` blocks from a docstring (pytest-output style)."""
    if not docstring:
        return {}
    doc = textwrap.dedent(docstring).strip()
    fields: dict[str, str] = {}
    for match in _DOC_FIELD_RE.finditer(doc):
        key = match.group("field").strip().lower()
        value = textwrap.dedent(match.group("data")).strip()
        fields[key] = value
    return fields


def parse_numbered_list(text: str) -> list[tuple[int, str]]:
    """Parse ``1. …\\n2. …`` lists used by ``:steps:`` / ``:expectedresults:``."""
    if not text or not text.strip():
        return []
    out: list[tuple[int, str]] = []
    for match in _NUMBERED_ITEM_RE.finditer(text.strip()):
        index = int(match.group("index").strip())
        value = textwrap.dedent(match.group("data")).strip()
        out.append((index, value))
    return out


def _const_str(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _decorator_name(node: ast.AST) -> str | None:
    """Return dotted name for a decorator, e.g. ``pytest.mark.importance``."""
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
        return None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _decorator_first_str_arg(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    return _const_str(node.args[0])


def parse_markers(decorator_list: list[ast.expr]) -> dict[str, list[str]]:
    """Extract selected pytest markers from AST decorators."""
    markers: dict[str, list[str]] = {}
    for dec in decorator_list:
        name = _decorator_name(dec)
        if not name:
            continue
        short = name.rsplit(".", 1)[-1]
        if short in {"importance", "topology"} or name.endswith(
            (".importance", ".topology"),
        ):
            value = _decorator_first_str_arg(dec)
            if value is None and isinstance(dec, ast.Call) and dec.args:
                # KnownTopology.AD → "AD" / attribute name
                arg = dec.args[0]
                if isinstance(arg, ast.Attribute):
                    value = arg.attr
                elif isinstance(arg, ast.Name):
                    value = arg.id
            if value:
                key = "importance" if "importance" in short else "topology"
                markers.setdefault(key, []).append(value)
    return markers


def _merge_docstrings(docstrings: list[str | None]) -> dict[str, str]:
    """Merge field dicts; later entries override earlier (function wins)."""
    fields: dict[str, str] = {}
    for doc in docstrings:
        fields.update(parse_docstring_fields(doc))
    return fields


def _read_module_ast(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def _pkginit_docstring(module_path: Path) -> str | None:
    init = module_path.parent / "__init__.py"
    if not init.is_file():
        return None
    try:
        return ast.get_docstring(_read_module_ast(init))
    except (OSError, SyntaxError):
        return None


def collect_tests_from_module(
    path: Path,
    *,
    relative_to: Path,
) -> list[CollectedTest]:
    """Collect ``test_*`` functions/methods from one module (params expanded)."""
    try:
        root = _read_module_ast(path)
    except SyntaxError as exc:
        raise ScanError(f"syntax error in {path}: {exc}") from exc

    try:
        rel = path.resolve().relative_to(relative_to.resolve()).as_posix()
    except ValueError:
        rel = path.name

    module_doc = ast.get_docstring(root)
    pkg_doc = _pkginit_docstring(path)
    tests: list[CollectedTest] = []

    for node in ast.iter_child_nodes(root):
        if isinstance(node, ast.ClassDef):
            class_doc = ast.get_docstring(node)
            class_markers = parse_markers(node.decorator_list)
            for sub in ast.iter_child_nodes(node):
                if not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not sub.name.startswith("test_"):
                    continue
                markers = _merge_markers(
                    class_markers,
                    parse_markers(sub.decorator_list),
                )
                fields = _merge_docstrings(
                    [pkg_doc, module_doc, class_doc, ast.get_docstring(sub)],
                )
                tests.extend(
                    _expand_collected_test(
                        base_nodeid=f"{rel}::{node.name}::{sub.name}",
                        name=sub.name,
                        path=path,
                        lineno=sub.lineno,
                        parent_class=node.name,
                        fields=fields,
                        markers=markers,
                        docstring=ast.get_docstring(sub) or "",
                        file_rel=rel,
                        decorator_list=sub.decorator_list,
                        class_decorator_list=node.decorator_list,
                    )
                )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test_"):
                continue
            fields = _merge_docstrings(
                [pkg_doc, module_doc, ast.get_docstring(node)],
            )
            tests.extend(
                _expand_collected_test(
                    base_nodeid=f"{rel}::{node.name}",
                    name=node.name,
                    path=path,
                    lineno=node.lineno,
                    parent_class=None,
                    fields=fields,
                    markers=parse_markers(node.decorator_list),
                    docstring=ast.get_docstring(node) or "",
                    file_rel=rel,
                    decorator_list=node.decorator_list,
                )
            )
    return tests


def iter_test_modules(path: Path) -> Iterator[Path]:
    path = path.resolve()
    if path.is_file():
        if is_test_module(path.name):
            yield path
        return
    if not path.is_dir():
        raise ScanError(f"path not found: {path}")
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        )
        for filename in sorted(filenames):
            if is_test_module(filename):
                yield Path(dirpath) / filename


def collect_tests(
    path: Path,
    *,
    relative_to: Path | None = None,
) -> list[CollectedTest]:
    root = path.resolve()
    rel_root = (relative_to or (root if root.is_dir() else root.parent)).resolve()
    tests: list[CollectedTest] = []
    for module in iter_test_modules(root):
        tests.extend(collect_tests_from_module(module, relative_to=rel_root))
    return tests


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ScanError(
            f"reading {path} requires PyYAML; install pyyaml or pass "
            "defaults via CLI flags instead",
        ) from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScanError(f"cannot read {path}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — yaml error types vary
        raise ScanError(f"invalid YAML in {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _field_spec(name: str, opts: Any, *, required: bool) -> PolarionFieldSpec:
    if opts is None:
        opts = {}
    if not isinstance(opts, dict):
        opts = {}
    transform = opts.get("transform") or {}
    if not isinstance(transform, dict):
        transform = {}
    return PolarionFieldSpec(
        name=name,
        required=required,
        default=None if opts.get("default") is None else str(opts.get("default")),
        validate=None if opts.get("validate") is None else str(opts.get("validate")),
        transform_pattern=(
            None
            if transform.get("pattern") is None
            else str(transform.get("pattern"))
        ),
        transform_replace=str(transform.get("replace") or ""),
        transform_unless=(
            None
            if transform.get("unless") is None
            else str(transform.get("unless"))
        ),
        format=None if opts.get("format") is None else str(opts.get("format")),
        multiline=opts.get("multiline"),
    )


def load_polarion_config(path: Path) -> PolarionScanConfig:
    """Load pytest-output style ``polarion.yaml`` field defaults."""
    data = _load_yaml(path)
    cfg = PolarionScanConfig(
        project=str(data.get("project") or ""),
        tests_url=str(data.get("tests_url") or ""),
    )
    testcase = data.get("testcase") or {}
    if not isinstance(testcase, dict):
        return cfg
    for section, required in (("required", True), ("optional", False)):
        block = testcase.get(section) or {}
        if not isinstance(block, dict):
            continue
        for name, opts in block.items():
            cfg.fields[str(name)] = _field_spec(str(name), opts, required=required)
    return cfg


def find_polarion_config(start: Path) -> Path | None:
    """Search upward from *start* for ``polarion.yaml``."""
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for directory in [cur, *cur.parents]:
        candidate = directory / "polarion.yaml"
        if candidate.is_file():
            return candidate
        # Prefer repo ``src/tests/polarion.yaml`` style without climbing forever.
        if (directory / ".git").exists():
            break
    return None


def _render_template(template: str, test: CollectedTest, *, tests_url: str) -> str:
    """Minimal Jinja-like substitution for polarion.yaml defaults."""
    loc = test.location
    replacements = {
        "{{ item.id }}": test.nodeid,
        "{{item.id}}": test.nodeid,
        "{{ item.name }}": test.name,
        "{{item.name}}": test.name,
        "{{ item.location.file }}": loc.file,
        "{{item.location.file}}": loc.file,
        "{{ item.location.line }}": str(loc.line),
        "{{item.location.line}}": str(loc.line),
        "{{ tests_url }}": tests_url.rstrip("/"),
        "{{tests_url}}": tests_url.rstrip("/"),
    }
    out = template
    for needle, value in replacements.items():
        out = out.replace(needle, value)
    return out


def _apply_field_spec(
    spec: PolarionFieldSpec,
    raw: str | None,
    test: CollectedTest,
    *,
    tests_url: str,
) -> str | None:
    value = raw
    if value is None and spec.default is not None:
        value = _render_template(spec.default, test, tests_url=tests_url)
    if value is None:
        return None

    multiline = spec.multiline
    if multiline is None:
        multiline = spec.name not in {"title", "id"}
    if not multiline:
        value = " ".join(line.strip() for line in value.splitlines())

    if spec.transform_pattern:
        unless = spec.transform_unless
        if unless is None or not re.match(unless, value):
            value = re.sub(spec.transform_pattern, spec.transform_replace, value)

    if spec.validate and not re.match(spec.validate, value):
        raise ScanError(
            f"field {spec.name!r} failed validate {spec.validate!r} "
            f"for {test.nodeid!r} (value={value!r})",
        )

    if value.lower() in {"true", "false"}:
        value = value.lower()

    if spec.format == "pre" and value and not value.lstrip().startswith("<"):
        value = f"<pre>{value}</pre>"

    return value


def default_caseposneg(name: str) -> str:
    return "negative" if "negative" in name.lower() else "positive"


def _html_escape_text(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_params_description(test: CollectedTest) -> str:
    """HTML block listing parametrized args / topology (pytest-output style)."""
    parts: list[str] = []
    if test.params:
        items = "".join(
            f"<li><strong>{_html_escape_text(k)}</strong>: "
            f"{_html_escape_text(v)}</li>"
            for k, v in test.params.items()
        )
        parts.append(
            "<div><strong>Parametrized arguments:</strong>"
            f"<ul>{items}</ul></div>"
        )
    if test.topology:
        parts.append(f"<pre>Topology: {_html_escape_text(test.topology)}\n</pre>")
    return "".join(parts)


def _is_blank_setup(value: str) -> bool:
    text = re.sub(r"</?pre>", "", value or "", flags=re.I).strip()
    return not text


def build_polarion_pairs(
    test: CollectedTest,
    *,
    config: PolarionScanConfig | None = None,
    tests_url: str = "",
    id_prefix: str = "",
    title_prefix: str = "",
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map a collected test to Polarion-style pairs for ``polarion_pairs_to_jira``."""
    cfg = config or PolarionScanConfig()
    url = tests_url or cfg.tests_url
    meta = dict(test.fields)

    if "caseimportance" not in meta:
        if test.markers.get("importance"):
            meta["caseimportance"] = test.markers["importance"][0].lower()
        else:
            meta["caseimportance"] = "medium"
    if "customerscenario" not in meta:
        # Missing docstring → not a customer scenario.
        meta["customerscenario"] = "false"
    if "title" not in meta:
        meta["title"] = test.name

    nodeid_id = (
        f"{id_prefix.rstrip(':')}::{test.nodeid}" if id_prefix else test.nodeid
    )
    defaults: dict[str, str] = {
        "caseautomation": "automated",
        "caseposneg": default_caseposneg(test.name),
        "testtype": "functional",
        "caselevel": "component",
        "upstream": "no",
        "status": "approved",
        "caseimportance": meta["caseimportance"],
        "customerscenario": meta["customerscenario"],
        "id": nodeid_id,
    }
    if url:
        defaults["automation_script"] = (
            f"{url.rstrip('/')}/{test.location.file}#L{test.lineno}"
        )
    defaults.update({k: v for k, v in (overrides or {}).items() if v})

    pairs: dict[str, str] = {}
    consumed: set[str] = set()

    for name, spec in cfg.fields.items():
        raw = meta.get(name)
        if name == "id":
            # yaml default templates ``{{ item.id }}`` as the pytest nodeid.
            rendered = _apply_field_spec(spec, meta.get("id"), test, tests_url=url)
            if rendered is None and spec.required:
                raise ScanError(f"required field 'id' missing for {test.nodeid!r}")
            if rendered is not None:
                pairs["testCaseID"] = rendered
                pairs["id"] = rendered
            consumed.add("id")
            continue

        if name in {"steps", "expectedresults"}:
            # Optional even when polarion.yaml lists them as required; missing
            # steps/results are flagged with an ``incomplete`` label later.
            rendered = _apply_field_spec(spec, raw, test, tests_url=url)
            if rendered is not None:
                pairs[f"_{name}_raw"] = rendered
            consumed.add(name)
            continue

        # ``:setup:`` is optional even when polarion.yaml lists it as required.
        if name == "setup":
            rendered = _apply_field_spec(
                spec,
                raw if raw is not None else "",
                test,
                tests_url=url,
            )
            if rendered is not None and not _is_blank_setup(rendered):
                pairs[name] = rendered
            consumed.add(name)
            continue

        # ``:requirement:`` is optional; missing values get ``missing_requirement``.
        if name == "requirement":
            rendered = _apply_field_spec(spec, raw, test, tests_url=url)
            if rendered is not None and rendered.strip():
                pairs[name] = rendered
            consumed.add(name)
            continue

        if raw is None and name in defaults and spec.default is None:
            raw = defaults[name]
        rendered = _apply_field_spec(spec, raw, test, tests_url=url)
        if rendered is None:
            if spec.required:
                raise ScanError(
                    f"required field {name!r} missing for {test.nodeid!r}",
                )
            continue
        pairs[name] = rendered
        consumed.add(name)

    # Defaults / docstring fields not covered by polarion.yaml.
    for key, value in defaults.items():
        if key == "id":
            if "testCaseID" not in pairs:
                pairs["testCaseID"] = value
                pairs["id"] = value
            continue
        if key not in pairs:
            pairs[key] = meta.get(key, value) if key in meta else value

    for key, value in meta.items():
        if key in consumed or key in pairs:
            continue
        if key in {"steps", "expectedresults"}:
            pairs[f"_{key}_raw"] = value
            continue
        pairs[key] = value

    if "title" not in pairs:
        pairs["title"] = meta.get("title", test.name)

    # Apply CLI title prefix only when yaml did not already transform title.
    title_transformed = any(
        s.name == "title" and s.transform_pattern for s in cfg.fields.values()
    )
    if title_prefix and not title_transformed:
        if not pairs["title"].startswith(title_prefix):
            pairs["title"] = f"{title_prefix}{pairs['title']}"

    if cfg.project and "project_id" not in pairs:
        pairs["project_id"] = cfg.project

    steps_raw = pairs.pop("_steps_raw", "")
    results_raw = pairs.pop("_expectedresults_raw", "")
    # Also pick up docstring values not routed through yaml field specs.
    if not steps_raw:
        steps_raw = meta.get("steps", "")
    if not results_raw:
        results_raw = meta.get("expectedresults", "")
    steps_text = re.sub(r"</?pre>", "", steps_raw, flags=re.I).strip()
    results_text = re.sub(r"</?pre>", "", results_raw, flags=re.I).strip()
    steps = parse_numbered_list(steps_text)
    results = parse_numbered_list(results_text)
    incomplete = not steps or not results
    if steps or results:
        by_index: dict[int, dict[str, str]] = {}
        for index, value in steps:
            by_index.setdefault(index, {})["step"] = value
        for index, value in results:
            by_index.setdefault(index, {})["expectedResult"] = value
        for index in sorted(by_index):
            for field_name, value in by_index[index].items():
                pairs[f"teststep.{index}.{field_name}"] = value

    if incomplete:
        pairs["tags"] = merge_csv_labels(pairs.get("tags", ""), "incomplete")

    has_requirement = bool(str(pairs.get("requirement", "")).strip())
    if not has_requirement:
        pairs["tags"] = merge_csv_labels(
            pairs.get("tags", ""),
            "missing_requirement",
        )

    if test.docstring and "description" not in pairs:
        prose = _DOC_FIELD_RE.sub("", textwrap.dedent(test.docstring)).strip()
        if prose:
            pairs["description"] = prose

    param_desc = format_params_description(test)
    if param_desc:
        existing = pairs.get("description", "")
        pairs["description"] = (
            f"{param_desc}{existing}" if existing else param_desc
        )

    return pairs


def dump_filename_for_id(work_item_id: str) -> str:
    """Filesystem-safe name derived from testCaseID / nodeid."""
    cleaned = re.sub(r"[^\w.\-]+", "_", work_item_id, flags=re.UNICODE)
    cleaned = cleaned.strip("._") or "testcase"
    return f"{cleaned[:200]}.properties"


def write_jira_dump(pairs: dict[str, str], path: Path) -> None:
    jira = polarion_pairs_to_jira(pairs, polarion_url="")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        format_key_value(jira, key_order=JIRA_KEY_ORDER),
        encoding="utf-8",
    )


def scan_and_write(
    source: Path,
    output_dir: Path,
    *,
    relative_to: Path | None = None,
    polarion_config: Path | None = None,
    auto_polarion_config: bool = True,
    tests_url: str = "",
    id_prefix: str = "",
    title_prefix: str = "",
    overrides: dict[str, str] | None = None,
    dry_run: bool = False,
    strict: bool = False,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Collect tests and write jira-format dumps.

    Returns ``(written_or_ok_rows, skipped_rows)``. Skipped rows include a
    ``reason`` when polarion.yaml required fields are missing (unless
    *strict*, which raises on the first such error).
    """
    cfg: PolarionScanConfig | None = None
    config_path = polarion_config
    if config_path is None and auto_polarion_config:
        config_path = find_polarion_config(source)
    if config_path is not None:
        cfg = load_polarion_config(config_path)

    tests = collect_tests(source, relative_to=relative_to)
    results: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for test in tests:
        try:
            pairs = build_polarion_pairs(
                test,
                config=cfg,
                tests_url=tests_url,
                id_prefix=id_prefix,
                title_prefix=title_prefix,
                overrides=overrides,
            )
        except ScanError as exc:
            if strict:
                raise
            skipped.append(
                {
                    "nodeid": test.nodeid,
                    "id": test.nodeid,
                    "summary": test.fields.get("title", test.name),
                    "path": "",
                    "reason": str(exc),
                }
            )
            continue
        work_id = pairs.get("testCaseID") or pairs.get("id") or test.nodeid
        out_path = output_dir / dump_filename_for_id(work_id)
        row = {
            "nodeid": test.nodeid,
            "id": work_id,
            "summary": pairs.get("title", ""),
            "path": str(out_path),
        }
        if not dry_run:
            write_jira_dump(pairs, out_path)
        results.append(row)
    return results, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a local/cloned Python test tree (Betelgeuse-style AST collect) "
            "and write jira-format key=value dumps for import-jira-testcase. "
            "Reads :field: docstring metadata and optional polarion.yaml defaults."
        ),
    )
    parser.add_argument(
        "source",
        type=Path,
        help="File or directory to scan for test_*.py / *_test.py",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Directory for .properties dumps (required to write; optional with --dry-run/--json)",
    )
    parser.add_argument(
        "--relative-to",
        type=Path,
        help="Root for pytest-style nodeids (default: source dir)",
    )
    parser.add_argument(
        "--polarion-config",
        type=Path,
        help="pytest-output polarion.yaml (default: search upward from source)",
    )
    parser.add_argument(
        "--no-polarion-config",
        action="store_true",
        help="Do not auto-load polarion.yaml",
    )
    parser.add_argument(
        "--tests-url",
        default="",
        help="Base URL for automation_script / URL field "
        "(e.g. https://github.com/org/repo/tree/main/tests)",
    )
    parser.add_argument(
        "--id-prefix",
        default="",
        help="Prefix for testCaseID (e.g. idm-sssd-tc → idm-sssd-tc::nodeid)",
    )
    parser.add_argument(
        "--title-prefix",
        default="",
        help='Prefix for summary/title (e.g. "IDM-SSSD-TC: ")',
    )
    parser.add_argument("--component", default="", help="casecomponent override")
    parser.add_argument("--team", default="", help="subsystemteam override")
    parser.add_argument(
        "--upstream",
        choices=["yes", "no", ""],
        default="",
        help="upstream custom field (yes/no)",
    )
    parser.add_argument(
        "--status",
        default="",
        help="Polarion status (default approved → Jira Active)",
    )
    parser.add_argument("--assignee", default="", help="Assignee email for dump")
    parser.add_argument(
        "--caselevel",
        default="",
        help="caselevel override (e.g. system)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Collect and report without writing files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON summary of collected tests",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on the first test missing polarion.yaml required fields",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.source
    if not source.exists():
        print(f"error: source not found: {source}", file=sys.stderr)
        return 2
    if not args.dry_run and args.output is None and not args.json:
        print("error: -o/--output is required unless --dry-run", file=sys.stderr)
        return 2

    overrides: dict[str, str] = {}
    if args.component:
        overrides["casecomponent"] = args.component
    if args.team:
        overrides["subsystemteam"] = args.team
    if args.upstream:
        overrides["upstream"] = args.upstream
    if args.status:
        overrides["status"] = args.status
    if args.assignee:
        overrides["assignee_email"] = args.assignee
    if args.caselevel:
        overrides["caselevel"] = args.caselevel

    output_dir = args.output or Path(".")
    try:
        results, skipped = scan_and_write(
            source,
            output_dir,
            relative_to=args.relative_to,
            polarion_config=None if args.no_polarion_config else args.polarion_config,
            auto_polarion_config=not args.no_polarion_config,
            tests_url=args.tests_url,
            id_prefix=args.id_prefix,
            title_prefix=args.title_prefix,
            overrides=overrides,
            dry_run=args.dry_run or args.output is None,
            strict=args.strict,
        )
    except ScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "count": len(results),
                    "skipped_count": len(skipped),
                    "tests": results,
                    "skipped": skipped,
                },
                indent=2,
            )
        )
    else:
        action = "would write" if args.dry_run else "wrote"
        print(f"{action} {len(results)} testcase dump(s)")
        for row in results[:20]:
            print(f"  {row['id']}")
        if len(results) > 20:
            print(f"  … and {len(results) - 20} more")
        if skipped:
            print(f"skipped {len(skipped)} test(s) (missing required fields)", file=sys.stderr)
            for row in skipped[:10]:
                print(f"  skip: {row['nodeid']}: {row.get('reason', '')}", file=sys.stderr)
            if len(skipped) > 10:
                print(f"  … and {len(skipped) - 10} more", file=sys.stderr)
    if not results and skipped:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
