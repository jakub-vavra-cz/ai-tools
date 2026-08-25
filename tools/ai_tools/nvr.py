"""Parse RPM NVR/NEVRA strings and compare EVR for pre-verify checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

KNOWN_ARCHES = (
    "x86_64",
    "aarch64",
    "ppc64le",
    "s390x",
    "i686",
    "i386",
    "noarch",
    "src",
)

_VER_CHUNK = re.compile(r"(\d+|[a-zA-Z]+|~|\^)")


class NvrError(ValueError):
    """Invalid NVR/NEVRA string."""


@dataclass(frozen=True)
class NVR:
    """name-version-release (epoch optional, ignored in brew paths)."""

    name: str
    version: str
    release: str
    epoch: str | None = None

    @property
    def nvr(self) -> str:
        return f"{self.name}-{self.version}-{self.release}"


def strip_arch_suffix(raw: str) -> str:
    """Drop ``.rpm`` and a trailing ``.arch`` if present."""
    text = raw.strip()
    if text.endswith(".rpm"):
        text = text[:-4]
    for arch in KNOWN_ARCHES:
        suffix = f".{arch}"
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def parse_nvr(raw: str) -> NVR:
    """Parse NVR or NEVRA. Epoch (``0:name-ver-rel``) is optional."""
    text = strip_arch_suffix(raw)
    epoch: str | None = None
    if ":" in text:
        maybe_epoch, rest = text.split(":", 1)
        if maybe_epoch.isdigit():
            epoch = maybe_epoch
            text = rest
    parts = text.rsplit("-", 2)
    if len(parts) != 3 or not all(parts):
        raise NvrError(f"invalid NVR: {raw!r}")
    name, version, release = parts
    return NVR(name=name, version=version, release=release, epoch=epoch)


def rpmvercmp(left: str, right: str) -> int:
    """Compare RPM version/release strings. Returns -1, 0, or 1."""
    if left == right:
        return 0
    try:
        import rpm

        return int(rpm.labelCompare(("", left, ""), ("", right, "")))
    except ImportError:
        return _rpmvercmp_fallback(left, right)


def compare_evr(left: NVR, right: NVR) -> int:
    """Compare epoch-version-release. Returns -1 (older), 0, or 1 (newer)."""
    try:
        import rpm

        le = left.epoch or "0"
        re_ = right.epoch or "0"
        return int(
            rpm.labelCompare(
                (le, left.version, left.release),
                (re_, right.version, right.release),
            )
        )
    except ImportError:
        for a, b in (
            (left.epoch or "0", right.epoch or "0"),
            (left.version, right.version),
            (left.release, right.release),
        ):
            cmp = _rpmvercmp_fallback(a, b)
            if cmp:
                return cmp
        return 0


def nvr_relation(installed: str | None, wanted: str) -> str:
    """How *installed* NEVRA relates to *wanted* NVR: missing/older/same/newer."""
    if not installed:
        return "missing"
    line = installed.strip().splitlines()[0].strip()
    if not line or "is not installed" in line or line.startswith("package "):
        return "missing"
    try:
        got = parse_nvr(line)
        want = parse_nvr(wanted)
    except NvrError:
        return "missing"
    if got.name != want.name:
        return "missing"
    cmp = compare_evr(got, want)
    if cmp < 0:
        return "older"
    if cmp > 0:
        return "newer"
    return "same"


def _rpmvercmp_fallback(left: str, right: str) -> int:
    """Chunked rpmvercmp when the rpm Python module is unavailable."""
    if left == right:
        return 0
    pa = _VER_CHUNK.findall(left)
    pb = _VER_CHUNK.findall(right)
    for x, y in zip(pa, pb):
        if x == y:
            continue
        if x == "~":
            return -1
        if y == "~":
            return 1
        if x == "^" or y == "^":
            if x == "^" and y == "^":
                continue
            if x == "^":
                return -1
            return 1
        x_num, y_num = x.isdigit(), y.isdigit()
        if x_num and y_num:
            xi, yi = int(x), int(y)
            if xi != yi:
                return 1 if xi > yi else -1
            continue
        if x_num:
            return 1
        if y_num:
            return -1
        if x != y:
            return 1 if x > y else -1
    if len(pa) == len(pb):
        return 0
    if len(pa) > len(pb):
        extra = pa[len(pb)]
        if extra in "~^":
            return -1
        return 1
    extra = pb[len(pa)]
    if extra in "~^":
        return 1
    return -1
