"""The async public API: open, resolve, create, save, externalize, delete.

Each verb composes the lower layers (`fetch_all` (async) then `build` (pure) to
read, `write_document` to write) and returns a `Node` handle. Reading stamps
`origin_url` on every record (so opened nodes are document-backed); `create` /
`save` write one document and return the declaring entry (`stub`) you compose
into a parent with `add_external`. Multiscales are never embedded: an image is
created as its own document first, then linked.
"""

from __future__ import annotations

from typing import Mapping

from ngio_collections.api._extensions import EXTENSIONS
from ngio_collections.api._node import Node, _reference_stub, wrap_node
from ngio_collections.graph import ROOT, NodeRecord, find_declaration
from ngio_collections.io.store import (
    AnyReadableStore,
    AsyncReadableStore,
    AsyncWritableStore,
    StoreReadOnlyError,
    default_store,
)
from ngio_collections.io.store._adapt import as_async
from ngio_collections.models._errors import NodeStateError
from ngio_collections.models._manifest import ExtensionRegistry
from ngio_collections.models._paths import ALL_FORMATS, DocPath, meta_url
from ngio_collections.models._references import ReferenceObj
from ngio_collections.resolve import OnError, build, fetch_all, write_document


def _store(store: AnyReadableStore | None) -> AsyncReadableStore:
    """Return `store` adapted to the async protocol, or the default routed store.

    A sync store (`SyncReadableStore`/`SyncWritableStore`) is wrapped so its
    calls run on a worker thread (see `store._adapt.as_async`), letting every
    verb below stay async-only regardless of which protocol `store` implements.
    """
    return as_async(store) if store is not None else default_store()


def _writable(store: AsyncReadableStore) -> AsyncWritableStore:
    """Return `store` as an `AsyncWritableStore`, or raise if it cannot write."""
    if not isinstance(store, AsyncWritableStore) or getattr(store, "read_only", False):
        raise StoreReadOnlyError(f"store {type(store).__name__!r} cannot write")
    return store


async def _exists(store: AsyncReadableStore, url: str) -> bool:
    """Return whether a document exists at `url`."""
    try:
        await store.get(url=url)
    except FileNotFoundError:
        return False
    return True


async def open(source: str, store: AnyReadableStore | None = None) -> Node:
    """Open one document as an editable tree, external nodes left in place."""
    store = _store(store)
    url = meta_url(source)
    docs = await fetch_all(url, store, depth=0)
    if url not in docs:
        raise FileNotFoundError(url)
    return wrap_node(build(url, docs, inline=False), ROOT)


async def open_resolved(
    source: str,
    store: AnyReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
    formats: frozenset[str] = ALL_FORMATS,
) -> Node:
    """Open a document and resolve its external nodes into one read-only tree.

    The result is a *view*: it is not writable (`save` rejects it) and
    serializing it yields the entry document again, with every resolved node
    collapsed back to its declaring entry.

    Args:
        source: The entry document (a `.json` file or a Zarr group).
        store: The store to read through; defaults to the scheme-routed store.
        depth: Max document hops to resolve (`None` unlimited).
        on_error: `"skip"` leaves unresolvable nodes external; `"raise"` fails.
        formats: Path formats to follow; `CORE_FORMATS` for strict conformance.
    """
    store = _store(store)
    url = meta_url(source)
    docs = await fetch_all(url, store, depth=depth, formats=formats)
    if url not in docs:
        raise FileNotFoundError(url)
    tree = build(
        url, docs, inline=True, depth=depth, on_error=on_error, formats=formats
    )
    return wrap_node(tree, ROOT)


def _ref_url(ref: ReferenceObj, base_url: str | None) -> str:
    """Resolve a `ReferenceObj` to the absolute URL of the document it points at.

    Raises:
        NodeStateError: If `ref` carries no path (a same-document reference);
            resolve it locally with `resolve_ref(node, ref)`.
    """
    if ref.path is None:
        raise NodeStateError(
            f"reference to {ref.ref!r} has no path; it points within its own "
            "document: resolve it locally with resolve_ref(node, ref)"
        )
    return ref.path.resolve(base_url)


