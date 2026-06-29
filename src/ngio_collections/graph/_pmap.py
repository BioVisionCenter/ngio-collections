"""An immutable key→value map with a dependency-free default backend.

`PersistentMap` is the single seam the graph core relies on for immutability. The
default backend here is stdlib-only: it wraps a plain `dict` that is never mutated
in place once published, so every map value is safely shareable. A single `set` /
`delete` copies the dict (O(n)); to apply many edits cheaply, take a `mutate()`
evolver, stage all changes on one fresh dict, and `finish()` once.

This is intentionally a thin interface (`get` / `set` / `delete` / `mutate`). If
the 1M benchmark ever shows the copy-on-write cost dominates, an accelerated
backend (e.g. `pyrsistent.PMap`) can replace this class behind the same surface —
the `orjson` optional-speedup pattern — without touching callers.
"""

from __future__ import annotations

from typing import Generic, Iterator, Mapping, TypeVar, overload

K = TypeVar("K")
V = TypeVar("V")


class PersistentMap(Generic[K, V]):
    """An immutable map; edits return a new map sharing nothing it must not.

    The wrapped dict is never mutated after construction, so values can be shared
    freely across versions. Construct empty, from a mapping, or (internally) by
    handing ownership of a dict that no one else references.
    """

    __slots__ = ("_data",)

    def __init__(
        self, data: Mapping[K, V] | None = None, *, _own: bool = False
    ) -> None:
        """Wrap `data`, copying it unless `_own` transfers exclusive ownership.

        Args:
            data: Initial contents; empty if `None`.
            _own: Internal flag. When `True`, `data` is a `dict` that no caller
                will mutate again (e.g. straight from an evolver), so it is
                adopted without copying. External callers must not pass this.
        """
        if _own and isinstance(data, dict):
            self._data: dict[K, V] = data
        else:
            self._data = dict(data) if data is not None else {}

    def __getitem__(self, key: K) -> V:
        """Return the value for `key`, raising `KeyError` if absent."""
        return self._data[key]

    @overload
    def get(self, key: K) -> V | None: ...
    @overload
    def get(self, key: K, default: V) -> V: ...
    def get(self, key: K, default: V | None = None) -> V | None:
        """Return the value for `key`, or `default` if absent."""
        return self._data.get(key, default)

    def __contains__(self, key: object) -> bool:
        """Return whether `key` is present."""
        return key in self._data

    def __len__(self) -> int:
        """Return the number of entries."""
        return len(self._data)

    def __iter__(self) -> Iterator[K]:
        """Iterate over keys."""
        return iter(self._data)

    def keys(self) -> Iterator[K]:
        """Iterate over keys."""
        return iter(self._data.keys())

    def values(self) -> Iterator[V]:
        """Iterate over values."""
        return iter(self._data.values())

    def items(self) -> Iterator[tuple[K, V]]:
        """Iterate over `(key, value)` pairs."""
        return iter(self._data.items())

    def set(self, key: K, value: V) -> PersistentMap[K, V]:
        """Return a new map with `key` bound to `value`."""
        data = dict(self._data)
        data[key] = value
        return PersistentMap(data, _own=True)

    def delete(self, key: K) -> PersistentMap[K, V]:
        """Return a new map without `key` (no error if it was absent)."""
        data = dict(self._data)
        data.pop(key, None)
        return PersistentMap(data, _own=True)

    def mutate(self) -> Evolver[K, V]:
        """Return a one-shot evolver for staging many edits, then `finish()`."""
        return Evolver(self._data)


class Evolver(Generic[K, V]):
    """A mutable staging buffer that produces one `PersistentMap` on `finish()`.

    Batches many `set`/`delete` calls onto a single fresh dict so a bulk edit
    costs one copy instead of one per change. Single-use: after `finish()` the
    evolver is spent (its dict has been handed to the new map) and any further
    call raises.
    """

    __slots__ = ("_data", "_done")

    def __init__(self, base: Mapping[K, V]) -> None:
        """Start an evolver from a snapshot of `base`."""
        self._data: dict[K, V] = dict(base)
        self._done = False

    def _check(self) -> None:
        if self._done:
            raise RuntimeError("evolver already finished; it is single-use")

    def __getitem__(self, key: K) -> V:
        """Return the staged value for `key`."""
        return self._data[key]

    @overload
    def get(self, key: K) -> V | None: ...
    @overload
    def get(self, key: K, default: V) -> V: ...
    def get(self, key: K, default: V | None = None) -> V | None:
        """Return the staged value for `key`, or `default` if absent."""
        return self._data.get(key, default)

    def __contains__(self, key: object) -> bool:
        """Return whether `key` is currently staged."""
        return key in self._data

    def set(self, key: K, value: V) -> Evolver[K, V]:
        """Stage `key = value`; returns self for chaining."""
        self._check()
        self._data[key] = value
        return self

    def delete(self, key: K) -> Evolver[K, V]:
        """Stage removal of `key` (no error if absent); returns self."""
        self._check()
        self._data.pop(key, None)
        return self

    def finish(self) -> PersistentMap[K, V]:
        """Freeze the staged edits into a new map and spend this evolver."""
        self._check()
        self._done = True
        return PersistentMap(self._data, _own=True)
