"""Pure JSON walkers that rewrite references embedded in node attributes.

No node dependency: these operate on the raw JSON drawn from a node's
`attributes`. `relativize_attr_refs` rewrites embedded path objects relative to
a document (used at write time); `rewrite_attr_refs` rewrites intra-document
`{"id": ...}` references after inlining renames node ids.
"""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from ngio_collections.models._paths import relativize as _relativize_path_str


def relativize_attr_refs(value: JsonValue, base_url: str | None) -> JsonValue:
    """Relativize every embedded path object in an attribute value.

    Walks the JSON structure; any dict carrying the `DocPath` shape
    (`{"type": "zarr"|"json", "path": <str>}`) has its `path` relativized against
    `base_url` (best-effort, via `_paths.relativize`). This rewrites references
    nested at any depth — e.g. `LabelsAttribute.source[*].path`,
    `WellAttribute.column.path`, `AcquisitionAttribute.path` — while leaving
    plain `path` strings (e.g. `ScaleTransformation.path`) untouched, since the
    match is on the path-object *shape*, not the key name.

    Args:
        value: A JSON value drawn from a node's `attributes`.
        base_url: The owning document's `url` (the relativization base).

    Returns:
        The value with matching path objects relativized (a new structure).
    """
    if isinstance(value, dict):
        if value.get("type") in ("zarr", "json") and isinstance(
            value.get("path"), str
        ):
            return {
                **value,
                "path": _relativize_path_str(cast("str", value["path"]), base_url),
            }
        return {k: relativize_attr_refs(v, base_url) for k, v in value.items()}
    if isinstance(value, list):
        return [relativize_attr_refs(v, base_url) for v in value]
    return value


def rewrite_attr_refs(value: JsonValue, rename: dict[str, str]) -> JsonValue:
    """Rewrite intra-document `{"id": <old>}` references in an attribute value.

    Walks the JSON structure; any object carrying an `id` whose value was
    renamed during inlining (i.e. it points at a node in `rename`) is updated to
    the new id. Ids that are not node ids (e.g. coordinate-system definitions)
    are absent from `rename` and left untouched.

    Args:
        value: A JSON value drawn from a node's `attributes`.
        rename: Map of original node id -> namespaced id for the same document.

    Returns:
        The value with matching id references rewritten (a new structure).
    """
    if isinstance(value, dict):
        new = {k: rewrite_attr_refs(v, rename) for k, v in value.items()}
        ref_id = new.get("id")
        if isinstance(ref_id, str) and ref_id in rename:
            new["id"] = rename[ref_id]
        return new
    if isinstance(value, list):
        return [rewrite_attr_refs(v, rename) for v in value]
    return value
