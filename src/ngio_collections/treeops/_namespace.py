"""Id uniqueness checks and occurrence-based namespacing for inlined trees.

Inlining merges several documents whose node ids are only unique per source.
`assert_unique_ids` is the safety net; `namespace_ids` makes ids globally unique
by rewriting them as `<origin_id>-<occurrence_token>` and updating intra-document
attribute references to match.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast

from ngio_collections.treeops._jsonrefs import rewrite_attr_refs
from ngio_collections.models._nodes import (
    BaseNode,
    InlinedNode,
    RefNode,
    set_private,
)

if TYPE_CHECKING:
    from ngio_collections.io._document import MetadataDocument


def assert_unique_ids(root: BaseNode) -> None:
    """Assert that every node id in the tree is unique.

    Node ids MUST be unique across the inlined (single-document) tree.
    Inlining merges several source documents into one, where ids are only unique
    per source — so collisions surface here. Unresolved `RefNode` stubs are
    pointers, not materialized nodes (a stub left at a cycle necessarily shares
    an ancestor's id), so they are not counted.

    Args:
        root: The root of the tree to validate.

    Raises:
        ValueError: If any materialized node id appears more than once.
    """
    seen: set[str] = set()
    for node in root.walk():
        node_id = getattr(node, "id", None)
        if node_id is None:  # path-based stubs are pointers, not nodes
            continue
        if node_id in seen:
            raise ValueError(f"duplicate node id {node_id!r} in document")
        seen.add(node_id)


def _occurrence_token(index_path: tuple[int, ...]) -> str:
    """Return a deterministic 8-hex token for a document occurrence.

    Seeded with the occurrence's child-index path from the root, so re-inlining
    the same source yields the same token (reproducible), while the same document
    inlined at two positions gets two distinct tokens.

    Args:
        index_path: The chain of child indices from the root to the boundary node
            where this document occurrence begins.

    Returns:
        An 8-character hex token (32 bits).
    """
    seed = ".".join(str(i) for i in index_path)
    return hashlib.blake2b(seed.encode(), digest_size=4).hexdigest()


def namespace_ids(root: InlinedNode | RefNode) -> InlinedNode | RefNode:
    """Make node ids globally unique as `<origin_id>-<occurrence_token>`.

    Inlining merges several documents whose ids are only unique per source. Each
    inlined document occurrence gets a short deterministic token from its
    position in the tree (see `_occurrence_token`); a node's id becomes
    `<origin_id>-<token>` (e.g. `image_inner-a1f3`, `image_0-a1f3`). The entry
    document keeps **bare** ids (e.g. `root`). Each node keeps its real id in
    `_origin_id` so `ref()` still yields a correct on-disk locator, and
    intra-document attribute references (`{"id": ...}`) are rewritten to the new
    ids per occurrence (so a doc inlined twice stays distinct). Path-based
    `RefNode` stubs carry no id and are passed through untouched.

    Args:
        root: The inlined tree to namespace.

    Returns:
        A new inlined tree with namespaced ids and rewritten attribute refs.
    """
    renames: dict[int, str] = {}
    origins: dict[int, str] = {}
    node_region: dict[int, int] = {}
    region_maps: dict[int, dict[str, str]] = {}

    def assign(
        node: BaseNode,
        index_path: tuple[int, ...],
        parent_doc: "MetadataDocument | None",
        region: int,
        token: str,
    ) -> None:
        orig = getattr(node, "id", None)
        if orig is None:
            return  # id-less pointer (unresolved document stub)
        # A node whose document differs from its parent's begins a new document
        # occurrence: its own id namespace for attribute refs, and one shared
        # token. The entry document (no parent) keeps bare ids.
        if node._document is not parent_doc or region not in region_maps:
            region = id(node)
            region_maps.setdefault(region, {})
            token = "" if parent_doc is None else _occurrence_token(index_path)
        new_id = orig if not token else f"{orig}-{token}"
        renames[id(node)] = new_id
        origins[id(node)] = orig
        node_region[id(node)] = region
        region_maps[region][orig] = new_id
        for i, child in enumerate(getattr(node, "nodes", ()) or ()):
            assign(child, (*index_path, i), node._document, region, token)

    assign(root, (), None, 0, "")

    def rebuild(node: BaseNode) -> tuple[BaseNode, bool]:
        """Rebuild `node` with namespaced ids/attrs; return `(node, changed)`.

        perf: nodes in the entry document keep bare ids and usually have no
        intra-document attribute refs, so most of the tree is structurally
        unchanged by namespacing. Such a node is reused as-is (no `model_copy`) —
        only its `_origin_id` is stamped in place, which is safe because the
        inlined tree is freshly built and owned solely by this call. This
        collapses the pass to a plain walk on a single-document read. `changed`
        tells the parent whether a *new* child object was created (so the parent
        must copy its `nodes` tuple).
        """
        node_id = getattr(node, "id", None)
        if node_id is None:
            return node, False  # id-less pointer, left untouched
        update: dict[str, object] = {"_origin_id": origins[id(node)]}
        new_id = renames[id(node)]
        if new_id != node_id:
            update["id"] = new_id
        rename = region_maps[node_region[id(node)]]
        new_attrs = rewrite_attr_refs(node.attributes, rename)
        if new_attrs != node.attributes:
            update["attributes"] = new_attrs
        children = getattr(node, "nodes", None)
        if children is not None:  # not a leaf stub
            rebuilt = [rebuild(c) for c in children]
            if any(child_changed for _, child_changed in rebuilt):
                update["nodes"] = tuple(child for child, _ in rebuilt)
        # Every materialized node carries `_origin_id`; if that is the only change
        # (and no child was rebuilt), stamp it in place and reuse the node.
        if set(update) == {"_origin_id"}:
            set_private(node, "_origin_id", origins[id(node)])
            return node, False
        # `model_copy` carries `_document` and applies the overrides without
        # re-validation (the lite node's copy is the read-path fast path).
        return node.model_copy(update=update), True

    return cast("InlinedNode | RefNode", rebuild(root)[0])
