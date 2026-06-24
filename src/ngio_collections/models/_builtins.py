"""Composition root: wire the built-in node families into a registry.

Kept separate from the per-type modules (which stay pure class definitions) and
from `_base` (which would import them circularly). `models.__init__` calls
`register_builtins()` once at package import.
"""

from __future__ import annotations

from ngio_collections.models._base import DEFAULT_REGISTRY
from ngio_collections.models._collection import (
    CollectionNode,
    InlinedCollectionNode,
    RefCollectionNode,
)
from ngio_collections.models._multiscale import (
    InlinedMultiscaleNode,
    MultiscaleNode,
    RefMultiscaleNode,
)
from ngio_collections.models._registry import NodeRegistry
from ngio_collections.models._singlescale import RefSinglescaleNode


def register_builtins(registry: NodeRegistry = DEFAULT_REGISTRY) -> None:
    """Register the collection / multiscale / singlescale families.

    Idempotent: `register` overwrites, so calling twice is harmless.

    Args:
        registry: Registry to populate; the module default if omitted.
    """
    registry.register_family(
        CollectionNode, RefCollectionNode, InlinedCollectionNode
    )
    registry.register_family(
        MultiscaleNode, RefMultiscaleNode, InlinedMultiscaleNode
    )
    registry.register_family(RefSinglescaleNode)  # ref-only; key inferred
