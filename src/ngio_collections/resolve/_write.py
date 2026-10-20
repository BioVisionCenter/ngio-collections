"""Write one document's worth of a `NodeTree` through a store.

The write counterpart to `fetch_all`: serialize the subtree rooted at `root_id`,
derive or accept the document's `extension_manifest`, wrap it in the document
envelope (preserving any `existing` content's siblings), and `put` it. This
writes a single document, the unit `create` / `save` / `externalize` each
target. Multiscales are never embedded, so a collection document only ever
carries declaring entries for its images; there is no multi-document writer.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from ngio_collections.graph import ROOT, NodeId, NodeTree
from ngio_collections.io.store import AsyncWritableStore, StoreReadOnlyError
from ngio_collections.models._manifest import ExtensionRegistry
from ngio_collections.models._paths import meta_url
from ngio_collections.resolve._document import Document, wrap_payload
from ngio_collections.resolve._manifest import derive_manifest
from ngio_collections.resolve._serialize import payload


def _require_writable(store: object) -> AsyncWritableStore:
    """Return `store` as an `AsyncWritableStore`, or raise if it cannot write."""
    if not isinstance(store, AsyncWritableStore) or getattr(store, "read_only", False):
        raise StoreReadOnlyError(f"store {type(store).__name__!r} cannot write")
    return store


async def write_document(
    store: object,
    url: str,
    tree: NodeTree,
    *,
    root_id: NodeId = ROOT,
    relativize: bool = True,
    existing: dict | None = None,
    overwrite: bool = False,
    extension_manifest: Sequence[Mapping] | None = None,
    registry: ExtensionRegistry | None = None,
    strict: bool = True,
) -> str:
    """Serialize the subtree at `root_id` to `url` and write it through `store`.

    Args:
        store: A writable store.
        url: Destination document URL (normalised to its metadata-file URL).
        tree: The tree to serialize from.
        root_id: The node whose subtree becomes the document root.
        relativize: Whether to relativize co-located local paths.
        existing: Current on-disk content to preserve sibling keys (and the
            previously declared manifest entries) from.
        overwrite: Whether to replace a document already at `url`.
        extension_manifest: The manifest to write verbatim; when `None` it is
            derived from the URI types used, `existing`'s manifest and `registry`.
        registry: Known extensions to draw derived manifest entries from.
        strict: Refuse to embed a multiscale (`EmbeddedMultiscaleError`).

    Returns:
        The normalised URL written.

    Raises:
        StoreDuplicateValueError: If a document already exists at `url` and
            `overwrite` is `False`.
        EmbeddedMultiscaleError: With `strict`, if a multiscale would be embedded.
    """
    writable = _require_writable(store)
    url = meta_url(url)
    kind = Document.kind_for(url)
    if extension_manifest is None:
        known: Sequence[Mapping] = ()
        if existing is not None:
            known = Document.from_content(url, existing).extension_manifest
        extension_manifest = derive_manifest(
            tree, root_id, registry=registry, known=known
        )
    body = payload(
        tree,
        root_id=root_id,
        base_url=url,
        relativize=relativize,
        extension_manifest=extension_manifest,
        strict=strict,
    )
    content = wrap_payload(kind, body, existing)
    await writable.put(url, content, overwrite=overwrite)
    return url
