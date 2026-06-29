"""Relativize reference paths embedded inside a node's attributes (write time).

A pure JSON walker: no node or IO dependency. Any object carrying the `DocPath`
shape (`{"type": "zarr"|"json", "path": <str>}`) anywhere in an attribute value —
e.g. `LabelsAttribute.source[*].path`, `WellAttribute.column.path` — has its
`path` relativized against the document, while plain `path` strings (e.g.
`ScaleTransformation.path`) are left untouched, since the match is on the
path-object *shape*, not the key name.
"""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from ngio_collections.models._paths import relativize as _relativize_path_str


def relativize_attr_refs(value: JsonValue, base_url: str | None) -> JsonValue:
    """Relativize every embedded `DocPath`-shaped object in an attribute value.

    Args:
        value: A JSON value drawn from a node's `attributes`.
        base_url: The owning document's `url` (the relativization base).

    Returns:
        The value with matching path objects relativized (a new structure).
    """
    if isinstance(value, dict):
        if value.get("type") in ("zarr", "json") and isinstance(value.get("path"), str):
            return {
                **value,
                "path": _relativize_path_str(cast("str", value["path"]), base_url),
            }
        return {k: relativize_attr_refs(v, base_url) for k, v in value.items()}
    if isinstance(value, list):
        return [relativize_attr_refs(v, base_url) for v in value]
    return value
