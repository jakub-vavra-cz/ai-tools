"""Gzip helpers shared by artifact and log CLIs."""

from __future__ import annotations

import gzip
from pathlib import Path

GZIP_MAGIC = b"\x1f\x8b"


def maybe_decompress(data: bytes) -> bytes:
    """Return *data*, gunzipping when the payload is gzip-compressed."""
    if data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def is_gzip_payload(data: bytes) -> bool:
    return data.startswith(GZIP_MAGIC)


def write_artifact_bytes(data: bytes, dest: Path) -> None:
    """Write artifact bytes to *dest*, decompressing gzip payloads in place."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(maybe_decompress(data))
