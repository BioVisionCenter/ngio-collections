"""Synchronous IO entry points over the async :class:`Resolver`.

Free functions mirroring the resolver's IO surface — `open`, `open_inlined`,
`create`, `save`, `save_inlined`, `delete` — for scripts and notebooks. Node
editing is already synchronous; only IO is async, so this is all the sync facade
needs.

Each call submits the async work to a persistent event loop running on a daemon
background thread, so the functions work both in plain scripts and inside
environments that already run a loop (Jupyter). Pass a shared `resolver` to
reuse its document cache and store across calls — but do not also drive that same
`Resolver` from your own event loop, since its cache then lives on the
background loop and would be touched from two loops.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine, Literal, TypeVar

from ngio_collections._resolver import Resolver
from ngio_collections.models import BaseNode, InlinedNode, Node, RefNode
from ngio_collections.store import LocalStore, ReadableStore

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return the module's event loop, lazily starting it on a daemon thread.

    Returns:
        The running event loop used by all sync wrapper calls.
    """
    global _loop
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever,
                name="ngio-collections-sync",
                daemon=True,
            ).start()
            _loop = loop
    return _loop


def _run(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on the background loop and block for its result.

    The loop lives on its own thread, so this also works when the calling thread
    already runs an event loop (the Jupyter case).

    Args:
        coro: The coroutine to schedule.

    Returns:
        The coroutine's return value.
    """
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result()


def _resolver(resolver: Resolver | None, store: ReadableStore | None) -> Resolver:
    """Return `resolver` if given, otherwise build one from `store`."""
    return resolver if resolver is not None else Resolver(store or LocalStore())


def open(url: str, resolver: Resolver | None = None) -> Node:
    """Synchronous :meth:`Resolver.open`: read ONE document, stubs left in place.

    Args:
        url: Entry-point document URL.
        resolver: Optional shared resolver; a fresh one is created if omitted.

    Returns:
        The editable root node with cross-document references left as stubs.
    """
    return _run(_resolver(resolver, None).open(url))


def open_inlined(
    url: str,
    resolver: Resolver | None = None,
    *,
    depth: int | None = None,
    on_error: Literal["skip", "raise"] = "skip",
) -> InlinedNode:
    """Synchronous :meth:`Resolver.open_inlined`: resolve stubs into a read-only tree.

    Args:
        url: Entry-point document URL.
        resolver: Optional shared resolver; a fresh one is created if omitted.
        depth: Maximum boundary hops when inlining; `None` = unlimited.
        on_error: `"skip"` leaves unresolvable stubs in place; `"raise"`
            propagates.

    Returns:
        The read-only inlined node tree.
    """
    return _run(_resolver(resolver, None).open_inlined(url, depth, on_error))


def create(
    url: str,
    root: Node,
    resolver: Resolver | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
) -> RefNode:
    """Synchronous :meth:`Resolver.create`: write a detached tree to a new document.

    Args:
        url: Destination document URL.
        root: A DETACHED node tree to persist.
        resolver: Optional shared resolver; a fresh one is created if omitted.
        overwrite: If `False` (default), raise when a document already exists.
        relativize: If `True` (default), relativize co-located local stub paths.

    Returns:
        A typed `RefNode` stub locating `root` in the new document.
    """
    return _run(
        _resolver(resolver, None).create(
            url, root, overwrite=overwrite, relativize=relativize
        )
    )


def save(
    root: Node, resolver: Resolver | None = None, *, relativize: bool = True
) -> RefNode:
    """Synchronous :meth:`Resolver.save`: write an opened tree back to its document.

    Args:
        root: The root node of a previously opened or created tree.
        resolver: Optional shared resolver; a fresh one is created if omitted.
        relativize: If `True` (default), relativize co-located local stub paths.

    Returns:
        A typed `RefNode` stub locating `root` in its document.
    """
    return _run(_resolver(resolver, None).save(root, relativize=relativize))


def save_inlined(
    view: InlinedNode,
    url: str,
    resolver: Resolver | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
) -> RefNode:
    """Synchronous :meth:`Resolver.save_inlined`: snapshot an inlined tree to one file.

    Args:
        view: The read-only inlined tree to flatten.
        url: Destination document URL.
        resolver: Optional shared resolver; a fresh one is created if omitted.
        overwrite: If `False` (default), raise when a document already exists.
        relativize: If `True` (default), relativize co-located local stub paths.

    Returns:
        A typed `RefNode` stub locating the snapshot's root in the new document.
    """
    return _run(
        _resolver(resolver, None).save_inlined(
            view, url, overwrite=overwrite, relativize=relativize
        )
    )


def delete(node: BaseNode, resolver: Resolver | None = None) -> list[str]:
    """Synchronous :meth:`Resolver.delete`: remove a node from its document on disk.

    Args:
        node: A document-backed node to delete.
        resolver: Optional shared resolver; a fresh one is created if omitted.

    Returns:
        The URL(s) affected (written or deleted); empty if nothing changed.
    """
    return _run(_resolver(resolver, None).delete(node))
