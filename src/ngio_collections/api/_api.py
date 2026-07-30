"""The async public API: open, inline, create, save, snapshot, delete.

Each verb composes the lower layers — `fetch_all` (async) then `build` (pure) to
read, `write_document` to write — and returns a `Node` handle. Reading stamps
`origin_url` on every record (so opened nodes are document-backed); `create` /
`save` / `save_inlined` write one document and return a reference stub `Node` you
can compose into a parent with `add_ref`.
"""

from __future__ import annotations

from ngio_collections.api._node import (
    Node,
    _reference_stub,
    reference_path,
    wrap_node,
)
from ngio_collections.graph import ROOT, NodeRecord, Reference
from ngio_collections.io.store import (
    LocalStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)
from ngio_collections.models._config import NodeStateError
from ngio_collections.models._paths import meta_url
from ngio_collections.models._references import ReferenceObj
from ngio_collections.resolve import OnError, build, fetch_all, write_document


def _store(store: ReadableStore | None) -> ReadableStore:
    """Return `store` or a default `LocalStore`."""
    return store if store is not None else LocalStore()


def _writable(store: ReadableStore) -> WritableStore:
    """Return `store` as a `WritableStore`, or raise if it cannot write."""
    if not isinstance(store, WritableStore) or getattr(store, "read_only", False):
        raise StoreReadOnlyError(f"store {type(store).__name__!r} cannot write")
    return store


async def _exists(store: ReadableStore, url: str) -> bool:
    """Return whether a document exists at `url`."""
    try:
        await store.get(url=url)
    except FileNotFoundError:
        return False
    return True


async def open(source: str, store: ReadableStore | None = None) -> Node:
    """Open one document as an editable tree, cross-document stubs left in place."""
    store = _store(store)
    url = meta_url(source)
    docs = await fetch_all(url, store, depth=0)
    if url not in docs:
        raise FileNotFoundError(url)
    return wrap_node(build(url, docs, inline=False), ROOT)


async def open_inlined(
    source: str,
    store: ReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> Node:
    """Open a document and inline resolvable references into a read-only tree."""
    store = _store(store)
    url = meta_url(source)
    docs = await fetch_all(url, store, depth=depth)
    if url not in docs:
        raise FileNotFoundError(url)
    return wrap_node(
        build(url, docs, inline=True, depth=depth, on_error=on_error), ROOT
    )


def _ref_url(ref: ReferenceObj, base_url: str | None) -> str:
    """Resolve a `ReferenceObj` to the absolute URL of the document it points at.

    Raises:
        NodeStateError: If `ref` carries no path (an intra-document reference);
            locate it locally on the owning tree with `node.find(ref.id)`.
    """
    if ref.path is None:
        raise NodeStateError(
            f"reference to {ref.id!r} has no path; it points within its own "
            "document — locate it locally with node.find(ref.id)"
        )
    return ref.path.resolve(base_url)


def _locate(root: Node, ref: ReferenceObj, url: str) -> Node:
    """Find the node `ref.id` within the tree at `root`, or raise."""
    node = root.find(ref.id)
    if node is None:
        raise LookupError(f"no node with id {ref.id!r} in document {url!r}")
    return node


async def open_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: ReadableStore | None = None,
) -> Node:
    """Open the node subtree a `ReferenceObj` points at, as an editable tree.

    Resolves `ref.path` (relative paths join against `base_url`, the URL of the
    document the reference was read from), opens that document with cross-document
    children left as reference stubs, and returns the handle for the node whose
    local id is `ref.id`. Call `.subtree()` on the result to detach it into its
    own tree.

    Raises:
        NodeStateError: If `ref` carries no path (an intra-document reference).
        FileNotFoundError: If no document exists at the resolved URL.
        LookupError: If `ref.id` is not found in that document.
    """
    store = _store(store)
    url = _ref_url(ref, base_url)
    return _locate(await open(url, store), ref, url)


async def open_inlined_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: ReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> Node:
    """Open the node subtree a `ReferenceObj` points at, references inlined.

    Like `open_ref`, but resolves the target document's own cross-document
    references into one read-only tree (see `open_inlined`) before locating
    `ref.id`.

    Raises:
        NodeStateError: If `ref` carries no path (an intra-document reference).
        FileNotFoundError: If no document exists at the resolved URL.
        LookupError: If `ref.id` is not found in that document.
    """
    store = _store(store)
    url = _ref_url(ref, base_url)
    view = await open_inlined(url, store, depth=depth, on_error=on_error)
    return _locate(view, ref, url)


