"""Serialize a `NodeTree` (sub)tree back to its OME-payload wire form.

The inverse of `build` for one document: walk the key-graph from a root and
rebuild the nested node dicts (`type` / `name` / `id` / `attributes` / `nodes`),
emitting a reference record as a `path` stub. When `relativize` is set, stub
paths and any reference paths embedded in attributes are rewritten relative to
the target document (best-effort; remote / cross-root paths stay verbatim) so a
co-located collection stays relocatable. `None` fields and empty attribute bags
are dropped, so an unedited document re-serializes identically.
"""

from __future__ import annotations

from ngio_collections.graph import ROOT, NodeTree, NodeId
from ngio_collections.resolve._document import VERSION
from ngio_collections.resolve._jsonrefs import relativize_attr_refs


def node_dict(
    collection: NodeTree,
    node_id: NodeId,
    *,
    base_url: str,
    relativize: bool,
) -> dict:
    """Serialize the node at `node_id` (and its subtree) to a node dict."""
    record = collection.record(node_id)
    data: dict = {"type": record.type}
    if record.name is not None:
        data["name"] = record.name
    if record.id is not None:
        data["id"] = record.id
    if record.attributes:
        attrs = dict(record.attributes)
        if relativize:
            attrs = relativize_attr_refs(attrs, base_url)  # type: ignore[assignment]
        if attrs:
            data["attributes"] = attrs
    if record.ref is not None:
        path = record.ref.path.relativize(base_url) if relativize else record.ref.path
        data["path"] = path.model_dump(mode="json", by_alias=True)
        return data
    if record.children is not None:
        data["nodes"] = [
            node_dict(collection, child, base_url=base_url, relativize=relativize)
            for child in record.children
        ]
    return data


def payload(
    collection: NodeTree,
    *,
    root_id: NodeId = ROOT,
    base_url: str,
    relativize: bool = True,
) -> dict:
    """Return the full OME payload (`version` + root node dict) for a document.

    `version` is a document-envelope key kept off the nodes themselves so it
    never nests into embedded children.
    """
    return {
        "version": VERSION,
        **node_dict(collection, root_id, base_url=base_url, relativize=relativize),
    }
