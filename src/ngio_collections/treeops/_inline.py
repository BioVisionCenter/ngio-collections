"""Build the read-only `InlinedNode` mirror of an editable node.

Part of the inlining algorithm driven by `Resolver.open_inlined`: given a source
node and its already-resolved children, mirror it into an `InlinedNode`,
carrying over the source's `_document` so `ref()` still works.
"""

from __future__ import annotations

from typing import cast

from ngio_collections.models._nodes import (
    DEFAULT_REGISTRY,
    BaseNode,
    InlinedNode,
    RefNode,
    construct_node,
)


def build_inlined(
    source: BaseNode, children: tuple[InlinedNode | RefNode, ...]
) -> InlinedNode:
    """Build the `InlinedNode` mirror of an editable `source` node.

    Copies `source`'s identity and attributes, attaches the already-resolved
    `children`, and carries the source's `_document` so `ref()` works on the
    result.

    Args:
        source: The editable `Node` being inlined.
        children: The resolved children (inlined nodes and/or leftover stubs).

    Returns:
        A typed `InlinedNode` mirroring `source`.
    """
    cls = DEFAULT_REGISTRY.get_inlined(source.type or "")
    # perf: `source` is an already-validated `Node`; copy its field values
    # straight across instead of `model_dump()` + re-validating into `cls`. The
    # only shape change is dropping `path` (inlined nodes have none) and swapping
    # in the resolved `children`. `_document` (and `_origin_id`) ride along via
    # the private-attr copy. See `construct_node`.
    fields = {k: v for k, v in source.__dict__.items() if k != "path"}
    fields["nodes"] = children
    return cast(
        "InlinedNode", construct_node(cls, fields, source.__pydantic_private__ or {})
    )
