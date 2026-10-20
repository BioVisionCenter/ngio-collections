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
"""

from ngio_collections import api as _api
from ngio_collections.api import *  # noqa: F403

__all__ = list(_api.__all__)
