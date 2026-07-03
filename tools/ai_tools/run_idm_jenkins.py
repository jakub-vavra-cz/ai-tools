#!/usr/bin/env python3
"""Upload IdM-CI metadata as a GitLab snippet and print Jenkins trigger params.

Prefer MCP ``user-jenkins`` / ``trigger_build``. ``--trigger`` posts the same
parameters to the Jenkins REST API when MCP is unavailable.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
import shutil
import ssl
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

import click

from ai_tools.jenkins_artifacts import ca_bundle_from_env, jenkins_auth_from_env

DEFAULT_GITLAB_HOST = "gitlab.cee.redhat.com"
DEFAULT_SNIPPET_REPO = "sssd/sssd-qe"
DEFAULT_JENKINS_JOB = "User-Tools/trigger-test-suite-tool"
DEFAULT_JENKINS_URL = "https://jenkins-csb-idmops-ci.dno.corp.redhat.com"
DEFAULT_IDMCI_GITREPO = "https://gitlab.cee.redhat.com/identity-management/idm-ci.git"
DEFAULT_IDMCI_GITBRANCH = "master"
DEFAULT_VISIBILITY = "internal"

# git@host:group/proj.git
SSH_SCP_RE = re.compile(r"^git@([^:]+):(.+)$")
# ssh://git@host/group/proj.git
SSH_URL_RE = re.compile(r"^ssh://git@([^/]+)/(.+)$")


@dataclass(frozen=True)
class JenkinsParamSpec:
    """One User-Tools/trigger-test-suite-tool job parameter."""

    name: str
    help: str
    kind: str = "string"  # string | bool

    @property
    def option(self) -> str:
        return "--" + self.name.lower().replace("_", "-")

    @property
    def dest(self) -> str:
        return self.name.lower()


# Job params from trigger-test-suite-tool / envvar.txt (not secrets or snippet URL).
JENKINS_PARAMS: tuple[JenkinsParamSpec, ...] = (
    JenkinsParamSpec(
        "IDMCI_REPLACE_OS", "os token replacements, e.g. rhel:rhel-10.2|windows:win-2025"
    ),
    JenkinsParamSpec("IDMCI_REPLACE_TOKEN", "TOKEN_ replacements, e.g. SUITE:-k=test_gpo|NAME:gpo"),
    JenkinsParamSpec("IDMCI_COMPOSE_URL", "Compose URL (use with IDMCI_COMPOSE_ID)"),
    JenkinsParamSpec("IDMCI_COMPOSE_ID", "Compose id, e.g. RHEL-8.3.0-20200701.2"),
    JenkinsParamSpec("IDMCI_PROVIDER", "mrack provider: openstack, beaker, aws"),
    JenkinsParamSpec("IDMCI_TEST_REPO_BRANCH", "Branch for the test repository"),
    JenkinsParamSpec("IDMCI_EXTRA_REPO_URL", "Extra yum repo URL or .repo file (comma-separated)"),
    JenkinsParamSpec("IDMCI_EXTRA_REPO_HOST_PATTERN", "Hosts for extra repo (default all:!ad)"),
    JenkinsParamSpec("IDMCI_TEST_COMPOSE_URL", "Pre-verification compose URL (comma-separated)"),
    JenkinsParamSpec("IDMCI_BREW_TASK_ID", "Brew task id for an RPM build"),
    JenkinsParamSpec("IDMCI_MBS_KOJI_TAG", "Module koji-tag"),
    JenkinsParamSpec("IDMCI_SET_IMAGE", "OS:IMAGE pairs, delimiter |"),
    JenkinsParamSpec("IDMCI_COPR", "Upstream copr repo(s)"),
    JenkinsParamSpec("IDMCI_COPR_REDHAT", "Downstream copr repo(s)"),
    JenkinsParamSpec("IDMCI_HAS_RANDOM_DOMAIN", "AD random domain; disable to turn off"),
    JenkinsParamSpec("IDMCI_OPENSTACK_TENANT", "OpenStack tenant (default idm-jenkins-1)"),
    JenkinsParamSpec("IDMCI_BEAKER_ARCH", "Beaker arch: x86_64, aarch64, …"),
    JenkinsParamSpec("IDMCI_K8S_AGENT", "K8s agent template (default jnlp-agent)"),
    JenkinsParamSpec("IDMCI_SUT_LIFETIME", "SUT lifetime when teardown is skipped"),
    JenkinsParamSpec("IDMCI_SUT_OS_VERSION", "SUT OS version / qualification os"),
    JenkinsParamSpec("IDMCI_MRACK_REPO", "mrack git repository URL"),
    JenkinsParamSpec("IDMCI_MRACK_VERSION_BRANCH", "mrack git branch"),
    JenkinsParamSpec("IDMCI_PIPELINE_STAGE_TIMEOUT", "Pipeline stage timeout minutes"),
    JenkinsParamSpec("IDMCI_TEST_OWNER_RECIPIENT", "Test-owner email list"),
    JenkinsParamSpec("IDMCI_ABRT_EMAIL", "ABRT notification email"),
    JenkinsParamSpec("IDMCI_CUSTOM_CONTAINERFILE", "Raw custom bootc Containerfile"),
    JenkinsParamSpec("IDMCI_CUSTOM_CONTAINER_NAME", "Custom bootc container name"),
    JenkinsParamSpec("IDMCI_TARGET_PROJECT", "Release Dashboard target project"),
    JenkinsParamSpec("IDMCI_QUALIFICATION_TYPE", "Qualification type"),
    JenkinsParamSpec("IDMCI_QUALIFICATION_STAGE", "Qualification stage"),
    JenkinsParamSpec("IDMCI_QUALIFICATION_RUN_KEY", "Qualification run key"),
    JenkinsParamSpec("IDMCI_IS_NIGHTLY", "Nightly image", "bool"),
    JenkinsParamSpec("IDMCI_IS_FIPS", "Enable FIPS", "bool"),
    JenkinsParamSpec("IDMCI_IS_STIG", "Enable STIG", "bool"),
    JenkinsParamSpec("IDMCI_IS_PERMISSIVE", "SELinux permissive", "bool"),
    JenkinsParamSpec("IDMCI_IS_SCRATCH_BUILD", "Scratch brew build", "bool"),
    JenkinsParamSpec("IDMCI_SKIP_TEARDOWN", "Keep SUTs after the run", "bool"),
    JenkinsParamSpec("IDMCI_SKIP_ARTIFACT_SERVER", "Skip artifact-server upload", "bool"),
    JenkinsParamSpec("IDMCI_SKIP_POLARION", "Skip Polarion", "bool"),
    JenkinsParamSpec("IDMCI_SKIP_REPORT_PORTAL", "Skip Report Portal", "bool"),
    JenkinsParamSpec("IDMCI_SKIP_RELEASE_DASHBOARD", "Skip Release Dashboard", "bool"),
)

JENKINS_PARAM_BY_NAME = {spec.name: spec for spec in JENKINS_PARAMS}

# Replay from envvar.txt: never copy these into Jenkins parameters.
ENVVAR_FILE_SKIP = frozenset(
    {
        "IDMCI_METADATA_URL",
        "IDMCI_JOB_BASE_NAME",
        "IDMCI_GH_APP_CODE",
        "IDMCI_GATING_MESSAGING",
        "IDMCI_RELEASE_DASHBOARD_URL",
        "DEFAULT_IDMCI_GITREPO",
        "DEFAULT_IDMCI_GITBRANCH",
    }
)
ENVVAR_FILE_SKIP_PREFIXES = ("IDMCI_POLARION_", "DEFAULT_")


class RunIdmJenkinsError(RuntimeError):
    """Fatal error preparing a Jenkins metadata run."""


@dataclass
class IdmciSource:
    """Custom IdM-CI git clone Jenkins should use (both fields required)."""

    gitrepo: str
    gitbranch: str

    def to_dict(self) -> dict[str, str]:
        return {"idmci_gitrepo": self.gitrepo, "idmci_gitbranch": self.gitbranch}


@dataclass
class SnippetInfo:
    """Project snippet created (or dry-run placeholder)."""

    snippet_id: int
    title: str
    web_url: str
    raw_url: str
    file_name: str
    repo: str
    visibility: str
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JenkinsTriggerInfo:
    """Result of POSTing buildWithParameters to Jenkins."""

    job: str
    queue_url: str | None = None
    queue_id: int | None = None
    build_url: str | None = None
    build_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunIdmJenkinsResult:
    """Snippet plus Jenkins parameters (and optional REST trigger result)."""

    jenkins_job: str
    jenkins_parameters: dict[str, str]
    snippet: SnippetInfo
    idmci_gitrepo: str | None = None
    idmci_gitbranch: str | None = None
    trigger: JenkinsTriggerInfo | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["snippet"] = self.snippet.to_dict()
        if self.trigger is not None:
            data["trigger"] = self.trigger.to_dict()
        return data


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def git_url_to_https(url: str) -> str:
    """Turn an SSH git remote into an https URL Jenkins can clone."""
    url = url.strip()
    match = SSH_SCP_RE.match(url)
    if match:
        return f"https://{match.group(1)}/{match.group(2)}"
    match = SSH_URL_RE.match(url)
    if match:
        return f"https://{match.group(1)}/{match.group(2)}"
    return url


def parse_param(value: str) -> tuple[str, str]:
    """Split ``KEY=VALUE``; value may contain further ``=``."""
    if "=" not in value:
        raise RunIdmJenkinsError(f"expected KEY=VALUE, got: {value}")
    key, val = value.split("=", 1)
    key = key.strip()
    if not key:
        raise RunIdmJenkinsError(f"empty parameter name in: {value}")
    return key, val


def skip_envvar_key(name: str) -> bool:
    if name in ENVVAR_FILE_SKIP:
        return True
    return any(name.startswith(prefix) for prefix in ENVVAR_FILE_SKIP_PREFIXES)


def parse_envvar_file(path: Path) -> dict[str, str]:
    """Parse artifact ``envvar.txt`` (KEY=VALUE lines); drop secrets and empties."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise RunIdmJenkinsError(f"envvar file not found: {resolved}")
    raw = resolved.read_bytes()
    if raw.startswith(b"\x1f\x8b"):
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        key = key.strip()
        if not key or skip_envvar_key(key) or val == "":
            continue
        values[key] = val
    return values


