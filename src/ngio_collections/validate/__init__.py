"""Validation: trait lenses and cheap, composable validators.

`has_trait` / `read_trait` / `get_trait` read a node's roles through typed
models. A validator is a plain `Callable[[Node], None]` that `raise`s a
`ValidationError` on a problem; `validate` runs a sequence of them over a node
and its descendants and collects the failures. Callers pass the validators they
want explicitly, or one of the bundles: `CORE_VALIDATORS` (the revision's
structural rules), `RECOMMENDED_VALIDATORS` (the recommended-tier traits) or
`ALL_VALIDATORS` (both). `paths_are_core` is opt-in, since this package
deliberately resolves every path format.
"""

from __future__ import annotations

from ngio_collections.validate._builtins import (
    RECOMMENDED_VALIDATORS,
    labels_source_resolves,
    plate_children_are_wells,
    scale_matches_axes,
    trait_applies_to,
    well_under_plate,
)
from ngio_collections.validate._engine import (
    ValidationError,
    ValidatorType,
    validate,
)
from ngio_collections.validate._structural import (
    CORE_VALIDATORS,
    extension_types_declared,
    external_unresolved,
    id_is_uuid,
    known_types,
    multiscale_is_complete,
    no_embedded_multiscale,
    node_fields_allowed,
    paths_are_core,
    references_resolve,
)
from ngio_collections.validate._views import (
    get_trait,
    has_trait,
    read_fields,
    read_trait,
    trait_key,
    trait_types,
)

ALL_VALIDATORS = (*CORE_VALIDATORS, *RECOMMENDED_VALIDATORS)
"""Every bundled validator (core structural rules plus recommended traits)."""

__all__ = [
    "ALL_VALIDATORS",
    "CORE_VALIDATORS",
    "RECOMMENDED_VALIDATORS",
    "ValidationError",
    "ValidatorType",
    "extension_types_declared",
    "external_unresolved",
    "get_trait",
    "has_trait",
    "id_is_uuid",
    "known_types",
    "labels_source_resolves",
    "multiscale_is_complete",
    "no_embedded_multiscale",
    "node_fields_allowed",
    "paths_are_core",
    "plate_children_are_wells",
    "read_fields",
    "read_trait",
    "references_resolve",
    "scale_matches_axes",
    "trait_applies_to",
    "trait_key",
    "trait_types",
    "validate",
    "well_under_plate",
]