def _locate(root: Node, ref: ReferenceObj, url: str) -> Node:
    """Find the node `ref` names within the tree at `root`, or raise."""
    node = root.find(ref.ref)
    if node is None:
        if root.tree.declarations(ref.ref):
            raise TypeError(
                f"{ref.ref!r} is a {ref.type} declaration, not a node; use "
                "resolve_ref(node, ref) on the document's root"
            )
        raise LookupError(f"no node with id {ref.ref!r} in document {url!r}")
    if node.type != ref.type:
        raise LookupError(
            f"node {ref.ref!r} in {url!r} has type {node.type!r}, but the "
            f"reference says {ref.type!r}"
        )
    return node


def resolve_ref(node: Node, ref: ReferenceObj) -> Node | Mapping:
    """Resolve a same-document reference against the tree `node` belongs to.

    Pure, no IO. A reference to a node type returns the `Node`; a reference to
    a nested declaration (a `scale`, `coordinate_system`, `acquisition`, …)
    returns that declaration's raw mapping.

    Raises:
        NodeStateError: If `ref` carries a path; use `open_ref` instead.
        LookupError: If nothing in the tree declares `ref.ref` with `ref.type`.
    """
    if ref.path is not None:
        raise NodeStateError("reference carries a path; open it with open_ref()")
    tree = node.tree
    for key in tree.find(ref.ref):
        if tree.record(key).type == ref.type:
            return wrap_node(tree, key)
    for key in tree.declarations(ref.ref):
        declaration = find_declaration(tree.record(key), ref.ref)
        if declaration is not None and declaration.get("type") == ref.type:
            return declaration
    raise LookupError(f"no {ref.type} with id {ref.ref!r} in this tree")


async def open_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: AnyReadableStore | None = None,
) -> Node:
    """Open the node a cross-document `ReferenceObj` points at, as an editable tree.

    Resolves `ref.path` (relative paths join against `base_url`, the URL of the
    document the reference was read from), opens that document with external
    children left in place, and returns the handle for the node whose UUID is
    `ref.ref` and whose type is `ref.type`.

    Raises:
        NodeStateError: If `ref` carries no path (a same-document reference).
        FileNotFoundError: If no document exists at the resolved URL.
        LookupError: If `ref.ref` is not found, or its type differs.
        TypeError: If `ref` names a nested declaration rather than a node.
    """
    store = _store(store)
    url = _ref_url(ref, base_url)
    return _locate(await open(url, store), ref, url)


async def open_resolved_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: AnyReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> Node:
    """Open the node a `ReferenceObj` points at, with its document resolved.

    Like `open_ref`, but resolves the target document's own external nodes into
    one read-only tree (see `open_resolved`) before locating `ref.ref`.
    """
    store = _store(store)
    url = _ref_url(ref, base_url)
    view = await open_resolved(url, store, depth=depth, on_error=on_error)
    return _locate(view, ref, url)


async def create(
    destination: str,
    root: Node,
    store: AnyReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
    registry: ExtensionRegistry = EXTENSIONS,
) -> Node:
    """Write a detached tree to a new document; return its declaring entry.

    The `extension_manifest` is derived from the URI types the tree uses and the
    extensions registered with `register_extension`.

    Raises:
        NodeStateError: If `root` is already document-backed, or a document
            already exists at `destination` and `overwrite` is `False`.
        EmbeddedMultiscaleError: If the tree embeds a multiscale below its root.
    """
    store = _store(store)
    if not root.is_detached:
        raise NodeStateError(
            f"tree is already backed by {root.document_url!r}; use save(), not create()"
        )
    url = meta_url(destination)
    if not overwrite and await _exists(store, url):
        raise NodeStateError(
            f"a document already exists at {url!r}; open it and save(), or pass overwrite=True"
        )
    await write_document(
        store,
        url,
        root.tree,
        root_id=root.node_id,
        relativize=relativize,
        overwrite=overwrite,
        registry=registry,
    )
    return _reference_stub(root, url)


