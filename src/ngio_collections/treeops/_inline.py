"""Build read-only `InlinedNode`s directly from parsed document payloads.

Part of the inlining algorithm driven by `Resolver.open_inlined`: it builds the
inlined tree in a single pass straight from each document's JSON payload (no
intermediate editable tree), so this is the read-path hot constructor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ngio_collections.models._nodes import (
    DEFAULT_REGISTRY,
    InlinedNode,
    RefNode,
)

if TYPE_CHECKING:
    from ngio_collections.io._document import MetadataDocument


def build_inlined_payload(
    node_dict: dict[str, Any],
    document: MetadataDocument,
    children: tuple[InlinedNode | RefNode, ...],
) -> InlinedNode:
    """Construct a lite `InlinedNode` straight from a parsed payload dict.

    perf: this is the single-pass read constructor — `Resolver.open_inlined`
    builds the inlined tree directly from each document's JSON payload, skipping
    the intermediate editable `Node` tree entirely (that tree was built only to be
    mirrored and discarded). Values come from a document Pydantic-free, so no
    per-node validation runs on the read path; `document` is stamped so `ref()`
    works (`_origin_id` is filled later by `namespace_ids`).

    Args:
        node_dict: A materialized node's payload dict (no `path`).
        document: The owning document of this node.
        children: The already-resolved children (inlined nodes / leftover stubs).

    Returns:
        A typed `InlinedNode` carrying `node_dict`'s identity and `children`.
    """
    cls = DEFAULT_REGISTRY.get_inlined(node_dict.get("type") or "")
    obj = cls.__new__(cls)
    sa = object.__setattr__
    sa(obj, "type", node_dict.get("type"))
    sa(obj, "name", node_dict.get("name"))
    sa(obj, "attributes", node_dict.get("attributes") or {})
    sa(obj, "id", node_dict.get("id"))
    sa(obj, "nodes", children)
    sa(obj, "_document", document)
    sa(obj, "_origin_id", None)
    return obj
