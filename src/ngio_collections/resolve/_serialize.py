"""Serialize a `NodeTree` (sub)tree back to its OME-payload wire form.

The inverse of `build` for one document: walk the key-graph from a root and
rebuild the nested node dicts (`type` / `id` / `name` / `path` / `traits` /
node fields / `nodes`). An external record is emitted as its declaring entry
(with `path`, no `nodes`); a *resolved* boundary record (one carrying an `edge`)
is emitted as the declaring entry it collapsed, so document boundaries are
respected by construction and a resolved view serializes back to the entry
document it was opened from. When `relativize` is set, path objects on nodes and
inside traits / fields are rewritten relative to the document (best-effort;
remote / cross-root paths stay verbatim) so a co-located collection stays
relocatable. `None` fields and empty trait lists are dropped, so an unedited
document re-serializes identically.

RFC-8 revision 1 never embeds a multiscale inside a collection (§8.1); with
`strict=True` serializing such a record raises `EmbeddedMultiscaleError`.
"""

from __future__ import annotations

from typing import Mapping, Sequence, cast

from ngio_collections._types import JSONValue
from ngio_collections.graph import (
    ROOT,
    Fields,
    NodeId,
    NodeTree,
    Traits,
    traits_to_list,
)
from ngio_collections.models._paths import DocPath
from ngio_collections.resolve._document import VERSION
from ngio_collections.resolve._jsonrefs import relativize_paths


class EmbeddedMultiscaleError(ValueError):
    """A multiscale is embedded in a collection; the revision requires a `path`."""


def _entry_dict(
    *,
    type: str,
    id: str,
    name: str | None,
    path: DocPath | None,
    traits: Traits,
    fields: Fields,
    base_url: str,
    relativize: bool,
) -> dict:
    """Assemble the common node-dict prefix: type, id, name, path, traits, fields."""
    data: dict = {"type": type, "id": id}
    if name is not None:
        data["name"] = name
    if path is not None:
        out_path = path.relativize(base_url) if relativize else path
        data["path"] = out_path.model_dump(mode="json")
    if traits:
        trait_list = cast(JSONValue, traits_to_list(traits))
        if relativize:
            trait_list = relativize_paths(trait_list, base_url)
        data["traits"] = trait_list
    for key, value in fields.items():
        data[key] = relativize_paths(value, base_url) if relativize else value
    return data


def node_dict(
    tree: NodeTree,
    node_id: NodeId,
    *,
    base_url: str,
    relativize: bool,
    strict: bool = True,
    _is_root: bool = True,
) -> dict:
    """Serialize the node at `node_id` (and its subtree) to a node dict.

    Raises:
        EmbeddedMultiscaleError: With `strict`, if a non-root multiscale has no
            `path` (it would be embedded in its parent's document).
    """
    record = tree.record(node_id)
    if record.edge is not None:  # resolved boundary: emit the declaring entry
        edge = record.edge
        return _entry_dict(
            type=record.type,
            id=record.id,
            name=edge.name,
            path=edge.path,
            traits=edge.traits,
            fields=edge.fields,
            base_url=base_url,
            relativize=relativize,
        )
    data = _entry_dict(
        type=record.type,
        id=record.id,
        name=record.name,
        path=record.path,
        traits=record.traits,
        fields=record.fields,
        base_url=base_url,
        relativize=relativize,
    )
    if record.path is not None:
        return data
    if strict and record.type == "multiscale" and not _is_root:
        raise EmbeddedMultiscaleError(
            f"multiscale {record.id!r} is embedded in its parent; RFC-8 revision 1 "
            "requires every multiscale in a collection to be its own document "
            "(create() it first, then add_external())"
        )
    if record.children is not None:
        data["nodes"] = [
            node_dict(
                tree,
                child,
                base_url=base_url,
                relativize=relativize,
                strict=strict,
                _is_root=False,
            )
            for child in record.children
        ]
    return data


def payload(
    tree: NodeTree,
    *,
    root_id: NodeId = ROOT,
    base_url: str,
    relativize: bool = True,
    extension_manifest: Sequence[Mapping] | None = None,
    strict: bool = True,
) -> dict:
    """Return the full OME payload for a document.

    `version` and `extension_manifest` are document-envelope keys kept off the
    nodes themselves so they never nest into embedded children; the manifest is
    emitted only when non-empty.
    """
    body: dict = {"version": VERSION}
    if extension_manifest:
        body["extension_manifest"] = [dict(entry) for entry in extension_manifest]
    body.update(
        node_dict(
            tree, root_id, base_url=base_url, relativize=relativize, strict=strict
        )
    )
    return body