def format_param_value(spec: JenkinsParamSpec, value: str) -> str:
    if spec.kind == "bool":
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return "true"
        if lowered in {"false", "0", "no"}:
            return "false"
        raise RunIdmJenkinsError(f"{spec.name} must be true or false, got: {value}")
    return value


def store_jenkins_param(spec: JenkinsParamSpec) -> Any:
    """Click callback: record a set flag on ``ctx.obj``."""

    def _cb(ctx: click.Context, _param: click.Parameter, value: str | None) -> str | None:
        if value not in (None, ""):
            ctx.ensure_object(dict)[spec.name] = format_param_value(spec, value)
        return value

    return _cb


def jenkins_param_options(func: Any) -> Any:
    """Attach ``--idmci-*`` flags for ``JENKINS_PARAMS`` (values on ``ctx.obj``)."""
    for spec in reversed(JENKINS_PARAMS):
        kwargs: dict[str, Any] = {
            "envvar": spec.name,
            "default": None,
            "expose_value": False,
            "callback": store_jenkins_param(spec),
            "help": f"{spec.help} (Jenkins {spec.name})",
        }
        if spec.kind == "bool":
            kwargs["type"] = click.Choice(["true", "false"], case_sensitive=False)
        func = click.option(spec.option, **kwargs)(func)
    return func


