"""The built-in `collection` node family.

A collection groups child nodes — inline (editable / inlined) or as a reference
stub. The `collection` type literal is declared once on `CollectionType` and
shared by the three variants through inheritance. Collection-specific methods and
validation belong on these classes as the type grows.
"""

from __future__ import annotations

from ngio_collections.models._config import NodeObj
from ngio_collections.models._nodes import InlinedNode, Node, RefNode


class CollectionType(NodeObj):
    """Marks the `collection` type; one `isinstance` target for all variants."""

    __slots__ = ()
    node_type = "collection"


class CollectionNode(CollectionType, Node):
    """An embedded OME collection node."""

    __slots__ = ()


class RefCollectionNode(CollectionType, RefNode):
    """A reference stub pointing to an OME collection document."""

    __slots__ = ()


class InlinedCollectionNode(CollectionType, InlinedNode):
    """A resolved OME collection node."""

    __slots__ = ()
