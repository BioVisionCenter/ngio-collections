"""Tests for `fingerprint`: canonical content hashing of JSON documents."""

from __future__ import annotations

import pytest

from ngio_collections.api import fingerprint


def test_stable_across_key_order_and_whitespace() -> None:
    a = b'{"b": 1, "a": {"x": [1, 2]}}'
    b = b'{\n  "a": {"x": [1,2]},\n  "b": 1\n}'
    assert fingerprint(a) == fingerprint(b)


def test_stable_across_non_ascii_escaping() -> None:
    # orjson keeps non-ASCII verbatim where the stdlib escapes it; the
    # fingerprint must not care which backend wrote the bytes.
    escaped = b'{"name": "caf\\u00e9"}'
    verbatim = '{"name": "café"}'.encode()
    assert fingerprint(escaped) == fingerprint(verbatim)


def test_differs_on_content_change() -> None:
    assert fingerprint(b'{"a": 1}') != fingerprint(b'{"a": 2}')


def test_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        fingerprint(b"not json")
