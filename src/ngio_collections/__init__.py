"""ngio_collections: functional, immutable OME-Zarr collection metadata.

Targets RFC-8 **revision 1** (the Fall 2026 proposal): typed `traits` instead
of free-form attributes, UUID ids, typed `{type, ref}` references,
`{type, format, href}` paths, multiscales that are always their own document
(`coordinate_systems` + `scales`, no `singlescale` nodes) and URI-typed
extensions declared in a per-document `extension_manifest`. One deliberate
deviation: `absolute` and `http` paths are resolved, not only `relative` ones,
so collections can point at existing data without bundling it.

The in-memory model is an immutable, indexed `NodeTree` of `NodeRecord`s; you hold
a `Node` handle into it. Reads (`walk` / `find` / lenses) return located handles;
edits return a new tree. `open` reads one editable document (external nodes stay
declaring entries); `open_resolved` follows paths across documents into a
read-only view. Writing is single-document (`create` / `save` / `externalize`).

The whole public surface (the verbs, the `Node` handles, the store backends, and
the value models) is re-exported here from `ngio_collections.api`. This top
level IS the public API: the subpackages (`graph`, `resolve`, `io`, `models`,
`validate`) are internal layout and may be reorganized without notice.

pydantic is optional (`pip install 'ngio-collections[validate]'`): the core
imports and runs without it, while the typed value models (`WellTrait`, `Scale`,
…), the `node[Trait]` lenses and the schema-shape validators are resolved
lazily and raise `ImportError` without it. `from ngio_collections import *`
touches every name and therefore needs the extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ngio_collections import api as _api

if TYPE_CHECKING:
    from ngio_collections.api import *  # noqa: F403

__all__ = list(_api.__all__)

for _name in __all__:
    if _name not in _api.PYDANTIC_NAMES:
        globals()[_name] = getattr(_api, _name)
del _name


def __getattr__(name: str):  # noqa: D103  (PEP 562: forward the pydantic models)
    if name in __all__:
        value = getattr(_api, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
