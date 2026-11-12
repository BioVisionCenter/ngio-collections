"""Wire keys of the multiscale layout, usable without pydantic.

The typed models live in `models._multiscale` (pydantic); the core and the
structural validators only need these names.
"""

from __future__ import annotations

DOWNSAMPLING_KEY = "downsamplingTransformations"
"""The wire key of an array's downsampling transformations."""

ARRAY_TYPE = "array"
"""The `type` every `data` entry carries."""

COORDINATE_SYSTEMS_KEY = "coordinateSystems"
"""The wire key of the coordinate systems of a multiscale or a `scene` trait."""

COORDINATE_TRANSFORMATIONS_KEY = "coordinateTransformations"
"""The wire key of the transformations of a multiscale or a `scene` trait."""

DATA_KEY = "data"
"""The wire key of a multiscale's array objects (its resolution levels)."""

MULTISCALE_FIELDS: frozenset[str] = frozenset(
    {COORDINATE_SYSTEMS_KEY, COORDINATE_TRANSFORMATIONS_KEY, DATA_KEY}
)
"""The node-type fields a `multiscale` node may carry."""
