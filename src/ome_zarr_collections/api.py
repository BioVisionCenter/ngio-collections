"""Synchronous convenience API: single-document reads and writes.

Four functions over the async core, for scripts and notebooks:

- ``open_collection`` / ``open_multiscale`` — open a URL and return the
  fully *inlined* tree (every metadata stub collapsed into its resolved
  subtree, DESIGN.md §5 attribute merge applied) as one node.
- ``write_collection`` / ``write_multiscale`` — write a node tree as ONE
  metadata document at a URL (children embedded, never externalized) and
  return a detached reference stub for it, ready to be grafted into a
  parent collection's ``nodes``.

Each call submits the async work to a persistent event loop running on a
daemon background thread, so the functions work both in plain scripts and
inside environments that already run a loop (Jupyter). Pass a shared
``resolver`` to reuse its document cache across calls — but do not use that
same ``Resolver`` instance directly in your own event loop, since its cache
would then be touched from two loops.

The full mirrored sync facade over the Resolver remains deferred
(DESIGN.md §10); this module is deliberately just these four functions.
"""

from __future__ import annotations

import asyncio
import copy
import threading
from typing import Any, Coroutine, Literal, TypeVar

from ome_zarr_collections.document import (
    DEFAULT_VERSION,
    MetadataDocument,
    _set_provenance,
)
from ome_zarr_collections.models.base import BaseNode
from ome_zarr_collections.models.nodes import (
    CollectionNode,
    CollectionRef,
    MultiscaleNode,
    MultiscaleRef,
    validate_node,
)
from ome_zarr_collections.resolver import (
    Resolver,
    _classify_url,
    _relativize_url,
    _stub_path_for,
)
from ome_zarr_collections.store.local import LocalStore

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """The module's event loop, lazily started on a daemon thread."""
    global _loop
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever,
                name="ome-zarr-collections-sync",
                daemon=True,
            ).start()
            _loop = loop
    return _loop


