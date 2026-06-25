"""Build the read-only `InlinedNode` mirror of an editable node.

Part of the inlining algorithm driven by `Resolver.open_inlined`: given a source
node and its already-resolved children, mirror it into an `InlinedNode`,
carrying over the source's `_document` so `ref()` still works.
"""

from __future__ import annotations

from ngio_collections.models._nodes import (
    DEFAULT_REGISTRY,
    BaseNode,
    InlinedNode,
    RefNode,
    set_private,
)


def build_inlined(
    source: BaseNode, children: tuple[InlinedNode | RefNode, ...]
) -> InlinedNode:
    """Build the `InlinedNode` mirror of an editable `source` node.

    Copies `source`'s identity and attributes, attaches the already-resolved
    `children`, and stamps the source's `_document` so `ref()` works on the
    result.

    Args:
        source: The editable `Node` being inlined.
        children: The resolved children (inlined nodes and/or leftover stubs).

    Returns:
        A typed `InlinedNode` mirroring `source`.
    """
    data = source.model_dump(exclude={"nodes", "path"})
    cls = DEFAULT_REGISTRY.get_inlined(source.type or "")
    inlined = cls(**data, nodes=children)
    set_private(inlined, "_document", source._document)
    return inlined
