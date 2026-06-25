"""The built-in `singlescale` node family.

A singlescale is a single-resolution image array. The `singlescale` type literal
is declared once on `SinglescaleType`. Today only the reference-stub variant
exists; the editable / inlined variants (`SinglescaleNode`,
`InlinedSinglescaleNode`) can be added here — inheriting `SinglescaleType` — as
the type grows.
"""

from __future__ import annotations

from ngio_collections.models._config import NodeObj
from ngio_collections.models._nodes import RefNode


class SinglescaleType(NodeObj):
    """Marks the `singlescale` type; one `isinstance` target for all variants."""

    __slots__ = ()
    node_type = "singlescale"


class RefSinglescaleNode(SinglescaleType, RefNode):
    """A reference stub pointing to an OME singlescale document."""

    __slots__ = ()
