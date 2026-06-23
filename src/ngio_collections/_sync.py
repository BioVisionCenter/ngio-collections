"""Synchronous IO entry points over the async :class:`Resolver`.

Four free functions mirroring the resolver's IO surface — ``open``, ``create``,
``save``, ``delete`` — for scripts and notebooks. Node editing is already
synchronous; only IO is async, so this is all the sync facade needs.

Each call submits the async work to a persistent event loop running on a daemon
background thread, so the functions work both in plain scripts and inside
environments that already run a loop (Jupyter). Pass a shared ``resolver`` to
reuse its document cache and store across calls — but do not also drive that same
``Resolver`` from your own event loop, since its cache then lives on the
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
    """The module's event loop, lazily started on a daemon thread."""
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
    """
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result()


def _resolver(resolver: Resolver | None, store: ReadableStore | None) -> Resolver:
    return resolver if resolver is not None else Resolver(store or LocalStore())


def open(
    url: str,
    resolver: Resolver | None = None,
    *,
    inline: bool = True,
    depth: int | None = None,
    on_error: Literal["skip", "raise"] = "skip",
) -> Node:
    """Open the tree at ``url`` synchronously.

    With ``inline`` (the default) RefNode stubs are collapsed across document
    boundaries into one resolved tree (:meth:`Resolver.inline`); ``depth`` and
    ``on_error`` bound that collapse. With ``inline=False`` exactly one document
    is read and every stub is left in place (:meth:`Resolver.open`); ``depth`` and
    ``on_error`` then have no effect.
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
    """Synchronous :meth:`Resolver.create`: write a detached tree to a new document
    at ``url`` and return it stamped with that document."""
    return _run(_resolver(resolver, None).create(url, root, overwrite=overwrite))


def save(root: Node, resolver: Resolver | None = None) -> list[str]:
    """Synchronous :meth:`Resolver.save`: write an opened/created tree back
    document-granularly and return the URLs written."""
    return _run(_resolver(resolver, None).save(root))


def delete(node: Node, resolver: Resolver | None = None) -> list[str]:
    """Synchronous :meth:`Resolver.delete_subtree`: delete the on-disk document of
    every boundary in ``node``'s subtree and return the URLs deleted."""
    return _run(_resolver(resolver, None).delete_subtree(node))
