"""The v5 graph core: an immutable, indexed `NodeTree` of `NodeRecord`s.

This package is the in-memory model the rest of v5 builds on. It is pure data and
algorithms — no IO. See `ngio-v5-architecture` for the design; the public `Node`
handle and the open/save/inline IO live in higher layers.
"""

from __future__ import annotations

from ngio_collections.graph._tree import Mode, NodeTree, TreeBuilder
from ngio_collections.graph._ids import ROOT, NodeId, child, depth, is_ancestor, parent
from ngio_collections.graph._pmap import Evolver, PersistentMap
from ngio_collections.graph._record import NodeRecord, Reference

__all__ = [
    "ROOT",
    "NodeTree",
    "Evolver",
    "Mode",
    "NodeId",
    "NodeRecord",
    "PersistentMap",
    "Reference",
    "TreeBuilder",
    "child",
    "depth",
    "is_ancestor",
    "parent",
]
