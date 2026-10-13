"""Relativize reference paths embedded inside a node's body (write time).

A pure JSON walker: no node or IO dependency. Any object carrying the `DocPath`
shape (`{"type": "zarr"|"json", "href": <str>, ...}`) anywhere in a body value —
e.g. a `ReferenceObj.path` inside `labels.source[*]` or a transformation's
`input` / `output` — has its `href` relativized against the document and its
`format` recomputed, while plain string paths (e.g. `ScaleTransformation.path`)
are left untouched, since the match is on the path-object *shape*, not the key
name.
"""

from __future__ import annotations

from typing import cast

from ngio_collections._types import JSONValue

from ngio_collections.models._paths import format_for
from ngio_collections.models._paths import relativize as _relativize_path_str


def relativize_attr_refs(value: JSONValue, base_url: str | None) -> JSONValue:
    """Relativize every embedded `DocPath`-shaped object in a body value.

    Args:
        value: A JSON value drawn from a node's body.
        base_url: The owning document's `url` (the relativization base).

    Returns:
        The value with matching path objects relativized (a new structure).
    """
    if isinstance(value, dict):
        if value.get("type") in ("zarr", "json") and isinstance(value.get("href"), str):
            href = _relativize_path_str(cast("str", value["href"]), base_url)
            return {**value, "format": format_for(href), "href": href}
        return {k: relativize_attr_refs(v, base_url) for k, v in value.items()}
    if isinstance(value, list):
        return [relativize_attr_refs(v, base_url) for v in value]
    return value
