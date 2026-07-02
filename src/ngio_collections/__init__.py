"""ngio_collections: functional, immutable OME-Zarr (RFC-8) collection metadata.

The in-memory model is an immutable, indexed `NodeTree` of `NodeRecord`s; you hold
a `Node` handle into it. Reads (`walk` / `find` / lenses) return located handles;
edits return a new tree. `open` reads one editable document (cross-document stubs
stay references); `open_inlined` resolves references across boundaries into a
read-only tree. Writing is single-document (`create` / `save`), with
`save_inlined` to snapshot a resolved tree.

The whole public surface — the verbs, the `Node` handles, the store backends, and
the value models (attributes, paths, references) — is re-exported here from
`ngio_collections.api`. This top level IS the public API: the subpackages
(`graph`, `resolve`, `io`, `models`, `validate`) are internal layout and may be
reorganized without notice.
"""

from ngio_collections import api as _api
from ngio_collections.api import *  # noqa: F403

__all__ = list(_api.__all__)