def known_from_context(ctx: click.Context) -> dict[str, str]:
    obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    return {key: str(val) for key, val in obj.items()}


def encode_project(repo: str) -> str:
    return quote(repo.strip().strip("/"), safe="")


def snippet_raw_url(payload: Mapping[str, Any], *, host: str, repo: str) -> str:
    """Prefer file raw_url, then snippet raw_url, then web_url/raw."""
    files = payload.get("files")
    if isinstance(files, list) and files:
        first = files[0]
        if isinstance(first, Mapping):
            file_raw = first.get("raw_url")
            if file_raw:
                return str(file_raw)
    raw = payload.get("raw_url")
    if raw:
        return str(raw)
    web = payload.get("web_url")
    if web:
        return str(web).rstrip("/") + "/raw"
    snippet_id = payload.get("id")
    if snippet_id is None:
        raise RunIdmJenkinsError("snippet response missing id and raw_url")
    return f"https://{host}/{repo}/-/snippets/{snippet_id}/raw"


def default_title(metadata: Path) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"idmci-metadata-{metadata.stem}-{stamp}"


def require_metadata(path: Path) -> str:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise RunIdmJenkinsError(f"metadata file not found: {resolved}")
    text = resolved.read_text(encoding="utf-8")
    if not text.strip():
        raise RunIdmJenkinsError(f"metadata file is empty: {resolved}")
    return text


