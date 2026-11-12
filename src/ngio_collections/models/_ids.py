"""Identifiers: free-form id strings for nodes and declarations, plus a minting helper.

Ids follow the ID rules of RFC-8 revision 2: an `id` is any non-empty string of
ASCII letters, digits, `-`, `_` and `.` (`ID_PATTERN`), so short readable ids
(`raw`, `s0`, `well-A1`) and UUIDs are both valid. The revision recommends
UUIDv7 and advises against encoding semantics in an id; `new_id()` mints a
UUIDv7 as the default when the caller does not choose one: it is unique without
coordination and sorts roughly by creation time. Ids are kept as plain strings
throughout the package.
"""

from __future__ import annotations

import os
import re
import time
import uuid

ID_PATTERN = r"^[a-zA-Z0-9_.-]+$"
"""A valid id: one or more ASCII letters, digits, `_`, `.` or `-` (the revision's ID rules)."""

_ID_RE = re.compile(ID_PATTERN)


def is_id(value: object) -> bool:
    """Return whether `value` is a valid id string (matches `ID_PATTERN`).

    Args:
        value: Any object; only `str` values can match.

    Returns:
        `True` iff `value` is a string matching `ID_PATTERN`.
    """
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


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
    """Mint a fresh id: a UUIDv7 string (unique, time-ordered), always a valid id.

    Uses `uuid.uuid7` when the running Python provides it (3.14+) and a small
    RFC 9562 implementation otherwise, so no extra dependency is needed. Any
    string matching `ID_PATTERN` is an equally valid id; this is only the
    default for callers that do not pick one.

    Returns:
        A canonical hyphenated UUID string.
    """
    generated = _uuid7() if _uuid7 is not None else _uuid7_fallback()
    return str(generated)
