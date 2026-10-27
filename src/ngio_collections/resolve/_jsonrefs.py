"""Relativize path objects embedded inside a node's traits and fields (write time).

A pure JSON walker: no node or IO dependency. Any object carrying the path-object
shape (`{"type": "zarr"|"json"|<URI>, "format": ..., "href": ...}`) anywhere in a value
(`scales[*].path`, `labels.source[*].path`, a scene transform's `input.path`, …)
is relativized against the document when it is a local absolute path, while
plain `path` strings (e.g. `ScaleTransformation.path`) are left untouched, since
the match is on the path-object *shape*, not the key name.
"""

from __future__ import annotations

from typing import Mapping

from ngio_collections._types import JSONValue
from ngio_collections.models._manifest import is_extension_type
from ngio_collections.models._paths import BUILTIN_PATH_TYPES, DocPath


def is_path_object(value: object) -> bool:
    """Return whether `value` has the `{type, format, href}` path-object shape.

    The `type` is a built-in path type or an extension URI (a data path).
    """
    if not isinstance(value, Mapping):
        return False
    type_ = value.get("type")
    return (
        isinstance(type_, str)
        and (type_ in BUILTIN_PATH_TYPES or is_extension_type(type_))
        and isinstance(value.get("format"), str)
        and isinstance(value.get("href"), str)
    )


def relativize_paths(value: JSONValue, base_url: str | None) -> JSONValue:
    """Relativize every embedded path object in a JSON value.

    Args:
        value: A JSON value drawn from a node's traits or fields.
        base_url: The owning document's `url` (the relativization base).

    Returns:
        The value with matching path objects relativized (a new structure).
    """
    if isinstance(value, dict):
        if is_path_object(value):
            try:
                path = DocPath.from_dict(value)
            except Exception:
                return value  # malformed: leave it for validation to report
            return path.relativize(base_url).to_dict()
        return {k: relativize_paths(v, base_url) for k, v in value.items()}
    if isinstance(value, list):
        return [relativize_paths(v, base_url) for v in value]
    return value