async def create(
    destination: str,
    root: Node,
    store: ReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
) -> Node:
    """Write a detached tree to a new document; return a reference stub `Node`.

    Raises:
        NodeStateError: If `root` is already document-backed, or a document
            already exists at `destination` and `overwrite` is `False`.
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
    )
    return _reference_stub(root, url)


async def save(
    node: Node, store: ReadableStore | None = None, *, relativize: bool = True
) -> Node:
    """Write an opened tree back into its own document; return a reference stub.

    Single-document: the node's whole document is rewritten (preserving sibling
    keys). Inlined (resolved) trees are read-only — snapshot them with
    `save_inlined` instead.

    Raises:
        NodeStateError: If `node` is inlined or detached.
    """
    store = _store(store)
    if node.tree.mode == "resolved":
        raise NodeStateError(
            "node is inlined (read-only); use save_inlined() to snapshot it"
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
    )
    return _reference_stub(node, url)


async def save_inlined(
    view: Node,
    destination: str,
    store: ReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
) -> Node:
    """Snapshot an inlined tree into one self-contained document; return a stub.

    Raises:
        NodeStateError: If a document already exists at `destination` and
            `overwrite` is `False`.
    """
    store = _store(store)
    url = meta_url(destination)
    if not overwrite and await _exists(store, url):
        raise NodeStateError(
            f"a document already exists at {url!r}; pass overwrite=True"
        )
    await write_document(
        store,
        url,
        view.tree,
        root_id=view.node_id,
        relativize=relativize,
        overwrite=overwrite,
    )
    return _reference_stub(view, url)


async def externalize(
    node: Node,
    destination: str,
    store: ReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
) -> Node:
    """Split `node` out of its document into its own document at `destination`.

    The restructuring verb: writes the subtree at `node` as a new document,
    replaces the node in its tree with a reference stub at the same sibling
    position, saves the node's home document, and returns the updated tree's
    root handle. The composition direction — linking a *detached* child — is
    the plain sequence `create` → `add_ref` → `save`.

    Not atomic: the new document is written first, so if saving the home
    document fails, the new document exists but the home document still embeds
    the subtree (re-running after the failure is safe with `overwrite=True`).

    Raises:
        NodeStateError: If `node` is inlined (read-only), already a reference,
            detached, its document's root (already its own document), or a
            document exists at `destination` and `overwrite` is `False`.
    """
    store = _store(store)
    if node.tree.mode == "resolved":
        raise NodeStateError(
            "node is inlined (read-only); open() its document to restructure it"
        )
    if node.is_reference:
        raise NodeStateError("node is already a reference to its own document")
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
    )
    stub = NodeRecord(
        type=node.type,
        id=node.id,
        name=node.name,
        ref=Reference(path=reference_path(url), id=node.id),
        origin_url=home_url,
    )
    root = wrap_node(node.tree.replace(node.node_id, stub), ROOT)
    await save(root, store, relativize=relativize)
    return root


async def delete(node: Node, store: ReadableStore | None = None) -> list[str]:
    """Remove `node` from its on-disk document, unlinking the file if left empty.

    Operates on the node's *origin* document (re-read fresh), locating the node by
    its local id — so it is correct for an inlined node too, whose in-memory
    position is not its document position. If the node is its document's root, the
    file is deleted. Idempotent.

    Raises:
        NodeStateError: If `node` is detached, or carries no id to locate it by.
    """
    store = _store(store)
    if node.is_detached:
        raise NodeStateError("node is detached; there is nothing on disk to delete")
    if node.id is None:
        raise NodeStateError("node has no id; it cannot be located in its document")
    url = node.document_url
    assert url is not None
    doc_tree = build(url, await fetch_all(url, store, depth=0), inline=False)
    matches = doc_tree.find(node.id)
    if not matches:
        return []
    target = matches[0]
    if target == ROOT:
        await _writable(store).delete(url)
        return [url]
    new = doc_tree.remove(target)
    existing = await store.get(url=url)
    await write_document(
        store, url, new, root_id=ROOT, existing=existing, overwrite=True
    )
    return [url]
