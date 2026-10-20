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
from ngio_collections.api._extensions import EXTENSIONS
from ngio_collections.api._node import Node
from ngio_collections.io.store import AnyReadableStore
from ngio_collections.models._manifest import ExtensionRegistry
from ngio_collections.models._paths import ALL_FORMATS
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


def open(source: str, store: AnyReadableStore | None = None) -> Node:
    """Synchronous `open`."""
    return _run(_api.open(source, store))


def open_resolved(
    source: str,
    store: AnyReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
    formats: frozenset[str] = ALL_FORMATS,
) -> Node:
    """Synchronous `open_resolved`."""
    return _run(
        _api.open_resolved(
            source, store, depth=depth, on_error=on_error, formats=formats
        )
    )


def open_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: AnyReadableStore | None = None,
) -> Node:
    """Synchronous `open_ref`."""
    return _run(_api.open_ref(ref, base_url, store))


def open_resolved_ref(
    ref: ReferenceObj,
    base_url: str | None = None,
    store: AnyReadableStore | None = None,
    *,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> Node:
    """Synchronous `open_resolved_ref`."""
    return _run(
        _api.open_resolved_ref(ref, base_url, store, depth=depth, on_error=on_error)
    )


def create(
    destination: str,
    root: Node,
    store: AnyReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
    registry: ExtensionRegistry = EXTENSIONS,
) -> Node:
    """Synchronous `create`."""
    return _run(
        _api.create(
            destination,
            root,
            store,
            overwrite=overwrite,
            relativize=relativize,
            registry=registry,
        )
    )


def save(
    node: Node,
    store: AnyReadableStore | None = None,
    *,
    relativize: bool = True,
    registry: ExtensionRegistry = EXTENSIONS,
) -> Node:
    """Synchronous `save`."""
    return _run(_api.save(node, store, relativize=relativize, registry=registry))


def externalize(
    node: Node,
    destination: str,
    store: AnyReadableStore | None = None,
    *,
    overwrite: bool = False,
    relativize: bool = True,
    registry: ExtensionRegistry = EXTENSIONS,
) -> Node:
    """Synchronous `externalize`."""
    return _run(
        _api.externalize(
            node,
            destination,
            store,
            overwrite=overwrite,
            relativize=relativize,
            registry=registry,
        )
    )


def delete(
    node: Node, store: AnyReadableStore | None = None, *, cascade: bool = False
) -> list[str]:
    """Synchronous `delete`."""
    return _run(_api.delete(node, store, cascade=cascade))


resolve_ref = _api.resolve_ref
