"""Identifiers: UUID strings for nodes and declarations, plus a v7 minting helper.

RFC-8 revision 1 (§6) makes `id` required on every declared object (nodes,
scales, coordinate systems, acquisitions) and requires it to be a UUID, with
UUIDv7 recommended so ids sort roughly by creation time. Ids are kept as plain
strings throughout the package: the wire form is the canonical 36-character
hyphenated text, and nothing gains from converting it to `uuid.UUID` objects.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Annotated

from pydantic import Field

UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
"""Canonical hyphenated UUID text, any version."""

_UUID_RE = re.compile(UUID_PATTERN)

UuidStr = Annotated[str, Field(pattern=UUID_PATTERN)]
"""A pydantic string field constrained to the canonical UUID form."""


def is_uuid(value: object) -> bool:
    """Return whether `value` is a canonical hyphenated UUID string.

    Args:
        value: Any object; only `str` values can match.

    Returns:
        `True` iff `value` matches `UUID_PATTERN`.
    """
    return isinstance(value, str) and _UUID_RE.fullmatch(value) is not None


def _uuid7_fallback() -> uuid.UUID:
    """Mint a UUIDv7 (RFC 9562 layout) on Pythons without `uuid.uuid7`."""
    timestamp_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits
    rand_a = (rand >> 68) & 0xFFF  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (timestamp_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand_b
    return uuid.UUID(int=value)


_uuid7 = getattr(uuid, "uuid7", None)


def new_id() -> str:
    """Mint a fresh UUIDv7 string (time-ordered, the revision's recommendation).

    Uses `uuid.uuid7` when the running Python provides it (3.14+) and a small
    RFC 9562 implementation otherwise, so no extra dependency is needed.

    Returns:
        A canonical hyphenated UUID string.
    """
    generated = _uuid7() if _uuid7 is not None else _uuid7_fallback()
    return str(generated)
