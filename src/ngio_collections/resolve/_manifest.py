"""Derive a document's `extension_manifest` from the extension types it uses.

A pure walk over the part of a `NodeTree` that one document serializes: the
subtree under `root_id`, stopping at document boundaries (external records and
resolved boundary records contribute their own declaring entry, not the target's
subtree). URI-typed node types, trait types and path types are the extension
points; the manifest entries come from the extensions the process has registered
plus any entries the document already declared.
"""

from __future__ import annotations

from typing import Iterator, Mapping, Sequence

from ngio_collections.graph import ROOT, NodeId, NodeTree
from ngio_collections.models._manifest import (
    ExtensionRegistry,
    is_extension_type,
    manifest_entries,
)


def _document_records(tree: NodeTree, root_id: NodeId) -> Iterator[NodeId]:
    """Yield the keys one document serializes: the subtree cut at boundaries."""
    stack = [root_id]
    while stack:
        node_id = stack.pop()
        yield node_id
        record = tree.record(node_id)
        if node_id != root_id and (record.path is not None or record.edge is not None):
            continue
        if record.children:
            stack.extend(reversed(record.children))


def used_extension_types(tree: NodeTree, root_id: NodeId = ROOT) -> tuple[str, ...]:
    """Return every URI-typed node / trait / path type the document at `root_id` uses.

    Resolved boundary records contribute the traits of their declaring entry
    (`edge.traits`), which is what the document actually stores.
    """
    used: dict[str, None] = {}
    for node_id in _document_records(tree, root_id):
        record = tree.record(node_id)
        if is_extension_type(record.type):
            used.setdefault(record.type)
        if record.path is not None and is_extension_type(record.path.type):
            used.setdefault(record.path.type)
        traits = record.edge.traits if record.edge is not None else record.traits
        for trait_type in traits:
            if is_extension_type(trait_type):
                used.setdefault(trait_type)
    return tuple(used)


def derive_manifest(
    tree: NodeTree,
    root_id: NodeId = ROOT,
    *,
    registry: ExtensionRegistry | None = None,
    known: Sequence[Mapping] = (),
) -> list[dict]:
    """Return the `extension_manifest` for the document rooted at `root_id`.

    Args:
        tree: The tree being serialized.
        root_id: The node whose subtree becomes the document.
        registry: Known extensions to draw entries from.
        known: Entries the document already declared (kept while still used).

    Returns:
        The manifest entries as plain dicts, in first-use order.
    """
    return manifest_entries(
        used_extension_types(tree, root_id), registry=registry, known=known
    )