def _run(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on the background loop and block for its result.

    The loop lives on its own thread, so this also works when the calling
    thread already runs an event loop (the Jupyter case).
    """
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result()


async def _open_inlined(
    url: str,
    resolver: Resolver,
    *,
    max_depth: int | None,
    on_error: Literal["skip", "raise"],
) -> MetadataDocument:
    doc = await resolver.open(url)
    # Concurrent cache warming over exactly the region inline() collapses
    # (same hop counting), so inlining is pure cache reads.
    await resolver.resolve_tree(doc, max_depth=max_depth, on_error=on_error)
    return await resolver.inline(doc, max_depth=max_depth, on_error=on_error)


def open_collection(
    url: str,
    resolver: Resolver | None = None,
    *,
    max_depth: int | None = None,
    on_error: Literal["skip", "raise"] = "skip",
) -> CollectionNode:
    """Open the collection at ``url`` as one fully inlined tree.

    Every metadata stub is collapsed into a copy of its resolved subtree
    (``Resolver.inline``): attributes merged per DESIGN.md §5 (stub wins),
    data leaves kept as stubs with absolute paths. Raises ``TypeError`` if
    the document's root is not a collection.

    ``max_depth`` bounds the collapse, counting resolution hops from the top
    document (``0`` collapses nothing, ``1`` only the top document's own
    stubs, ``None`` everything): deeper metadata stubs survive as stubs with
    absolute rebased paths — re-openable, not relocatable. ``on_error="raise"``
    fails on a missing or non-OME stub target instead of keeping the stub;
    since it also trips on ordinary data paths (e.g. a singlescale's array),
    it suits metadata-only trees.
    """
    resolver = resolver or Resolver(LocalStore())
    root = _run(
        _open_inlined(url, resolver, max_depth=max_depth, on_error=on_error)
    ).root
    if not isinstance(root, CollectionNode):
        raise TypeError(f"expected a collection at {url!r}, found {root.type!r}")
    return root


def open_multiscale(
    url: str,
    resolver: Resolver | None = None,
    *,
    max_depth: int | None = None,
    on_error: Literal["skip", "raise"] = "skip",
) -> MultiscaleNode:
    """Open the multiscale at ``url`` as one fully inlined tree.

    ``url`` must point directly at a multiscale document (e.g. an
    ``image.zarr`` group); raises ``TypeError`` otherwise. To reach a
    multiscale inside a collection, ``open_collection`` and navigate.
    ``max_depth`` / ``on_error`` as in ``open_collection``.
    """
    resolver = resolver or Resolver(LocalStore())
    root = _run(
        _open_inlined(url, resolver, max_depth=max_depth, on_error=on_error)
    ).root
    if not isinstance(root, MultiscaleNode):
        raise TypeError(f"expected a multiscale at {url!r}, found {root.type!r}")
    return root


def write_collection(
    collection: CollectionNode,
    url: str,
    resolver: Resolver | None = None,
    *,
    relativize: bool = True,
) -> CollectionRef:
    """Write ``collection`` (children embedded) as ONE document at ``url``.

    Returns a detached :class:`CollectionRef` (``{type, id, name, path}``)
    for the written document; graft it into a parent collection's ``nodes``
    to reference this document instead of embedding it. Parent-level
    attributes go on the reference (``ref.attributes[...] = ...``) and win
    over the target's on inlined reads (DESIGN.md §5).

    With ``relativize`` (the default) absolute stub paths in the tree are
    rewritten relative to ``url`` where possible — same scheme and host;
    cross-store references stay absolute. The comparison is textual, so a
    ``file://`` path written to a plain-path ``url`` stays absolute (still
    resolvable, not relocatable). ``relativize=False`` writes paths verbatim.
    """
    if not isinstance(collection, CollectionNode):
        raise TypeError(f"expected a CollectionNode, got {type(collection).__name__}")
    stub = _write_node(collection, url, resolver, relativize=relativize)
    assert isinstance(stub, CollectionRef)
    return stub


def write_multiscale(
    multiscale: MultiscaleNode,
    url: str,
    resolver: Resolver | None = None,
    *,
    relativize: bool = True,
) -> MultiscaleRef:
    """Write ``multiscale`` (singlescales embedded) as ONE document at ``url``.

    Returns a detached :class:`MultiscaleRef` for the written document;
    ``relativize`` as in ``write_collection``.
    """
    if not isinstance(multiscale, MultiscaleNode):
        raise TypeError(f"expected a MultiscaleNode, got {type(multiscale).__name__}")
    stub = _write_node(multiscale, url, resolver, relativize=relativize)
    assert isinstance(stub, MultiscaleRef)
    return stub


def _relativize_paths(root: BaseNode, doc_url: str) -> None:
    """Rewrite absolute node paths in the tree relative to ``doc_url``."""
    stack: list[BaseNode] = [root]
    while stack:
        node = stack.pop()
        if node.path is not None:
            relative = _relativize_url(node.path.path, doc_url)
            if relative is not None:
                node.path = node.path.model_copy(update={"path": relative})
        children = getattr(node, "nodes", None) or []
        stack.extend(child for child in children if isinstance(child, BaseNode))


def _write_node(
    node: BaseNode, url: str, resolver: Resolver | None, *, relativize: bool
) -> BaseNode:
    resolver = resolver or Resolver(LocalStore())
    doc_url, form = _classify_url(str(url))
    # Deep copy detaches all provenance: children owned by other documents
    # (e.g. a tree from open_collection) would otherwise be re-emitted as
    # path stubs instead of embedded; the caller's tree is never re-owned.
    root = copy.deepcopy(node)
    if relativize:
        _relativize_paths(root, doc_url)
    document = MetadataDocument(
        root=root, url=doc_url, form=form, version=DEFAULT_VERSION
    )
    _set_provenance(document)
    _run(resolver.save(document))
    stub_path = _stub_path_for(doc_url, form)
    return validate_node(
        {
            "type": node.type,
            "id": node.id,
            "name": node.name,
            "path": stub_path.model_dump(mode="json", by_alias=True),
        },
        context={"registry": resolver.registry},
    )
