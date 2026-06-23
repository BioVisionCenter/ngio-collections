"""Synchronous IO entry points over the async :class:`Resolver`.

Four free functions mirroring the resolver's IO surface — `open`, `create`,
`save`, `delete` — for scripts and notebooks. Node editing is already
synchronous; only IO is async, so this is all the sync facade needs.

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
from ngio_collections.models import Node
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


def open(
    url: str,
    resolver: Resolver | None = None,
    *,
    inline: bool = True,
    depth: int | None = None,
    on_error: Literal["skip", "raise"] = "skip",
) -> Node:
    """Open the tree at `url` synchronously.

    With `inline` (the default) RefNode stubs are collapsed across document
    boundaries into one resolved tree (:meth:`Resolver.inline`); `depth` and
    `on_error` bound that collapse. With `inline=False` exactly one document
    is read and every stub is left in place (:meth:`Resolver.open`); `depth` and
    `on_error` then have no effect.

    Args:
        url: Entry-point document URL.
        resolver: Optional shared resolver; a fresh one is created if omitted.
        inline: If `True` (default), inline RefNode stubs across document
            boundaries. If `False`, return the root document only.
        depth: Maximum boundary hops when inlining; `None` = unlimited.
            Ignored when `inline=False`.
        on_error: `"skip"` leaves unresolvable stubs in place; `"raise"`
            propagates. Ignored when `inline=False`.

    Returns:
        The resolved (or partially resolved) node tree.
    """
    r = _resolver(resolver, None)
    if inline:
        return _run(r.inline(url, depth, on_error))
    return _run(r.open(url))


def create(
    url: str,
    root: Node,
    resolver: Resolver | None = None,
    *,
    overwrite: bool = False,
) -> Node:
    """Synchronous :meth:`Resolver.create`: write a detached tree to a new document.

    Args:
        url: Destination document URL.
        root: A DETACHED node tree to persist.
        resolver: Optional shared resolver; a fresh one is created if omitted.
        overwrite: If `False` (default), raise when a document already exists.

    Returns:
        `root` stamped with the new document (state changes to DOCUMENT).
    """
    return _run(_resolver(resolver, None).create(url, root, overwrite=overwrite))


def save(root: Node, resolver: Resolver | None = None) -> list[str]:
    """Synchronous :meth:`Resolver.save`: write an opened/created tree back.

    Args:
        root: The root node of a previously opened or created tree.
        resolver: Optional shared resolver; a fresh one is created if omitted.

    Returns:
        List of URLs that were actually written (empty if nothing changed).
    """
    return _run(_resolver(resolver, None).save(root))


def delete(node: Node, resolver: Resolver | None = None) -> list[str]:
    """Synchronous :meth:`Resolver.delete_subtree`: delete boundary documents.

    Args:
        node: Root of the subtree whose boundary documents should be deleted.
        resolver: Optional shared resolver; a fresh one is created if omitted.

    Returns:
        List of URLs that were deleted.
    """
    return _run(_resolver(resolver, None).delete_subtree(node))
