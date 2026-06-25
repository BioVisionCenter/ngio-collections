"""The built-in `multiscale` node family.

A multiscale describes a multi-resolution image (singlescale children). The
`multiscale` type literal is declared once on `MultiscaleType` and shared by the
three variants through inheritance. Multiscale-specific methods and validation
belong on these classes as the type grows.
"""

from __future__ import annotations

from ngio_collections.models._config import NodeObj
from ngio_collections.models._nodes import InlinedNode, Node, RefNode


class MultiscaleType(NodeObj):
    """Marks the `multiscale` type; one `isinstance` target for all variants."""

    __slots__ = ()
    node_type = "multiscale"


class MultiscaleNode(MultiscaleType, Node):
    """An embedded OME multiscale node."""

    __slots__ = ()


class RefMultiscaleNode(MultiscaleType, RefNode):
    """A reference stub pointing to an OME multiscale document."""

    __slots__ = ()


class InlinedMultiscaleNode(MultiscaleType, InlinedNode):
    """A resolved OME multiscale node."""

    __slots__ = ()
