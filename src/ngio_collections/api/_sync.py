"""Synchronous wrappers over the async API for scripts and notebooks.

Each async verb is mirrored as a blocking free function that runs the coroutine
on a persistent daemon event loop (one per process). Because that loop lives on
its own thread, these work even when the caller already runs an event loop (the
Jupyter case). The async API stays the core; this is only a convenience shell.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine, TypeVar

from ngio_collections.api import _api
from ngio_collections.api._node import Node
from ngio_collections.io.store import ReadableStore
from ngio_collections.models._references import ReferenceObj
from ngio_collections.resolve import OnError

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return the module's event loop, lazily started on a daemon thread."""
    global _loop
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever, name="ngio-collections-sync", daemon=True
            ).start()
            _loop = loop
    return _loop


def _run(coro: Coroutine[Any, Any, T]) -> T:
    """Run `coro` on the background loop and block for its result."""
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result()


def open(source: str, store: ReadableStore | None = None) -> Node:
    """Synchronous `open`."""
    return _run(_api.open(source, store))


def open_inlined(
    source: str,
    store: ReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> Node:
    """Synchronous `open_inlined`."""
    return _run(_api.open_inlined(source, store, depth=depth, on_error=on_error))


def open_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: ReadableStore | None = None,
) -> Node:
    """Synchronous `open_ref`."""
    return _run(_api.open_ref(ref, base_url, store))


def open_inlined_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: ReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> Node:
    """Synchronous `open_inlined_ref`."""
    return _run(
        _api.open_inlined_ref(ref, base_url, store, depth=depth, on_error=on_error)
    )


def create(
    destination: str,
    root: Node,
    store: ReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
) -> Node:
    """Synchronous `create`."""
    return _run(
        _api.create(
            destination, root, store, overwrite=overwrite, relativize=relativize
        )
    )


def save(
    node: Node, store: ReadableStore | None = None, *, relativize: bool = True
) -> Node:
    """Synchronous `save`."""
    return _run(_api.save(node, store, relativize=relativize))


def save_inlined(
    view: Node,
    destination: str,
    store: ReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
) -> Node:
    """Synchronous `save_inlined`."""
    return _run(
        _api.save_inlined(
            view, destination, store, overwrite=overwrite, relativize=relativize
        )
    )


def delete(node: Node, store: ReadableStore | None = None) -> list[str]:
    """Synchronous `delete`."""
    return _run(_api.delete(node, store))
