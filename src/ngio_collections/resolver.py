"""Async Resolver: open / resolve / navigate / save collection documents.

The resolver is the only caller of the Store. Resolution never mutates the
parsed tree (DESIGN.md §3.3): the tree stays exactly as parsed, stubs in
place; resolution state lives in the URL-keyed MetadataDocument cache.
"""

from __future__ import annotations

import asyncio
import copy
import json
import posixpath
from typing import Literal
from urllib.parse import urljoin, urlparse

from ngio_collections.document import (
    MetadataDocument,
    MetadataDocumentForm,
    NotOmeDocumentError,
    _assert_unique_ids,
    _set_provenance,
    parse_metadata_document,
)
from ngio_collections.models.base import (
    BaseNode,
    JsonPath,
    PathObj,
    ZarrPath,
    merged_attributes,
)
from ngio_collections.registry import DEFAULT_REGISTRY, NodeRegistry
from ngio_collections.store.protocols import (
    ReadableStore,
    StoreReadOnlyError,
    WritableStore,
)

ZARR_METADATA_FILE = "zarr.json"


def _classify_url(url: str) -> tuple[str, MetadataDocumentForm]:
    """Map a user-facing URL to its metadata-document URL and storage form."""
    if url.endswith(ZARR_METADATA_FILE):
        return url, "zarr"
    if url.endswith(".json"):
        return url, "json"
    # Anything else is taken to be a Zarr group directory.
    return url.rstrip("/") + "/" + ZARR_METADATA_FILE, "zarr"


def _target_doc_url(base_doc_url: str, path: PathObj) -> str:
    """Join a stub's Path against the URL of the document declaring it.

    A relative path is joined with ``urljoin`` semantics; an absolute URL (or
    absolute filesystem path) passes through untouched (DESIGN.md §6).
    """
    target = urljoin(base_doc_url, path.path)
    if isinstance(path, ZarrPath):
        # Spec: implementations MUST append zarr.json to access the metadata.
        return target.rstrip("/") + "/" + ZARR_METADATA_FILE
    return target


def _stub_path_for(doc_url: str, form: MetadataDocumentForm) -> PathObj:
    """The Path with which a parent document references the document at ``doc_url``.

    Inverse of ``_classify_url``: the zarr form is referenced by its group
    directory (resolution re-appends ``zarr.json``), the json form by the
    document URL itself.
    """
    if form == "zarr":
        directory = doc_url.removesuffix(ZARR_METADATA_FILE).rstrip("/")
        return ZarrPath(path=directory)
    return JsonPath(path=doc_url)


def _relativize_url(target: str, base_doc_url: str) -> str | None:
    """Rewrite an absolute ``target`` relative to the document at ``base_doc_url``.

    Inverse of the ``urljoin`` in ``_target_doc_url``: joining the result back
    onto ``base_doc_url`` reproduces ``target``. Returns the path verbatim when
    it is already relative, and ``None`` when relativization is impossible
    (different scheme or host — cross-store references stay absolute,
    DESIGN.md §6). The comparison is textual, so e.g. a ``file://`` target
    against a plain-path base is not relativized.
    """
    target_parts = urlparse(target)
    base_parts = urlparse(base_doc_url)
    if (target_parts.scheme, target_parts.netloc) != (
        base_parts.scheme,
        base_parts.netloc,
    ):
        return None
    if not target_parts.path.startswith("/"):
        return target
    relative = posixpath.relpath(target_parts.path, posixpath.dirname(base_parts.path))
    if not relative.startswith(".."):
        relative = "./" + relative
    return relative


