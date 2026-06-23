"""Lazy, async, non-mutating resolver over a URL-addressed store.

Opening a collection reads exactly one metadata document; path-bearing stubs are
fetched only on demand. ``inline`` builds the resolved tree bottom-up (it never
mutates the parsed source or the cache). Saves are document-granular: editing a
node rewrites only its owning document, and an unedited tree writes nothing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal, Type, cast

from ngio_collections._document import (
    VERSION,
    JsonMetadataDocument,
    MetadataDocument,
    ZarrMetadataDocument,
)
from ngio_collections.models._base import (
    AnyNode,
    Node,
    NodeStateError,
    RefNode,
    _set_private,
    assert_unique_ids,
    build_node,
    merge,
    split,
)
from ngio_collections.store import (
    LocalStore,
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)

ZARR_METADATA_FILE = "zarr.json"


def _clean_url(url: str) -> str:
    if url.endswith(ZARR_METADATA_FILE) or url.endswith(".json"):
        return url
    # Anything else is taken to be a Zarr group directory.
    return url.rstrip("/") + "/" + ZARR_METADATA_FILE


def _classify_url(url: str) -> Type[MetadataDocument]:
    if url.endswith(".json") and not url.endswith(ZARR_METADATA_FILE):
        return JsonMetadataDocument
    return ZarrMetadataDocument


def _assign_document(node: AnyNode, doc: MetadataDocument) -> None:
    """Stamp ``doc`` as the owning document of every node in a parsed tree."""
    _set_private(node, "_document", doc)
    for child in getattr(node, "nodes", None) or ():
        _assign_document(child, doc)


def _dump_node(node: AnyNode) -> dict:
    """Serialize one node to its OME-payload dict, re-emitting boundary children
    (merged stubs) as path references.

    None fields and an empty ``attributes`` dict are dropped so an unedited
    document re-serializes identically (only-changed-docs-written relies on it).
    """
    data = node.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude={"nodes"}
    )
    if data.get("attributes") == {}:
        data.pop("attributes")
    children: tuple[AnyNode, ...] | None = getattr(node, "nodes", None)
    if children is None:  # a RefNode leaf: no embedded children
        return data
    dumped: list = []
    for child in children:
        if isinstance(child, Node) and child._origin is not None:
            # A document boundary: re-emit the parent reference (path stub).
            stub, _ = split(child)
            dumped.append(_dump_node(stub))
        else:
            dumped.append(_dump_node(child))
    data["nodes"] = dumped
    return data


def _doc_payload(doc_root: AnyNode) -> dict:
    """The OME payload for the document ``doc_root`` owns. A boundary node is
    rendered as its home (target) layer; a plain root as itself."""
    if doc_root._origin is not None:
        _, home = split(cast("Node", doc_root))
        return _dump_node(home)
    return _dump_node(doc_root)


class Resolver:
    def __init__(self, store: ReadableStore | None = None) -> None:
        self.store = store if store is not None else LocalStore()
        # URL-keyed document cache: the single source of resolution state.
        self._cache: dict[str, MetadataDocument] = {}

    async def _open_document(self, url: str) -> MetadataDocument:
        url = _clean_url(url)
        if url in self._cache:
            return self._cache[url]
        doc_class = _classify_url(url)
        payload = await self.store.get(url=url)
        doc = doc_class(content=json.loads(payload), store=self.store, url=url)
        self._cache[url] = doc
        return doc

    async def _resolve_node(self, url: str) -> Node:
        """Parse one document into a node tree (stubs left in place)."""
        doc = await self._open_document(url)
        node = build_node(doc.deserialize_payload(doc.content))
        _assign_document(node, doc)
        return node

    async def inline(
        self,
        url: str,
        depth: int | None = None,
        on_error: Literal["skip", "raise"] = "skip",
    ) -> Node:
        """Resolve a tree across document boundaries, inlining RefNode stubs.

        Builds a NEW tree bottom-up (the parsed source and cache are never
        mutated): each resolvable RefNode is replaced by ``merge(ref, target)``.
        ``depth`` bounds the hops to follow (``None`` unlimited, ``0`` root only);
        ``on_error="skip"`` leaves an unresolvable stub (data leaf / open
        failure) in place. Cycles are always skipped.
        """
        root = await self._resolve_node(url)
        assert root._document is not None
        root = await self._inline(
            root, depth, on_error, frozenset({root._document.url})
        )
        # Eager: inlining merges several documents into one (ids unique only per
        # source) — surface collisions here, not at save().
        assert_unique_ids(root)
        return root

    async def _inline(
        self,
        node: Node,
        depth: int | None,
        on_error: Literal["skip", "raise"],
        ancestors: frozenset[str],
    ) -> Node:
        children = node.nodes
        if not children:
            return node
        new_children = await asyncio.gather(
            *(self._inline_one(c, depth, on_error, ancestors) for c in children)
        )
        return node.model_copy(update={"nodes": tuple(new_children)})

    async def _inline_one(
        self,
        child: AnyNode,
        depth: int | None,
        on_error: Literal["skip", "raise"],
        ancestors: frozenset[str],
    ) -> AnyNode:
        if isinstance(child, RefNode):
            if depth == 0:
                return child  # hop budget exhausted -> leave the stub
            target_url = _clean_url(child.resolve_path())
            if target_url in ancestors:
                return child  # cycle -> leave as stub
            try:
                target = await self._resolve_node(target_url)
            except Exception:
                if on_error == "raise":
                    raise
                return child  # data leaf / not-an-ome-doc -> leave as stub
            merged = merge(child, target)
            next_depth = None if depth is None else depth - 1
            return await self._inline(
                merged, next_depth, on_error, ancestors | {target_url}
            )
        return await self._inline(child, depth, on_error, ancestors)

    async def open(self, url: str) -> Node:
        """Open the document at ``url`` as a node tree, RefNode stubs left in place.

        Reads exactly one document (no boundary inlining): every cross-document
        reference stays a RefNode stub. Use :meth:`inline` to collapse boundaries
        into one resolved tree.
        """
        return await self._resolve_node(url)

    async def create(
        self,
        url: str,
        root: Node,
        *,
        overwrite: bool = False,
    ) -> Node:
        """Write a freshly built (DETACHED) tree to a NEW document at ``url``.

        Returns ``root`` stamped with its document (now DOCUMENT) so later edits +
        ``save`` round-trip. The form (JSON / Zarr) is inferred from ``url``; the
        OME payload is stamped with ``VERSION``. Raises if ``root`` is already
        backed by a document (use ``save``) or if a document already exists at
        ``url`` and ``overwrite`` is False (``inline`` it and use ``save``).
        """
        if not root.is_detached:
            raise NodeStateError(
                f"tree is already backed by {root.document_url!r}; use "
                "Resolver.save(root) to persist edits, not create()"
            )
        self._writable_store()  # fail fast before any work
        url = _clean_url(url)
        if not overwrite and await self._exists(url):
            raise NodeStateError(
                f"a document already exists at {url!r}; inline it and use "
                "Resolver.save(root), or pass overwrite=True"
            )
        assert_unique_ids(root)
        doc = _classify_url(url)(content={}, store=self.store, url=url)
        _assign_document(root, doc)
        payload = {"version": VERSION, **_doc_payload(root)}
        self._cache[url] = doc
        await self._save_document(url, doc.serialize_payload(payload, {}))
        return root

    async def save(self, root: Node) -> list[str]:
        """Write an opened/created tree back, document-granularly (the inverse of
        inline).

        ``root`` and every boundary node (``_origin`` set) roots its own
        document; each is rebuilt (boundary children re-emitted as path stubs,
        attributes un-merged by origin, unknown keys carried through) and written
        only if its serialized payload changed. Returns the URLs written. Use
        ``create`` for a tree built from scratch.
        """
        if root.is_detached:
            raise NodeStateError(
                "tree has no backing document; use Resolver.create(url, root) to "
                "write a new collection first"
            )
        written: list[str] = []
        for node in root.walk():
            if node is root or node._origin is not None:
                assert node._document is not None
                doc = node._document
                new_content = doc.serialize_payload(_doc_payload(node), doc.content)
                if new_content != doc.content:
                    await self._save_document(doc.url, new_content)
                    written.append(doc.url)
        return written

    async def delete_subtree(self, node: Node) -> list[str]:
        """Delete the on-disk document of every boundary in ``node``'s subtree
        (``node`` itself included if it is a boundary). Call BEFORE removing the
        node in memory, while provenance is intact. Idempotent."""
        store = self._writable_store()
        deleted: list[str] = []
        for descendant in node.walk():
            if descendant._origin is None or descendant._document is None:
                continue
            url = descendant._document.url
            await store.delete(url)
            self._cache.pop(url, None)
            deleted.append(url)
        return deleted

    async def _save_document(self, url: str, content: dict) -> None:
        """Write the full document ``content`` at ``url`` and refresh the cache."""
        store = self._writable_store()
        await store.put(url, json.dumps(content, indent=2).encode())
        cached = self._cache.get(url)
        if cached is not None:
            cached.content = content

    async def _exists(self, url: str) -> bool:
        if url in self._cache:
            return True
        try:
            await self.store.get(url=url)
        except FileNotFoundError:
            return False
        return True

    def _writable_store(self) -> WritableStore:
        store = self.store
        if not isinstance(store, WritableStore) or getattr(store, "read_only", False):
            raise StoreReadOnlyError(f"store {type(store).__name__!r} cannot write")
        return store
