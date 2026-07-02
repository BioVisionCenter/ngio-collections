"""JSON (de)serialization shim with an optional ``orjson`` fast path.

The core stays dependency-free: if ``orjson`` is installed (the ``speedups``
extra) it is used, otherwise we fall back to the standard-library ``json``.

perf: on the write benchmark ``json.dumps`` is ~10% of the cost (~0.2 s for a
~96k-node snapshot); ``orjson`` roughly halves the encode step. It is a small,
optional win — the read path is dominated by node reconstruction, not JSON — so
this is deliberately gated behind an optional import rather than made a hard
dependency (see ``benchmarks/README.md``).

Both back-ends emit the same logical document with 2-space indentation, so a
round-trip parses to identical content. The bytes are not guaranteed identical
across back-ends (``orjson`` keeps non-ASCII verbatim where the stdlib escapes
it), which is why callers compare parsed content, never raw bytes.
"""

from __future__ import annotations

import hashlib
import json as _stdlib_json
from typing import Any

try:
    import orjson  # ty: ignore[unresolved-import]  # optional `speedups` extra

    def loads(data: bytes) -> Any:
        """Parse JSON ``data`` (bytes) into Python objects via ``orjson``."""
        return orjson.loads(data)

    def dumps(obj: Any) -> bytes:
        """Serialize ``obj`` to indented JSON bytes via ``orjson``."""
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)

except ModuleNotFoundError:
    import json

    def loads(data: bytes) -> Any:
        """Parse JSON ``data`` (bytes) into Python objects via stdlib ``json``."""
        return json.loads(data)

    def dumps(obj: Any) -> bytes:
        """Serialize ``obj`` to indented JSON bytes via stdlib ``json``."""
        return json.dumps(obj, indent=2).encode()


def fingerprint(data: bytes) -> str:
    """Return a canonical content hash (sha256 hex) of the JSON document `data`.

    Raw bytes are not stable across serializers (see the module docstring), so
    the hash is taken over a canonical re-encoding of the *parsed* content —
    sorted keys, compact separators, escaped non-ASCII, always via the stdlib
    encoder regardless of the `orjson` fast path. Two documents fingerprint
    equal iff their parsed content is equal, whatever wrote the bytes.

    Raises:
        ValueError: If `data` is not valid JSON (via `json.JSONDecodeError`).
    """
    canonical = _stdlib_json.dumps(
        loads(data), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