class Resolver:
    """Lazy, async-native resolver over a URL-addressed store.

    Opening a collection reads exactly one metadata document; path-bearing
    stubs are only fetched on demand (DESIGN.md §2.2). Saves are
    document-granular: editing a node rewrites only its owning document.
    """

    def __init__(
        self,
        store: ReadableStore,
        *,
        registry: NodeRegistry = DEFAULT_REGISTRY,
    ) -> None:
        self.store = store
        self.registry = registry
        # URL-keyed document cache: the single source of resolution state.
        self._cache: dict[str, MetadataDocument] = {}

    async def open(self, url: str) -> MetadataDocument:
        """Fetch (or hit cache) and parse the metadata document at ``url``.

        ``url`` may point at a ``*.json`` document, a ``zarr.json`` file, or
        a Zarr group directory (``zarr.json`` is appended).
        """
        doc_url, _ = _classify_url(str(url))
        return await self._load_document(doc_url, stub_path=None)

    async def resolve(self, stub: BaseNode) -> MetadataDocument:
        """Fetch (or hit cache) and return the document a stub points to.

        The stub's relative ``path`` is joined against the URL of the
        declaring document; an absolute URL passes through untouched
        (DESIGN.md §6, cross-store references).
        """
        if stub.path is None:
            document = stub._document
            if document is not None and document.root is stub:
                return document  # already a resolved document root
            raise ValueError(f"node {stub.id!r} has no 'path'; nothing to resolve")
        if stub._document is None:
            raise ValueError(
                f"node {stub.id!r} is detached (no owning document); relative "
                "paths need the declaring document's URL — resolve nodes from "
                "a tree opened by this resolver"
            )
        doc_url = _target_doc_url(stub._document.url, stub.path)
        return await self._load_document(doc_url, stub_path=stub.path)

    async def children(self, node: BaseNode) -> list[BaseNode]:
        """The node's children, stubs transparently replaced by their
        resolved document roots. Does not mutate ``node``."""
        children = getattr(node, "nodes", None) or []
        resolved: list[BaseNode] = []
        for child in children:
            if isinstance(child, BaseNode) and child.path is not None:
                resolved.append((await self.resolve(child)).root)
            else:
                resolved.append(child)
        return resolved

    async def resolve_tree(
        self,
        doc: MetadataDocument,
        *,
        max_depth: int | None = None,
        on_error: Literal["skip", "raise"] = "skip",
    ) -> list[MetadataDocument]:
        """Resolve every metadata document reachable from ``doc``.

        Breadth-first cache warming: each round fetches one frontier of
        path stubs concurrently. The parsed trees are never mutated
        (DESIGN.md §3.3) — stubs stay in place; afterwards ``resolve()`` /
        ``children()`` over the tree are pure cache hits.

        A stub whose path points at plain data rather than an OME metadata
        document (e.g. a singlescale's Zarr array) is a *data leaf*: with
        ``on_error="skip"`` (the default) it is skipped and its target's
        ``FileNotFoundError`` / :class:`NotOmeDocumentError` suppressed;
        with ``on_error="raise"`` it raises. Any other error always raises.

        ``max_depth`` counts resolution hops from ``doc``: ``0`` fetches
        nothing, ``1`` resolves only ``doc``'s own stubs, and so on.

        Returns every document reached, ``doc`` first.
        """
        documents = [doc]
        frontier = [doc]
        visited = {doc.url}
        depth = 0
        while frontier and (max_depth is None or depth < max_depth):
            stubs: list[BaseNode] = []
            for document in frontier:
                stack: list[BaseNode] = [document.root]
                while stack:
                    node = stack.pop()
                    if node.path is not None and node is not document.root:
                        # A stub: its target's tree is walked next round.
                        url = _target_doc_url(document.url, node.path)
                        if url not in visited:
                            visited.add(url)
                            stubs.append(node)
                        continue
                    # Reversed so stubs come out in declaration order.
                    for child in reversed(getattr(node, "nodes", None) or []):
                        if isinstance(child, BaseNode):
                            stack.append(child)
            results = await asyncio.gather(
                *(self.resolve(stub) for stub in stubs), return_exceptions=True
            )
            frontier = []
            for result in results:
                if isinstance(result, (FileNotFoundError, NotOmeDocumentError)):
                    if on_error == "raise":
                        raise result
                    continue  # data leaf: no metadata document behind the path
                if isinstance(result, BaseException):
                    raise result
                documents.append(result)
                frontier.append(result)
            depth += 1
        return documents

    async def inline(
        self,
        doc: MetadataDocument,
        *,
        max_depth: int | None = None,
        on_error: Literal["skip", "raise"] = "skip",
    ) -> MetadataDocument:
        """Explicit copy-building merge of a resolved tree into ONE document.

        Returns a NEW :class:`MetadataDocument` in which every stub that
        resolves to a metadata document is collapsed into a copy of its
        resolved subtree, recursively. The collapse is the one place the
        DESIGN.md §5 attribute merge is materialized: the collapsed node
        carries ``merged_attributes(stub, target_root)`` (shallow, key-level,
        stub wins) and the stub's ``id``/``name``. Neither the input tree,
        the cached target documents, nor the resolver cache are ever mutated;
        the result is a derived artifact and is NOT cached (``open()`` on the
        URL keeps returning the original).

        ``max_depth`` bounds the collapse, counting resolution hops from
        ``doc`` exactly like :meth:`resolve_tree`: ``0`` resolves nothing
        (the result is a pure copy of ``doc``), ``1`` collapses only
        ``doc``'s own stubs, ``None`` (the default) collapses everything. A
        stub at the depth boundary is never fetched: it survives as a stub —
        attributes verbatim, no §5 merge (the merge happens only at collapse)
        — with its path rebased like any surviving path, so the partial tree
        stays navigable.

        Any surviving ``path`` declared in a non-top document — a data leaf
        kept under ``on_error="skip"``, or e.g. a singlescale's array path
        inside an inlined subtree — is rebased to the absolute URL it already
        resolved to, so the inlined document stays navigable. The trade-off:
        the result is not relocatable (absolute paths pin the original store
        layout). Paths declared in the top document itself are kept verbatim.

        The top document wins on ``url``/``form``/``version``/``stub_path``;
        merged child documents' versions are discarded. Reference cycles
        raise ``ValueError``, as do node-id collisions created by merging
        several documents into one (ids are only unique per document).

        ``on_error`` mirrors :meth:`resolve_tree`: a stub whose path points
        at plain data (``FileNotFoundError`` / :class:`NotOmeDocumentError`)
        survives as a stub under ``"skip"`` (the default) and raises under
        ``"raise"``. Any other error always raises. Fetches are sequential
        but cached — warm the cache with :meth:`resolve_tree` first for
        concurrent IO.
        """
        root = await self._inline_node(
            doc,
            doc.root,
            top_url=doc.url,
            ancestors=frozenset({doc.url}),
            depth_left=max_depth,
            on_error=on_error,
        )
        # Eager: id collisions are created by inline (ids are unique only
        # per source document), so fail here rather than at save().
        _assert_unique_ids(root)
        result = MetadataDocument(
            root=root,
            url=doc.url,
            form=doc.form,
            version=doc.version,
            stub_path=doc.stub_path,
        )
        _set_provenance(result)
        return result

    async def _inline_node(
        self,
        doc: MetadataDocument,
        node: BaseNode,
        *,
        top_url: str,
        ancestors: frozenset[str],
        depth_left: int | None,
        on_error: Literal["skip", "raise"],
    ) -> BaseNode:
        """Copy ``node`` (owned by ``doc``), collapsing path stubs."""
        if node.path is not None and node is not doc.root:
            return await self._inline_stub(
                doc,
                node,
                top_url=top_url,
                ancestors=ancestors,
                depth_left=depth_left,
                on_error=on_error,
            )
        children = getattr(node, "nodes", None)
        if children is None:
            copied = node.model_copy(deep=True)
        else:
            rebuilt: list = []
            for child in children:
                if isinstance(child, BaseNode):
                    rebuilt.append(
                        await self._inline_node(
                            doc,
                            child,
                            top_url=top_url,
                            ancestors=ancestors,
                            depth_left=depth_left,
                            on_error=on_error,
                        )
                    )
                else:
                    rebuilt.append(copy.deepcopy(child))
            copied = node.model_copy(deep=True, update={"nodes": rebuilt})
        if node is doc.root and node.path is not None:
            # A root-level path is a data pointer (resolve_tree never
            # traverses it); keep it, rebased into the top document's frame.
            copied.path = self._rebased_path(doc, node.path, top_url)
        return copied

    async def _inline_stub(
        self,
        doc: MetadataDocument,
        stub: BaseNode,
        *,
        top_url: str,
        ancestors: frozenset[str],
        depth_left: int | None,
        on_error: Literal["skip", "raise"],
    ) -> BaseNode:
        assert stub.path is not None
        if depth_left is not None and depth_left <= 0:
            # Depth boundary: never fetched (so no §5 merge, and on_error
            # cannot fire), survives as a stub like a data leaf below.
            return stub.model_copy(
                deep=True, update={"path": self._rebased_path(doc, stub.path, top_url)}
            )
        try:
            target = await self.resolve(stub)
        except (FileNotFoundError, NotOmeDocumentError):
            if on_error == "raise":
                raise
            # Data leaf: survives as a stub, path rebased to stay resolvable.
            return stub.model_copy(
                deep=True, update={"path": self._rebased_path(doc, stub.path, top_url)}
            )
        if target.url in ancestors:
            raise ValueError(
                f"reference cycle while inlining: {target.url!r} is its own ancestor"
            )
        inlined = await self._inline_node(
            target,
            target.root,
            top_url=top_url,
            ancestors=ancestors | {target.url},
            depth_left=None if depth_left is None else depth_left - 1,
            on_error=on_error,
        )
        # The §5 collapse: stub's id/name win, attributes merge (stub wins);
        # the stub's path is consumed by resolution.
        return inlined.model_copy(
            update={
                "id": stub.id,
                "name": stub.name,
                "attributes": copy.deepcopy(merged_attributes(stub, target.root)),
            }
        )

    def _rebased_path(
        self, doc: MetadataDocument, path: PathObj, top_url: str
    ) -> PathObj:
        """A surviving path, made absolute when its declaring document is
        not the top document (relative paths are document-relative)."""
        if doc.url == top_url:
            return path.model_copy(deep=True)
        return path.model_copy(update={"path": urljoin(doc.url, path.path)})

    async def save(self, doc: MetadataDocument) -> None:
        """Rewrite ONE document at its URL; externalized children are
        re-emitted as path stubs.

        For the zarr form this is a read-modify-write of ``zarr.json``
        touching only the ``attributes.ome`` key (sibling keys like
        ``zarr_format`` survive). Fails early with StoreReadOnlyError if the
        store can't write.
        """
        store = self._writable_store(doc.url)
        if doc.form == "json":
            data = doc.serialize()
        else:
            # Read-modify-write: only attributes.ome of zarr.json is ours.
            data = await self._existing_zarr_doc(doc.url)
            data.setdefault("attributes", {})["ome"] = doc.serialize_payload()
        await store.put(doc.url, json.dumps(data, indent=2).encode())
        self._cache[doc.url] = doc

    def _writable_store(self, url: str) -> WritableStore:
        """The store, checked up-front so save() fails before any IO."""
        store = self.store
        if not isinstance(store, WritableStore) or getattr(store, "read_only", False):
            raise StoreReadOnlyError(
                f"store {type(store).__name__!r} cannot write {url!r}"
            )
        return store

    async def _existing_zarr_doc(self, doc_url: str) -> dict:
        try:
            return json.loads(await self.store.get(doc_url))
        except FileNotFoundError:
            return {"zarr_format": 3, "node_type": "group"}

    async def _load_document(
        self, doc_url: str, stub_path: PathObj | None
    ) -> MetadataDocument:
        cached = self._cache.get(doc_url)
        if cached is not None:
            return cached
        raw = await self.store.get(doc_url)
        document = parse_metadata_document(
            raw, url=doc_url, registry=self.registry, stub_path=stub_path
        )
        self._cache[doc_url] = document
        return document