async def save(
    node: Node,
    store: AnyReadableStore | None = None,
    *,
    relativize: bool = True,
    registry: ExtensionRegistry = EXTENSIONS,
) -> Node:
    """Write an opened tree back into its own document; return its declaring entry.

    Single-document: the node's whole document is rewritten (preserving sibling
    keys and previously declared manifest entries). Resolved views are
    read-only: `open()` the document you want to change.

    Raises:
        NodeStateError: If `node` is a resolved view or detached.
    """
    store = _store(store)
    if node.tree.mode == "resolved":
        raise NodeStateError(
            "node is a resolved view (read-only); open() its document to edit it"
        )
    if node.is_detached:
        raise NodeStateError("node has no backing document; use create() first")
    url = node.document_url
    assert url is not None
    try:
        existing = await store.get(url=url)
    except FileNotFoundError:
        existing = None
    await write_document(
        store,
        url,
        node.tree,
        root_id=ROOT,
        relativize=relativize,
        existing=existing,
        overwrite=True,
        registry=registry,
    )
    return _reference_stub(node, url)


async def externalize(
    node: Node,
    destination: str,
    store: AnyReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
    registry: ExtensionRegistry = EXTENSIONS,
) -> Node:
    """Split `node` out of its document into its own document at `destination`.

    The restructuring verb: writes the subtree at `node` as a new document,
    replaces the node in its tree with its declaring entry at the same sibling
    position, saves the node's home document, and returns the updated tree's
    root handle. The composition direction (linking a *detached* child) is the
    plain sequence `create` → `add_external` → `save`.

    Not atomic: the new document is written first, so if saving the home
    document fails, the new document exists but the home document still embeds
    the subtree (re-running after the failure is safe with `overwrite=True`).

    Raises:
        NodeStateError: If `node` is a resolved view, already external,
            detached, its document's root (already its own document), or a
            document exists at `destination` and `overwrite` is `False`.
    """
    store = _store(store)
    if node.tree.mode == "resolved":
        raise NodeStateError(
            "node is a resolved view (read-only); open() its document to restructure it"
        )
    if node.is_external:
        raise NodeStateError("node is already external (its own document)")
    home_url = node.require_document_url()
    if not node.node_id:
        raise NodeStateError(
            f"node is the root of its document {home_url!r}; it already is its "
            "own document"
        )
    url = meta_url(destination)
    if not overwrite and await _exists(store, url):
        raise NodeStateError(
            f"a document already exists at {url!r}; pass overwrite=True"
        )
    await write_document(
        store,
        url,
        node.tree,
        root_id=node.node_id,
        relativize=relativize,
        overwrite=overwrite,
        registry=registry,
    )
    stub = NodeRecord(
        type=node.type,
        id=node.id,
        name=node.name,
        path=DocPath.for_url(url),
        origin_url=home_url,
    )
    root = wrap_node(node.tree.replace(node.node_id, stub), ROOT)
    await save(root, store, relativize=relativize, registry=registry)
    return root


async def delete(
    node: Node, store: AnyReadableStore | None = None, *, cascade: bool = False
) -> list[str]:
    """Remove `node` from its on-disk document, unlinking the file if left empty.

    Operates on the node's *origin* document (re-read fresh), locating the node by
    its UUID, so it is correct for a resolved node too, whose in-memory position
    is not its document position. If the node is its document's root, the file
    is deleted. With `cascade`, an external node's target document is deleted as
    well (data deletion must be asked for explicitly). Idempotent.

    Returns:
        The URLs of the documents written or deleted.

    Raises:
        NodeStateError: If `node` is detached.
    """
    store = _store(store)
    if node.is_detached:
        raise NodeStateError("node is detached; there is nothing on disk to delete")
    url = node.document_url
    assert url is not None
    affected: list[str] = []
    if cascade and node.record.path is not None:
        target = node.record.path.meta_url(url)
        await _writable(store).delete(target)
        affected.append(target)
    doc_tree = build(url, await fetch_all(url, store, depth=0), inline=False)
    matches = doc_tree.find(node.id)
    if not matches:
        return affected
    target_key = matches[0]
    if target_key == ROOT:
        await _writable(store).delete(url)
        return [*affected, url]
    new = doc_tree.remove(target_key)
    existing = await store.get(url=url)
    await write_document(
        store, url, new, root_id=ROOT, existing=existing, overwrite=True
    )
    return [*affected, url]
