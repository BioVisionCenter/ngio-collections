"""Lazy, async, non-mutating resolver over a URL-addressed store.

`open` reads exactly one metadata document into an editable tree (cross-document
references stay `RefNode` stubs). `open_inlined` resolves those path-based stubs
across document boundaries — loading each target document and merging its *root*
into the stub's position — into a read-only `InlinedNode` tree; a stub's
attributes overlay the resolved target on read (stub wins) and ids are
namespaced by ancestor path. Inlining is a read-only operation: it builds a new
tree and never mutates the parsed source or the cache, and it cannot be written
back through its origins.

Writing is single-document. `create` writes a detached tree to a new file;
`save` writes an opened tree back to its own document; `save_inlined` snapshots
an inlined tree to one self-contained file. Each returns a `RefNode` so the
written node can be composed into a parent in another document. `delete` removes
a node from its on-disk document, unlinking the file only when it is left empty.
"""

from __future__ import annotations

import json
from typing import Literal, cast, overload

from ngio_collections.treeops import (
    assert_unique_ids,
    build_inlined,
    namespace_ids,
)
from ngio_collections.io._document import MetadataDocument
from ngio_collections.io._serialize import (
    _assign_document,
    _classify_url,
    _doc_payload,
    _node_from_payload,
    _ref_target,
)
from ngio_collections.io.store import (
    LocalStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)
from ngio_collections.models._config import NodeStateError
from ngio_collections.models._nodes import (
    BaseNode,
    InlinedNode,
    Node,
    RefNode,
    ReferenceObj,
    rebuild,
    remove,
    stub_to,
)
from ngio_collections.models._paths import meta_url as _clean_url