def run_cmd(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        env=merged,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RunIdmJenkinsError(f"{' '.join(argv)} failed: {detail}")
    return proc


def infer_idmci_from_checkout(checkout: Path) -> IdmciSource:
    """Read origin URL + current branch from a local idm-ci git checkout."""
    root = checkout.expanduser().resolve()
    if not root.exists():
        raise RunIdmJenkinsError(f"idm-ci checkout not found: {root}")
    git_dir = root / ".git"
    if not git_dir.exists():
        raise RunIdmJenkinsError(f"not a git checkout (no .git): {root}")
    origin = run_cmd(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
    ).stdout.strip()
    if not origin:
        raise RunIdmJenkinsError(f"origin remote is empty: {root}")
    branch = run_cmd(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
    ).stdout.strip()
    if not branch or branch == "HEAD":
        raise RunIdmJenkinsError(f"detached HEAD in {root}; pass --idmci-gitbranch explicitly")
    return IdmciSource(gitrepo=git_url_to_https(origin), gitbranch=branch)


def resolve_idmci_source(
    *,
    gitrepo: str | None,
    gitbranch: str | None,
    checkout: Path | None,
) -> IdmciSource | None:
    """Build custom IdM-CI source; Jenkins needs both repo and branch to clone."""
    inferred: IdmciSource | None = None
    if checkout is not None:
        inferred = infer_idmci_from_checkout(checkout)
    repo = gitrepo or (inferred.gitrepo if inferred else None)
    branch = gitbranch or (inferred.gitbranch if inferred else None)
    if repo is None and branch is None:
        return None
    if repo and not branch:
        branch = DEFAULT_IDMCI_GITBRANCH
    if branch and not repo:
        repo = DEFAULT_IDMCI_GITREPO
    assert repo is not None and branch is not None
    return IdmciSource(gitrepo=git_url_to_https(repo), gitbranch=branch)


def build_jenkins_parameters(
    *,
    metadata_url: str,
    source: IdmciSource | None,
    extra: Mapping[str, str] | None = None,
    known: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Jenkins job params. ``IDMCI_GITBRANCH`` maps to ``IDMCI_BRANCH``."""
    params: dict[str, str] = {}
    if extra:
        params.update(extra)
    if known:
        params.update(known)
    params["IDMCI_METADATA_URL"] = metadata_url
    if source is not None:
        params["IDMCI_GITREPO"] = source.gitrepo
        params["IDMCI_BRANCH"] = source.gitbranch
    return params


def jenkins_job_url(base_url: str, job: str) -> str:
    """Turn ``Folder/job-name`` into ``{base}/job/Folder/job/job-name``."""
    base = base_url.strip().rstrip("/")
    raw = job.strip().strip("/")
    parts = [p for p in raw.split("/") if p and p != "job"]
    if not parts:
        raise RunIdmJenkinsError(f"empty Jenkins job name: {job!r}")
    return base + "".join(f"/job/{quote(part, safe='')}" for part in parts)


def queue_id_from_url(queue_url: str) -> int | None:
    match = re.search(r"/queue/item/(\d+)/?", queue_url)
    if match:
        return int(match.group(1))
    return None


def parse_queue_executable(payload: Mapping[str, Any]) -> tuple[str | None, int | None]:
    executable = payload.get("executable")
    if not isinstance(executable, Mapping):
        return None, None
    url = executable.get("url")
    number = executable.get("number")
    build_url = str(url) if url else None
    if build_url and not build_url.endswith("/"):
        build_url += "/"
    build_number = int(number) if number is not None else None
    return build_url, build_number


def _ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ca_bundle and Path(ca_bundle).is_file():
        ctx.load_verify_locations(ca_bundle)
    return ctx


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def jenkins_http(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    ca_bundle: str | None = None,
    timeout: float = 60,
) -> tuple[int, dict[str, str], bytes]:
    """HTTP helper for Jenkins REST. Returns status, headers, body."""
    req_headers = dict(headers or {})
    if auth is not None:
        req_headers["Authorization"] = _basic_auth_header(*auth)
    request = Request(url, data=data, headers=req_headers, method=method)
    try:
        with urlopen(request, context=_ssl_context(ca_bundle), timeout=timeout) as resp:
            body = resp.read()
            hdrs = {k: v for k, v in resp.headers.items()}
            return int(resp.status), hdrs, body
    except HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        hdrs = {k: v for k, v in exc.headers.items()} if exc.headers is not None else {}
        return int(exc.code), hdrs, body
    except URLError as exc:
        raise RunIdmJenkinsError(f"Jenkins request failed {url}: {exc}") from exc


def fetch_jenkins_crumb(
    base_url: str,
    *,
    auth: tuple[str, str],
    ca_bundle: str | None,
) -> tuple[str, str] | None:
    """Return ``(header_name, crumb)`` or None if crumbs are disabled."""
    url = base_url.rstrip("/") + "/crumbIssuer/api/json"
    status, _hdrs, body = jenkins_http(url, auth=auth, ca_bundle=ca_bundle)
    if status in {404, 410}:
        return None
    if status != 200:
        detail = body.decode("utf-8", errors="replace")[:200]
        raise RunIdmJenkinsError(f"Jenkins crumb fetch HTTP {status}: {detail}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RunIdmJenkinsError("Jenkins crumb response was not JSON") from exc
    crumb = payload.get("crumb")
    field = payload.get("crumbRequestField") or "Jenkins-Crumb"
    if not crumb:
        return None
    return str(field), str(crumb)


def trigger_jenkins_job(
    job: str,
    parameters: Mapping[str, str],
    *,
    base_url: str = DEFAULT_JENKINS_URL,
    auth: tuple[str, str] | None = None,
    ca_bundle: str | None = None,
    wait_seconds: float = 15,
    poll_interval: float = 1,
) -> JenkinsTriggerInfo:
    """POST ``buildWithParameters``; optionally wait for a build URL."""
    if auth is None:
        auth = jenkins_auth_from_env()
    if auth is None:
        raise RunIdmJenkinsError(
            "set JENKINS_USERNAME and JENKINS_PASSWORD to trigger via the Jenkins API"
        )
    if ca_bundle is None:
        ca_bundle = ca_bundle_from_env()
    base = base_url.strip().rstrip("/")
    crumb = fetch_jenkins_crumb(base, auth=auth, ca_bundle=ca_bundle)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if crumb is not None:
        headers[crumb[0]] = crumb[1]
    post_url = jenkins_job_url(base, job) + "/buildWithParameters"
    body = urlencode(list(parameters.items())).encode()
    status, hdrs, resp_body = jenkins_http(
        post_url,
        method="POST",
        data=body,
        headers=headers,
        auth=auth,
        ca_bundle=ca_bundle,
    )
    if status not in {200, 201}:
        detail = resp_body.decode("utf-8", errors="replace")[:300]
        raise RunIdmJenkinsError(f"Jenkins trigger HTTP {status} for {post_url}: {detail}")
    location = hdrs.get("Location") or hdrs.get("location")
    queue_url = urljoin(base + "/", location) if location else None
    if queue_url and not queue_url.endswith("/"):
        queue_url += "/"
    info = JenkinsTriggerInfo(
        job=job,
        queue_url=queue_url,
        queue_id=queue_id_from_url(queue_url) if queue_url else None,
    )
    if wait_seconds <= 0 or not queue_url:
        return info
    deadline = time.monotonic() + wait_seconds
    while True:
        q_status, _q_hdrs, q_body = jenkins_http(
            urljoin(queue_url, "api/json"),
            auth=auth,
            ca_bundle=ca_bundle,
        )
        if q_status == 200:
            try:
                payload = json.loads(q_body.decode("utf-8"))
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, Mapping):
                build_url, build_number = parse_queue_executable(payload)
                if build_url or build_number is not None:
                    info.build_url = build_url
                    info.build_number = build_number
                    return info
                if payload.get("cancelled"):
                    raise RunIdmJenkinsError(f"Jenkins queue item was cancelled: {queue_url}")
        if time.monotonic() >= deadline:
            return info
        time.sleep(poll_interval)


def create_project_snippet(
    *,
    host: str,
    repo: str,
    title: str,
    description: str,
    file_name: str,
    content: str,
    visibility: str,
) -> dict[str, Any]:
    """POST a project snippet via ``glab api``; return the JSON payload."""
    if not which("glab"):
        raise RunIdmJenkinsError("glab not found on PATH (required for GitLab snippets)")
    body = {
        "title": title,
        "description": description,
        "visibility": visibility,
        "files": [{"file_path": file_name, "content": content}],
    }
    path = f"projects/{encode_project(repo)}/snippets"
    proc = run_cmd(
        [
            "glab",
            "api",
            "--hostname",
            host,
            "--method",
            "POST",
            "--input",
            "-",
            path,
        ],
        input_text=json.dumps(body),
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RunIdmJenkinsError(
            f"glab api returned non-JSON: {(proc.stdout or '')[:200]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RunIdmJenkinsError("glab api returned unexpected snippet payload")
    if payload.get("message") and payload.get("id") is None:
        raise RunIdmJenkinsError(f"GitLab snippet create failed: {payload.get('message')}")
    return payload


def upload_snippet(
    metadata: Path,
    *,
    host: str,
    repo: str,
    title: str | None,
    description: str,
    file_name: str | None,
    visibility: str,
    dry_run: bool,
) -> SnippetInfo:
    content = require_metadata(metadata)
    name = file_name or metadata.name or "metadata.yaml"
    snippet_title = title or default_title(metadata)
    if dry_run:
        placeholder = f"https://{host}/{repo}/-/snippets/0/raw/{name}"
        return SnippetInfo(
            snippet_id=0,
            title=snippet_title,
            web_url=f"https://{host}/{repo}/-/snippets/0",
            raw_url=placeholder,
            file_name=name,
            repo=repo,
            visibility=visibility,
            dry_run=True,
        )
    payload = create_project_snippet(
        host=host,
        repo=repo,
        title=snippet_title,
        description=description,
        file_name=name,
        content=content,
        visibility=visibility,
    )
    snippet_id = int(payload["id"])
    web = str(payload.get("web_url") or f"https://{host}/{repo}/-/snippets/{snippet_id}")
    return SnippetInfo(
        snippet_id=snippet_id,
        title=str(payload.get("title") or snippet_title),
        web_url=web,
        raw_url=snippet_raw_url(payload, host=host, repo=repo),
        file_name=name,
        repo=repo,
        visibility=visibility,
        dry_run=False,
    )


def prepare_run(
    metadata: Path,
    *,
    host: str = DEFAULT_GITLAB_HOST,
    repo: str = DEFAULT_SNIPPET_REPO,
    title: str | None = None,
    description: str = "IdM-CI metadata uploaded by run-idm-jenkins",
    file_name: str | None = None,
    visibility: str = DEFAULT_VISIBILITY,
    jenkins_job: str = DEFAULT_JENKINS_JOB,
    gitrepo: str | None = None,
    gitbranch: str | None = None,
    checkout: Path | None = None,
    extra: Mapping[str, str] | None = None,
    known: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> RunIdmJenkinsResult:
    """Upload metadata snippet and assemble Jenkins MCP parameters."""
    source = resolve_idmci_source(gitrepo=gitrepo, gitbranch=gitbranch, checkout=checkout)
    snippet = upload_snippet(
        metadata,
        host=host,
        repo=repo,
        title=title,
        description=description,
        file_name=file_name,
        visibility=visibility,
        dry_run=dry_run,
    )
    params = build_jenkins_parameters(
        metadata_url=snippet.raw_url,
        source=source,
        extra=extra,
        known=known,
    )
    notes: list[str] = []
    if source is not None:
        notes.append(
            "IDMCI_GITBRANCH is passed to Jenkins as IDMCI_BRANCH "
            "(prepareIdmCI clones only when both IDMCI_GITREPO and IDMCI_BRANCH are set)."
        )
    if dry_run:
        notes.append("dry-run: snippet was not created")
    return RunIdmJenkinsResult(
        jenkins_job=jenkins_job,
        jenkins_parameters=params,
        snippet=snippet,
        idmci_gitrepo=source.gitrepo if source else None,
        idmci_gitbranch=source.gitbranch if source else None,
        notes=notes,
    )


def format_report(result: RunIdmJenkinsResult) -> str:
    lines = [
        f"jenkins_job: {result.jenkins_job}",
        f"snippet_id: {result.snippet.snippet_id}",
        f"web_url: {result.snippet.web_url}",
        f"raw_url: {result.snippet.raw_url}",
        "jenkins_parameters:",
    ]
    for key, value in result.jenkins_parameters.items():
        lines.append(f"  {key}={value}")
    if result.idmci_gitrepo:
        lines.append(f"idmci_gitrepo: {result.idmci_gitrepo}")
    if result.idmci_gitbranch:
        lines.append(f"idmci_gitbranch: {result.idmci_gitbranch}")
    if result.trigger is not None:
        lines.append(f"trigger_queue_url: {result.trigger.queue_url or ''}")
        if result.trigger.build_url:
            lines.append(f"trigger_build_url: {result.trigger.build_url}")
        if result.trigger.build_number is not None:
            lines.append(f"trigger_build_number: {result.trigger.build_number}")
    for note in result.notes:
        lines.append(f"note: {note}")
    return "\n".join(lines) + "\n"


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "metadata",
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.option(
    "--title",
    default=None,
    help="Snippet title (default: idmci-metadata-<stem>-<time>)",
)
@click.option(
    "--description",
    default="IdM-CI metadata uploaded by run-idm-jenkins",
    show_default=True,
    help="Snippet description",
)
@click.option(
    "--filename",
    "file_name",
    default=None,
    help="Filename stored in the snippet (default: metadata basename)",
)
@click.option(
    "--repo",
    envvar="IDMCI_SNIPPET_REPO",
    default=DEFAULT_SNIPPET_REPO,
    show_default=True,
    help="GitLab project for the snippet (GROUP/PROJ)",
)
@click.option(
    "--hostname",
    envvar="GITLAB_HOST",
    default=DEFAULT_GITLAB_HOST,
    show_default=True,
    help="GitLab hostname for glab api",
)
@click.option(
    "--visibility",
    type=click.Choice(["internal", "private", "public"], case_sensitive=False),
    default=DEFAULT_VISIBILITY,
    show_default=True,
    help="Snippet visibility (internal so Jenkins can wget on the corp network)",
)
@click.option(
    "--job",
    default=DEFAULT_JENKINS_JOB,
    show_default=True,
    help="Jenkins job path for trigger_build",
)
@click.option(
    "--idmci-gitrepo",
    envvar="IDMCI_GITREPO",
    default=None,
    help="Custom IdM-CI git URL (Jenkins IDMCI_GITREPO)",
)
@click.option(
    "--idmci-gitbranch",
    envvar="IDMCI_GITBRANCH",
    default=None,
    help="Custom IdM-CI git branch (user-facing IDMCI_GITBRANCH → Jenkins IDMCI_BRANCH)",
)
@click.option(
    "--idmci-checkout",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Local idm-ci checkout; infer origin URL and current branch",
)
@jenkins_param_options
@click.option(
    "--envvar-file",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Load extra Jenkins params from artifact envvar.txt (skips secrets/empty)",
)
@click.option(
    "--param",
    "params",
    multiple=True,
    help="Extra Jenkins parameter KEY=VALUE (repeatable)",
)
@click.option(
    "--trigger",
    is_flag=True,
    help="POST buildWithParameters via Jenkins REST (MCP fallback)",
)
@click.option(
    "--jenkins-url",
    envvar="JENKINS_URL",
    default=DEFAULT_JENKINS_URL,
    show_default=True,
    help="Jenkins base URL for --trigger",
)
@click.option(
    "--trigger-wait",
    type=float,
    default=15,
    show_default=True,
    help="Seconds to wait for a build URL after --trigger (0 skips)",
)
@click.option("-n", "--dry-run", is_flag=True, help="Do not create the snippet or trigger")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
@click.pass_context
def cli(
    ctx: click.Context,
    metadata: Path,
    title: str | None,
    description: str,
    file_name: str | None,
    repo: str,
    hostname: str,
    visibility: str,
    job: str,
    idmci_gitrepo: str | None,
    idmci_gitbranch: str | None,
    idmci_checkout: Path | None,
    envvar_file: Path | None,
    params: tuple[str, ...],
    trigger: bool,
    jenkins_url: str,
    trigger_wait: float,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Upload metadata.yaml as an sssd-qe GitLab snippet; print Jenkins params.

    Default: do not trigger Jenkins. Pass jenkins_parameters to MCP user-jenkins
    trigger_build. If MCP is unavailable, --trigger POSTs the same parameters
    to Jenkins REST (JENKINS_USERNAME / JENKINS_PASSWORD, optional crumb).
    Custom IdM-CI: --idmci-gitrepo / --idmci-gitbranch (Jenkins IDMCI_BRANCH).
    """
    extra: dict[str, str] = {}
    file_repo: str | None = None
    file_branch: str | None = None
    try:
        if envvar_file is not None:
            file_vals = parse_envvar_file(envvar_file)
            file_repo = file_vals.pop("IDMCI_GITREPO", None)
            file_branch = file_vals.pop("IDMCI_BRANCH", None)
            extra.update(file_vals)
        for item in params:
            key, value = parse_param(item)
            extra[key] = value
        result = prepare_run(
            metadata,
            host=hostname,
            repo=repo,
            title=title,
            description=description,
            file_name=file_name,
            visibility=visibility.lower(),
            jenkins_job=job,
            gitrepo=idmci_gitrepo or file_repo,
            gitbranch=idmci_gitbranch or file_branch,
            checkout=idmci_checkout,
            extra=extra,
            known=known_from_context(ctx),
            dry_run=dry_run,
        )
        if trigger:
            if dry_run:
                result.notes.append("dry-run: Jenkins API trigger skipped")
            else:
                result.trigger = trigger_jenkins_job(
                    result.jenkins_job,
                    result.jenkins_parameters,
                    base_url=jenkins_url,
                    wait_seconds=trigger_wait,
                )
                result.notes.append("triggered via Jenkins REST API (not MCP)")
    except RunIdmJenkinsError as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 2
        raise err from exc

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(format_report(result), nl=False)


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="run-idm-jenkins", standalone_mode=False)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted!", err=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
