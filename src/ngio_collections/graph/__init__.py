"""The graph core: an immutable, indexed `NodeTree` of `NodeRecord`s.

This package is the in-memory model the rest of the package builds on. It is
pure data and algorithms, with no IO. The public `Node` handle and the
open/save/resolve IO live in higher layers.
"""

from __future__ import annotations

from ngio_collections.graph._ids import ROOT, NodeId, child, depth, is_ancestor, parent
from ngio_collections.graph._pmap import Evolver, PersistentMap
from ngio_collections.graph._record import (
    RESERVED_NODE_KEYS,
    EdgeInfo,
    Fields,
    NodeRecord,
    Traits,
    declared_ids,
    find_declaration,
    iter_declarations,
    merge_traits,
    traits_from_list,
    traits_to_list,
)
from ngio_collections.graph._tree import Mode, NodeTree, TreeBuilder

__all__ = [
    "RESERVED_NODE_KEYS",
    "ROOT",
    "EdgeInfo",
    "Evolver",
    "Fields",
    "Mode",
    "NodeId",
    "NodeRecord",
    "NodeTree",
    "PersistentMap",
    "Traits",
    "TreeBuilder",
    "child",
    "declared_ids",
    "depth",
    "find_declaration",
    "is_ancestor",
    "iter_declarations",
    "merge_traits",
    "parent",
    "traits_from_list",
    "traits_to_list",
]
