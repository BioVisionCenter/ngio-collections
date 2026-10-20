"""Resolution: gather documents (async) then build a `NodeTree` (pure).

`fetch_all` is the async shell; `build` is the pure, synchronous core that turns
the gathered documents into an immutable `NodeTree`, optionally resolving
external nodes across document boundaries. `payload` / `write_document` are the
inverse for one document.
"""

from __future__ import annotations

from ngio_collections.resolve._build import (
    CycleError,
    Docs,
    IdMismatchError,
    OnError,
    TypeMismatchError,
    build,
)
from ngio_collections.resolve._document import Document, Kind, wrap_payload
from ngio_collections.resolve._fetch import (
    fetch_all,
    reference_targets,
    trait_reference_targets,
)
from ngio_collections.resolve._jsonrefs import is_path_object, relativize_paths
from ngio_collections.resolve._manifest import derive_manifest, used_extension_types
from ngio_collections.resolve._serialize import (
    EmbeddedMultiscaleError,
    node_dict,
    payload,
)
from ngio_collections.resolve._write import write_document

__all__ = [
    "CycleError",
    "Docs",
    "Document",
    "EmbeddedMultiscaleError",
    "IdMismatchError",
    "Kind",
    "OnError",
    "TypeMismatchError",
    "build",
    "derive_manifest",
    "fetch_all",
    "is_path_object",
    "node_dict",
    "payload",
    "reference_targets",
    "relativize_paths",
    "trait_reference_targets",
    "used_extension_types",
    "wrap_payload",
    "write_document",
]
