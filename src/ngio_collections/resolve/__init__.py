"""L3 resolution: gather documents (async) then build a `NodeTree` (pure).

`fetch_all` is the async shell; `build` is the pure, synchronous core that turns
the gathered documents into an immutable `NodeTree`, optionally inlining
cross-document references. See `ngio-v5-architecture`.
"""

from __future__ import annotations

from ngio_collections.resolve._build import Docs, OnError, build
from ngio_collections.resolve._document import Document, Kind, wrap_payload
from ngio_collections.resolve._fetch import fetch_all, reference_targets
from ngio_collections.resolve._serialize import node_dict, payload
from ngio_collections.resolve._write import write_document

__all__ = [
    "Docs",
    "Document",
    "Kind",
    "OnError",
    "build",
    "fetch_all",
    "node_dict",
    "payload",
    "reference_targets",
    "wrap_payload",
    "write_document",
]
