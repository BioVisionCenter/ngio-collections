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

A multiscale without a `path` is written inline, with its `data`. A relative
path read from another document is rebased, so a node moved between documents
keeps locating the same targets.
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
from ngio_collections.resolve._document import MANIFEST_KEY, VERSION
from ngio_collections.resolve._jsonrefs import relativize_paths


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
    origin_url: str | None,
) -> dict:
    """Assemble the common node-dict prefix: type, id, name, path, traits, fields.

    Relative paths read from another document (`origin_url`) are rebased onto
    `base_url`, so they keep locating the same target.
    """
    data: dict = {"type": type, "id": id}
    if name is not None:
        data["name"] = name
    if path is not None:
        out_path = path.rebase(origin_url, base_url)
        if relativize:
            out_path = out_path.relativize(base_url)
        data["path"] = out_path.to_dict()
    if traits:
        data["traits"] = relativize_paths(
            cast(JSONValue, traits_to_list(traits)),
            base_url,
            origin_url=origin_url,
            relativize=relativize,
        )
    for key, value in fields.items():
        data[key] = relativize_paths(
            value, base_url, origin_url=origin_url, relativize=relativize
        )
    return data


def node_dict(
    tree: NodeTree,
    node_id: NodeId,
    *,
    base_url: str,
    relativize: bool,
) -> dict:
    """Serialize the node at `node_id` (and its subtree) to a node dict.

    A multiscale without a `path` is written inline, with its `data`.
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
            origin_url=edge.origin_url,
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
        origin_url=record.origin_url,
    )
    if record.path is not None:
        return data
    if record.children is not None:
        data["nodes"] = [
            node_dict(tree, child, base_url=base_url, relativize=relativize)
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
) -> dict:
    """Return the full OME payload for a document.

    `version` and `extensionManifest` are document keys kept off the nodes
    themselves so they never nest into embedded children; the manifest is
    emitted only when non-empty. The root node's own keys follow them.
    """
    body: dict = {"version": VERSION}
    if extension_manifest:
        body[MANIFEST_KEY] = [dict(entry) for entry in extension_manifest]
    body.update(node_dict(tree, root_id, base_url=base_url, relativize=relativize))
    return body
