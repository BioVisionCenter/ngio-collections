"""The typed `ReferenceObj` pointer (`{type, ref, path?}`).

RFC-8 revision 1 (§7.2) separates *declarations* (`{type, id, ...}`) from
*references* (`{type, ref, path?}`): a reference names the kind of its target,
carries the target's UUID under `ref` (never `id`, so the two can always be told
apart) and optionally a `path` to the document that declares the target. A
reference carries nothing else — no traits, no children — which is why
`from_dict` rejects extra keys. Resolving it is the resolver's job. A frozen
stdlib dataclass: the core builds and consumes it without pydantic, and the
pydantic value models accept it as a field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ngio_collections._types import JSONValue
from ngio_collections.models._ids import is_uuid
from ngio_collections.models._paths import DocPath

_KEYS = frozenset({"type", "ref", "path"})


@dataclass(frozen=True, kw_only=True)
class ReferenceObj:
    """A portable, typed pointer to a declaration (node, scale, coordinate system).

    `type` is the kind of the target (`"multiscale"`, `"scale"`,
    `"coordinate_system"`, …); `ref` is its UUID. A `None` path means the target
    is declared in the *same* document; otherwise `path` locates the document.
    """

    type: str
    ref: str
    path: DocPath | None = None

    def __post_init__(self) -> None:
        """Check the field shapes, coercing a mapping `path` into a `DocPath`.

        Raises:
            ValueError: If `type` is not a string, `ref` is not a UUID, or
                `path` is neither `None`, a `DocPath` nor a valid path mapping.
        """
        if not isinstance(self.type, str):
            raise ValueError(f"reference type must be a string, got {self.type!r}")
        if not is_uuid(self.ref):
            raise ValueError(f"reference ref must be a UUID, got {self.ref!r}")
        if self.path is not None and not isinstance(self.path, DocPath):
            object.__setattr__(self, "path", DocPath.from_dict(self.path))  # a mapping

    @classmethod
    def from_dict(cls, data: Mapping[str, JSONValue] | ReferenceObj) -> ReferenceObj:
        """Build a reference from its wire mapping (`{type, ref, path?}`).

        A `ReferenceObj` instance is returned as is.

        Raises:
            ValueError: If `data` is not a mapping, misses `type` or `ref`,
                carries any other key, or fails the checks in `__post_init__`.
        """
        if isinstance(data, ReferenceObj):
            return data
        if not isinstance(data, Mapping):
            raise ValueError(f"a reference must be a mapping, got {data!r}")
        extra = set(data) - _KEYS
        if extra:
            raise ValueError(
                f"reference {dict(data)!r} carries unknown keys {sorted(extra)}"
            )
        type_, ref, path = data.get("type"), data.get("ref"), data.get("path")
        if not isinstance(type_, str) or not isinstance(ref, str):
            raise ValueError(f"reference {dict(data)!r} needs string `type` and `ref`")
        if path is not None and not isinstance(path, Mapping):
            raise ValueError(f"reference path must be a path object, got {path!r}")
        return cls(
            type=type_, ref=ref, path=None if path is None else DocPath.from_dict(path)
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the wire form `{type, ref, path?}` (`path` omitted when `None`)."""
        out: dict[str, JSONValue] = {"type": self.type, "ref": self.ref}
        if self.path is not None:
            out["path"] = self.path.to_dict()
        return out