class Resolver:
    """Async resolver that opens, inlines, and persists OME collection trees.

    Maintains a URL-keyed document cache so repeated reads of the same URL cost
    only one IO call. The cache is not thread-safe; use one `Resolver` per
    event loop (or per `_sync` background loop).
    """

    def __init__(self, store: ReadableStore | None = None) -> None:
        """Initialise the resolver with an optional backing store.

        Args:
            store: The store to use for all IO; defaults to :class:`LocalStore`.
        """
        self.store = store if store is not None else LocalStore()
        # URL-keyed document cache: the single source of resolution state.
        self._cache: dict[str, MetadataDocument] = {}

    async def _open_document(self, url: str) -> MetadataDocument:
        """Fetch and cache the document at `url`; return cached copy if loaded."""
        url = _clean_url(url)
        if url in self._cache:
            return self._cache[url]
        doc_class = _classify_url(url)
        payload = await self.store.get(url=url)
        doc = doc_class(content=json.loads(payload), store=self.store, url=url)
        self._cache[url] = doc
        return doc

    async def _resolve_node(self, url: str) -> Node:
        """Parse one document into an editable node tree (stubs left in place).

        Args:
            url: Document URL to fetch and parse.

        Returns:
            The root `Node` with `_document` stamped on every descendant.
        """
        doc = await self._open_document(url)
        node = _node_from_payload(doc.deserialize_payload(doc.content))
        _assign_document(node, doc)
        return node

    @overload
    async def open(self, source: str) -> Node: ...
    @overload
    async def open(self, source: ReferenceObj) -> BaseNode: ...
    async def open(self, source: str | ReferenceObj) -> Node | BaseNode:
        """Open a document as an editable tree, stubs left in place.

        Reads exactly one document (no boundary inlining): every cross-document
        reference stays a `RefNode` stub. The result is editable and writable
        single-document via :meth:`save`.

        Args:
            source: A document URL (returns its root `Node`), or a
                `ReferenceObj` (opens the document it locates and returns the
                node whose `id` matches).

        Returns:
            The root `Node` for a URL, or the referenced node for a
            `ReferenceObj` (stubs intact in both cases).

        Raises:
            KeyError: If `source` is a `ReferenceObj` whose `id` is absent from
                the document it locates.
        """
        if isinstance(source, ReferenceObj):
            url, node_id = _ref_target(source)
            root = await self._resolve_node(url)
            node = root.find(id=node_id)
            if node is None:
                raise KeyError(f"reference {node_id!r} not found in document {url!r}")
            return node
        return await self._resolve_node(_clean_url(source))

    @overload
    async def open_inlined(
        self,
        source: str,
        depth: int | None = ...,
        on_error: Literal["skip", "raise"] = ...,
    ) -> InlinedNode: ...
    @overload
    async def open_inlined(
        self,
        source: ReferenceObj,
        depth: int | None = ...,
        on_error: Literal["skip", "raise"] = ...,
    ) -> BaseNode: ...
    async def open_inlined(
        self,
        source: str | ReferenceObj,
        depth: int | None = None,
        on_error: Literal["skip", "raise"] = "skip",
    ) -> InlinedNode | BaseNode:
        """Resolve a tree across document boundaries into a read-only tree.

        Each resolvable path-based `RefNode` is replaced by the root of the
        document at its path (the stub and that root must share a `type`), with
        the stub's attributes overlaid (stub wins) and the child's name winning.
        Node ids are then namespaced by ancestor path (e.g. `root.child`) for
        global uniqueness, each node keeping its origin id for `ref()`. Builds a
        NEW `InlinedNode` tree bottom-up; the parsed source and cache are never
        mutated. Cycles, depth-exhausted hops, type mismatches, and unreadable
        targets are left as stubs.

        Args:
            source: An entry-point document URL (returns the inlined root), or a
                `ReferenceObj` (inlines the document it locates and returns the
                inlined node matching its origin id).
            depth: Maximum boundary hops to follow; `None` = unlimited,
                `0` = root only (no inlining).
            on_error: `"skip"` leaves unresolvable stubs in place; `"raise"`
                propagates the failure.

        Returns:
            The read-only inlined root for a URL, or the referenced inlined node
            for a `ReferenceObj`.

        Raises:
            ValueError: If duplicate node ids remain after inlining.
            KeyError: If `source` is a `ReferenceObj` whose `id` is absent from
                the inlined tree.
        """
        if isinstance(source, ReferenceObj):
            url, node_id = _ref_target(source)
        else:
            url, node_id = _clean_url(source), None
        root = await self._resolve_node(url)
        assert root._document is not None
        inlined = await self._inline_tree(
            root, depth, on_error, frozenset({root._document.url})
        )
        # Inlining merges several documents into one (ids unique only per
        # source); namespace ids to make them globally unique by ancestor path.
        inlined = cast("InlinedNode", namespace_ids(inlined))
        assert_unique_ids(inlined)  # safety net (namespacing guarantees this)
        if node_id is not None:
            # ids are now namespaced; match the referenced node by its origin
            # (its real id within `url`).
            node = next(
                (
                    n
                    for n in inlined.walk()
                    if n._origin_id == node_id
                    and n._document is not None
                    and n._document.url == url
                ),
                None,
            )
            if node is None:
                raise KeyError(f"reference {node_id!r} not found in document {url!r}")
            return node
        return inlined

    async def _inline_tree(
        self,
        node: BaseNode,
        depth: int | None,
        on_error: Literal["skip", "raise"],
        ancestors: frozenset[str],
    ) -> InlinedNode | RefNode:
        """Convert an editable node into its inlined mirror, resolving stubs."""
        if isinstance(node, RefNode):
            return await self._resolve_ref(node, depth, on_error, ancestors)
        children = getattr(node, "nodes", ()) or ()
        new_children = tuple(
            [
                await self._inline_tree(child, depth, on_error, ancestors)
                for child in children
            ]
        )
        return build_inlined(node, new_children)

    async def _resolve_ref(
        self,
        stub: RefNode,
        depth: int | None,
        on_error: Literal["skip", "raise"],
        ancestors: frozenset[str],
    ) -> InlinedNode | RefNode:
        """Resolve a path-based `RefNode` stub to the root of its target document.

        RFC-8 stubs are path-based: the document at the stub's path is opened and
        its *root* node is merged into the stub's position. The merged node keeps
        the child's id / type / nodes; its name is the child's (falling back to
        the stub's), and the stub's attributes overlay the child's (stub wins).
        The stub and the child root must share the same `type`.
        """
        if depth == 0:
            return stub  # hop budget exhausted -> leave the stub
        try:
            target_url = _clean_url(stub.resolve_path())
        except Exception:
            if on_error == "raise":
                raise
            return stub
        if target_url in ancestors:
            return stub  # cycle -> leave as stub
        try:
            target_root = await self._resolve_node(target_url)
        except Exception:
            if on_error == "raise":
                raise
            return stub  # data leaf / not-an-ome-doc -> leave as stub
        if stub.type != target_root.type:
            if on_error == "raise":
                raise TypeError(
                    f"stub type {stub.type!r} does not match the type "
                    f"{target_root.type!r} of the root node at {target_url!r}"
                )
            return stub
        next_depth = None if depth is None else depth - 1
        inlined = await self._inline_tree(
            target_root, next_depth, on_error, ancestors | {target_url}
        )
        # Merge the stub into the resolved child: name child-wins (fall back to
        # the stub), attributes stub-wins (the parent decorates the child).
        updates: dict[str, object] = {}
        if inlined.name is None and stub.name is not None:
            updates["name"] = stub.name
        if stub.attributes:
            updates["attributes"] = {**inlined.attributes, **stub.attributes}
        if updates:
            inlined = inlined.model_copy(update=updates)
        return inlined

    async def create(
        self,
        destination: str,
        root: Node,
        *,
        overwrite: bool = False,
        relativize: bool = True,
    ) -> RefNode:
        """Write a freshly built (DETACHED) tree to a NEW document at `destination`.

        Stamps `root` with its document (state changes to DOCUMENT) so later
        edits + :meth:`save` round-trip. The form (JSON / Zarr) is inferred from
        `destination`; the OME payload is stamped with `VERSION`.

        Args:
            destination: Destination document URL (JSON or Zarr inferred from
                suffix).
            root: A DETACHED node tree to persist.
            overwrite: If `False` (default), raise when a document already
                exists at `destination`.
            relativize: If `True` (default), rewrite co-located local stub paths
                relative to this document; `http` / cross-directory paths are
                kept verbatim. Pass `False` to store every path as-is.

        Returns:
            A typed `RefNode` stub locating `root` in the new document.

        Raises:
            NodeStateError: If `root` is already backed by a document (use
                :meth:`save`), or a document exists at `destination` and
                `overwrite` is `False`.
        """
        if not root.is_detached:
            raise NodeStateError(
                f"tree is already backed by {root.document_url!r}; use "
                "Resolver.save(node) to persist edits, not create()"
            )
        self._writable_store()  # fail fast before any work
        destination = _clean_url(destination)
        if not overwrite and await self._exists(destination):
            raise NodeStateError(
                f"a document already exists at {destination!r}; open it and use "
                "Resolver.save(node), or pass overwrite=True"
            )
        assert_unique_ids(root)
        doc = _classify_url(destination)(
            content={}, store=self.store, url=destination
        )
        _assign_document(root, doc)
        self._cache[destination] = doc
        payload = doc.serialize_payload(_doc_payload(root, doc, relativize), {})
        await self._save_document(destination, payload)
        return stub_to(root, doc)

    async def save(self, node: BaseNode, *, relativize: bool = True) -> RefNode:
        """Write an edited node back into ITS document.

        Single-document: only `node`'s own document is (re)written, and only if
        its serialized payload changed. A document-root node rewrites the whole
        document; a descendant (e.g. one returned by `open` from a `ReferenceObj`)
        is spliced back into its document by id, leaving siblings and ancestors
        untouched. Cross-document `RefNode` stubs are left as references.

        Args:
            node: A document-backed node (root or descendant) carrying edits.
            relativize: If `True` (default), rewrite co-located local stub paths
                relative to this document; `http` / cross-directory paths are
                kept verbatim. Pass `False` to store every path as-is.

        Returns:
            A typed `RefNode` stub locating `node` in its document.

        Raises:
            NodeStateError: If `node` is inlined (use :meth:`save_inlined`), has
                no backing document (use :meth:`create`), or no longer exists in
                its document on disk.
        """
        if isinstance(node, InlinedNode):
            raise NodeStateError(
                f"node {node.id!r} is inlined (read-only); use "
                "Resolver.save_inlined(view, url) to snapshot it"
            )
        if node.is_detached:
            raise NodeStateError(
                "node has no backing document; use Resolver.create(url, root) to "
                "write a new collection first"
            )
        doc = node._document
        assert doc is not None
        # Splice the edited node into a fresh parse of its document so siblings
        # and ancestors are preserved (mirrors delete()).
        doc_root = _node_from_payload(doc.deserialize_payload(doc.content))
        node_id = getattr(node, "id", None)
        if node_id is None:
            raise NodeStateError("cannot save a path-based stub; it has no id")
        if doc_root.id == node_id:
            new_root: BaseNode = node  # node IS the document root
        else:
            new_root, found = rebuild(doc_root, node_id, lambda _n: node)
            if not found:
                raise NodeStateError(
                    f"node {node_id!r} is not in document {doc.url!r}; it may have "
                    "been removed or renamed on disk"
                )
        assert_unique_ids(new_root)
        new_content = doc.serialize_payload(
            _doc_payload(cast("Node", new_root), doc, relativize), doc.content
        )
        if new_content != doc.content:
            await self._save_document(doc.url, new_content)
        return stub_to(node, doc)

    async def save_inlined(
        self,
        view: InlinedNode,
        destination: str,
        *,
        overwrite: bool = False,
        relativize: bool = True,
    ) -> RefNode:
        """Snapshot an inlined tree into ONE self-contained document at `destination`.

        Every resolved boundary is embedded inline; only stubs left un-inlined
        (depth / cycle / open error) stay as path references. The inlined tree's
        origins are untouched.

        Args:
            view: The read-only inlined tree to flatten.
            destination: Destination document URL (JSON or Zarr inferred from
                suffix).
            overwrite: If `False` (default), raise when a document already
                exists at `destination`.
            relativize: If `True` (default), rewrite co-located local stub paths
                relative to this document; `http` / cross-directory paths are
                kept verbatim. Pass `False` to store every path as-is.

        Returns:
            A typed `RefNode` stub locating the snapshot's root in the new document.

        Raises:
            NodeStateError: If a document exists at `destination` and `overwrite`
                is `False`.
        """
        self._writable_store()
        destination = _clean_url(destination)
        if not overwrite and await self._exists(destination):
            raise NodeStateError(
                f"a document already exists at {destination!r}; pass overwrite=True"
            )
        assert_unique_ids(view)
        doc = _classify_url(destination)(
            content={}, store=self.store, url=destination
        )
        self._cache[destination] = doc
        payload = doc.serialize_payload(_doc_payload(view, doc, relativize), {})
        await self._save_document(destination, payload)
        return stub_to(view, doc)

    async def delete(self, node: BaseNode) -> list[str]:
        """Remove `node` from its on-disk document, unlinking the file if empty.

        Re-reads the node's document, removes the node by id, and writes the
        document back. If `node` is the document's root (so nothing remains), the
        file is deleted instead. Idempotent.

        Args:
            node: A document-backed node to delete.

        Returns:
            The URL(s) affected (written or deleted); empty if nothing changed.

        Raises:
            NodeStateError: If `node` is detached (it has no document on disk).
        """
        node_id = getattr(node, "id", None)
        if node.is_detached:
            raise NodeStateError(
                f"node {node_id!r} is detached; there is nothing on disk to delete"
            )
        if node_id is None:
            raise NodeStateError("cannot delete a path-based stub; it has no id")
        store = self._writable_store()
        doc = node._document
        assert doc is not None
        root = _node_from_payload(doc.deserialize_payload(doc.content))
        if root.id == node_id:
            await store.delete(doc.url)
            self._cache.pop(doc.url, None)
            return [doc.url]
        new_root, found = remove(root, node_id)
        if not found:
            return []
        new_content = doc.serialize_payload(
            _doc_payload(new_root, doc, relativize=True), doc.content
        )
        await self._save_document(doc.url, new_content)
        return [doc.url]

    async def _save_document(self, url: str, content: dict) -> None:
        """Write `content` at `url` and refresh the in-memory cache entry.

        Args:
            url: Document URL to write.
            content: Full document dict to serialise as JSON.
        """
        store = self._writable_store()
        await store.put(url, json.dumps(content, indent=2).encode())
        cached = self._cache.get(url)
        if cached is not None:
            cached.content = content

    async def _exists(self, url: str) -> bool:
        """Return `True` if a document exists at `url` (cache or store)."""
        if url in self._cache:
            return True
        try:
            await self.store.get(url=url)
        except FileNotFoundError:
            return False
        return True

    def _writable_store(self) -> WritableStore:
        """Return the store cast to `WritableStore`, or raise if read-only."""
        store = self.store
        if not isinstance(store, WritableStore) or getattr(store, "read_only", False):
            raise StoreReadOnlyError(f"store {type(store).__name__!r} cannot write")
        return store
