"""Write one document's worth of a `NodeTree` through a store.

The write counterpart to `fetch_all`: serialize the subtree rooted at `root_id`,
wrap it in the document envelope (preserving any `existing` content's siblings),
and `put` it. This writes a single document — the unit `create` / `save` /
`save_inlined` each target. Regrouping a multi-document (resolved) collection by
`origin_url` to write several documents at once is a future extension that builds
on this primitive.
"""

from __future__ import annotations

from ngio_collections.graph import ROOT, NodeTree, NodeId
from ngio_collections.io.store import StoreReadOnlyError, AsyncWritableStore
from ngio_collections.models._paths import meta_url
from ngio_collections.resolve._document import Document, wrap_payload
from ngio_collections.resolve._serialize import payload


def _require_writable(store: object) -> AsyncWritableStore:
    """Return `store` as a `WritableStore`, or raise if it cannot write."""
    if not isinstance(store, AsyncWritableStore) or getattr(store, "read_only", False):
        raise StoreReadOnlyError(f"store {type(store).__name__!r} cannot write")
    return store


async def write_document(
    store: object,
    url: str,
    collection: NodeTree,
    *,
    root_id: NodeId = ROOT,
    relativize: bool = True,
    existing: dict | None = None,
    overwrite: bool = False,
) -> str:
    """Serialize the subtree at `root_id` to `url` and write it through `store`.

    Args:
        store: A writable store.
        url: Destination document URL (normalised to its metadata-file URL).
        collection: The collection to serialize from.
        root_id: The node whose subtree becomes the document root.
        relativize: Whether to relativize co-located local reference paths.
        existing: Current on-disk content to preserve sibling keys from.
        overwrite: Whether to replace a document already at `url`.

    Returns:
        The normalised URL written.

    Raises:
        StoreDuplicateValueError: If a document already exists at `url` and
            `overwrite` is `False`.
    """
    writable = _require_writable(store)
    url = meta_url(url)
    kind = Document.kind_for(url)
    body = payload(collection, root_id=root_id, base_url=url, relativize=relativize)
    content = wrap_payload(kind, body, existing)
    await writable.put(url, content, overwrite=overwrite)
    return url
