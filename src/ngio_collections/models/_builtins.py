"""Registry wiring for the built-in node families.

Pairs with `register_family` (in `_nodes`): populates a registry with the
collection / multiscale / singlescale families. Kept in its own module — apart
from the per-type modules (which stay pure class definitions) and from `_nodes`
(which would import them circularly). The package composition root
(`ngio_collections.__init__`) calls `register_builtins()` once at import.
"""

from __future__ import annotations

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
from ngio_collections.models._nodes import DEFAULT_REGISTRY
from ngio_collections.models._registry import NodeRegistry
from ngio_collections.models._singlescale import RefSinglescaleNode


def register_builtins(registry: NodeRegistry = DEFAULT_REGISTRY) -> None:
    """Register the collection / multiscale / singlescale families.

    Idempotent: `register` overwrites, so calling twice is harmless.

    Args:
        registry: Registry to populate; the module default if omitted.
    """
    registry.register_family(CollectionNode, RefCollectionNode, InlinedCollectionNode)
    registry.register_family(MultiscaleNode, RefMultiscaleNode, InlinedMultiscaleNode)
    registry.register_family(RefSinglescaleNode)  # ref-only; key inferred
