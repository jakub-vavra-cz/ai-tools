"""Log in to OpenShift via Kerberos/SPNEGO SSO (no browser).

Wraps ocp-sso-token and runs ``oc login`` / ``oc project``. Defaults target the
DnO hub used for local IdM Jenkins; override with flags or env when needed.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import click

from ai_tools.envfile import require_env
from ai_tools.jenkins_artifacts import ca_bundle_from_env

_DEFAULT_IDPS = ("OpenID", "SSO")
_DEFAULT_CA_CANDIDATES = (Path.home() / "git" / "certs" / "combined-certifi.pem",)


class OcLoginSsoError(RuntimeError):
    """Fatal OpenShift SSO login error."""


@dataclass
class OcLoginResult:
    """Outcome of an SSO login (or skip when already authenticated)."""

    user: str
    project: str
    refreshed: bool
    skipped: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def default_api_url() -> str:
    return require_env("OC_LOGIN_SSO_API_URL")


def default_project() -> str:
    return require_env("OC_LOGIN_SSO_PROJECT")


def ensure_ca_bundle() -> Path | None:
    """Set REQUESTS_CA_BUNDLE from env or a known corp bundle if present."""
    existing = ca_bundle_from_env()
    if existing:
        path = Path(existing).expanduser()
        if path.is_file():
            os.environ["REQUESTS_CA_BUNDLE"] = str(path)
            return path
    for candidate in _DEFAULT_CA_CANDIDATES:
        if candidate.is_file():
            os.environ["REQUESTS_CA_BUNDLE"] = str(candidate)
            return candidate
    return None


def run_oc(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["oc", *args]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise OcLoginSsoError(f"oc {' '.join(args)} failed: {detail}")
    return proc


def current_user() -> str | None:
    proc = run_oc(["whoami"], check=False)
    if proc.returncode != 0:
        return None
    user = (proc.stdout or "").strip()
    return user or None


def current_project() -> str | None:
    proc = run_oc(["project", "-q"], check=False)
    if proc.returncode != 0:
        return None
    project = (proc.stdout or "").strip()
    return project or None


def _ocp_oauth_login_cls():
    """Import OcpOAuthLogin or raise a clear install hint."""
    try:
        from ocp_sso_token.ocp_oauth_login import OcpOAuthLogin
    except ImportError as exc:
        raise OcLoginSsoError(
            "ocp-sso-token is required; install with: pip install -e ~/git/ai-tools/tools[ocp]"
        ) from exc
    return OcpOAuthLogin


def fetch_sso_token(
    api_url: str,
    identity_providers: tuple[str, ...],
    *,
    insecure_skip_tls_verify: bool = False,
) -> str:
    """Obtain an OpenShift OAuth token using the current Kerberos TGT."""
    ensure_ca_bundle()
    login = _ocp_oauth_login_cls()(
        api_url,
        insecure_skip_tls_verify=insecure_skip_tls_verify,
    )
    try:
        token = login.token(list(identity_providers))
    except (OSError, ValueError, RuntimeError) as exc:
        raise OcLoginSsoError(f"SSO token request failed: {exc}") from exc
    if not token or not str(token).strip():
        raise OcLoginSsoError("SSO token request returned an empty token")
    return str(token).strip()


def oc_login_with_token(api_url: str, token: str) -> None:
    run_oc(["login", f"--server={api_url}", f"--token={token}"])


def oc_set_project(project: str) -> None:
    run_oc(["project", project])


def login_sso(
    *,
    api_url: str | None = None,
    project: str | None = None,
    identity_providers: tuple[str, ...] = _DEFAULT_IDPS,
    force: bool = False,
    insecure_skip_tls_verify: bool = False,
) -> OcLoginResult:
    """Ensure ``oc`` is authenticated via Kerberos SSO and on *project*."""
    api = api_url or default_api_url()
    ns = project or default_project()

    user = current_user()
    if user and not force:
        cur = current_project()
        if cur != ns:
            oc_set_project(ns)
        return OcLoginResult(user=user, project=ns, refreshed=False, skipped=True)

    token = fetch_sso_token(
        api,
        identity_providers,
        insecure_skip_tls_verify=insecure_skip_tls_verify,
    )
    oc_login_with_token(api, token)
    oc_set_project(ns)
    user = current_user()
    if not user:
        raise OcLoginSsoError("oc login succeeded but whoami is empty")
    return OcLoginResult(user=user, project=ns, refreshed=True, skipped=False)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--server",
    "api_url",
    default=None,
    help="Cluster API URL (default: $OC_LOGIN_SSO_API_URL from ai-tools.env)",
)
@click.option(
    "--project",
    "project",
    default=None,
    help="OpenShift project after login (default: $OC_LOGIN_SSO_PROJECT from ai-tools.env)",
)
@click.option(
    "--identity-providers",
    default=",".join(_DEFAULT_IDPS),
    show_default=True,
    help="Comma-separated OAuth IdP names to try",
)
@click.option(
    "--force",
    is_flag=True,
    help="Always refresh the token even if oc whoami already works",
)
@click.option(
    "--token-only",
    is_flag=True,
    help="Print only the OAuth token (no oc login)",
)
@click.option(
    "--insecure-skip-tls-verify",
    is_flag=True,
    help="Disable TLS verification for the SSO HTTP client (INSECURE)",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
@click.option("-q", "--quiet", is_flag=True, help="No human-readable status line")
def cli(
    api_url: str | None,
    project: str | None,
    identity_providers: str,
    force: bool,
    token_only: bool,
    insecure_skip_tls_verify: bool,
    as_json: bool,
    quiet: bool,
) -> None:
    """Log in to OpenShift with Kerberos SSO (no browser)."""
    idps = tuple(p.strip() for p in identity_providers.split(",") if p.strip())
    if not idps:
        raise click.ClickException("identity-providers must list at least one name")

    try:
        if token_only:
            token = fetch_sso_token(
                api_url or default_api_url(),
                idps,
                insecure_skip_tls_verify=insecure_skip_tls_verify,
            )
            if as_json:
                click.echo(json.dumps({"token": token}))
            else:
                click.echo(token)
            return

        result = login_sso(
            api_url=api_url,
            project=project,
            identity_providers=idps,
            force=force,
            insecure_skip_tls_verify=insecure_skip_tls_verify,
        )
    except OcLoginSsoError as exc:
        err = click.ClickException(str(exc))
        err.exit_code = 1
        raise err from exc

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    elif not quiet:
        action = "refreshed" if result.refreshed else "already logged in"
        click.echo(f"{action}: user={result.user} project={result.project}")


def main(argv: list[str] | None = None) -> int:
    """Console entry point; returns a process exit code."""
    try:
        cli.main(args=argv, prog_name="oc-login-sso", standalone_mode=False)
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
