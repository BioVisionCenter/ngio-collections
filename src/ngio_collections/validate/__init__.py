"""L4 validation: capability lenses and scoped, composable validators.

`has_attribute` / `read_attribute` / `get_attribute` read a node's roles through
typed models. `validate` runs the union of every applicable validator over a
bounded `Context`. `register_builtins` wires the example validators explicitly.
See `ngio-node-composition-over-inheritance`.
"""

from __future__ import annotations

from ngio_collections.validate._builtins import (
    ScaleMatchesAxes,
    WellUnderPlate,
    register_builtins,
)
from ngio_collections.validate._engine import (
    DEFAULT_VALIDATORS,
    CapabilityValidator,
    Context,
    Issue,
    Scope,
    Validator,
    ValidatorRegistry,
    validate,
    validate_tree,
)
from ngio_collections.validate._views import (
    get_attribute,
    has_attribute,
    read_attribute,
)

__all__ = [
    "DEFAULT_VALIDATORS",
    "CapabilityValidator",
    "Context",
    "Issue",
    "ScaleMatchesAxes",
    "Scope",
    "Validator",
    "ValidatorRegistry",
    "WellUnderPlate",
    "get_attribute",
    "has_attribute",
    "read_attribute",
    "register_builtins",
    "validate",
    "validate_tree",
]
