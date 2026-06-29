"""L4 validation: capability lenses and cheap, composable validators.

`has_attribute` / `read_attribute` / `get_attribute` read a node's roles through
typed models. A validator is a plain `Callable[[Node], None]` that `raise`s a
`ValidationError` on a problem; `validate` runs a sequence of them over a node and
its descendants and collects the failures. Callers pass the validators they want
explicitly (e.g. `(well_under_plate, scale_matches_axes)`).
See `ngio-node-composition-over-inheritance`.
"""

from __future__ import annotations

from ngio_collections.validate._builtins import (
    scale_matches_axes,
    well_under_plate,
)
from ngio_collections.validate._engine import (
    ValidationError,
    ValidatorType,
    validate,
)
from ngio_collections.validate._views import (
    get_attribute,
    has_attribute,
    read_attribute,
)

__all__ = [
    "ValidationError",
    "ValidatorType",
    "get_attribute",
    "has_attribute",
    "read_attribute",
    "scale_matches_axes",
    "validate",
    "well_under_plate",
]
