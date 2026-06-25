"""Typed attribute models and the attribute base classes.

The base infra (`BaseAttribute`, `BaseListAttribute`, `AnyAttribute`) lives in
`_base` (a leaf depending only on `models._config`); `models._nodes` imports it
for `BaseNode`'s typed reads. It is re-exported here so consumers have a single
attribute import surface.
"""

from ngio_collections.models.attributes._base import (
    AnyAttribute,
    AttributeType,
    BaseAttribute,
    BaseListAttribute,
)
from ngio_collections.models.attributes._attributes import (
    LabelObj,
    LabelsAttribute,
    RgbaColor,
)
from ngio_collections.models.attributes._hcs import (
    AcquisitionAttribute,
    AcquisitionObj,
    ColumnObj,
    PlateAttribute,
    RowObj,
    WellAttribute,
)
from ngio_collections.models.attributes._coordinate import (
    Axis,
    CoordinateSystem,
    CoordinateSystemsAttribute,
    CoordinateTransformationsAttribute,
    SceneAttribute,
)
from ngio_collections.models.attributes._transformation import (
    AffineTransformation,
    BijectionTransformation,
    ByDimensionItem,
    ByDimensionTransformation,
    CoordinatesTransformation,
    CoordinateTransformation,
    CustomTransformation,
    DisplacementsTransformation,
    IdentityTransformation,
    MapAxisTransformation,
    RotationTransformation,
    ScaleTransformation,
    SequenceTransformation,
    TranslationTransformation,
)

__all__ = [
    "AcquisitionAttribute",
    "AcquisitionObj",
    "AffineTransformation",
    "AnyAttribute",
    "AttributeType",
    "Axis",
    "BaseAttribute",
    "BaseListAttribute",
    "BijectionTransformation",
    "ByDimensionItem",
    "ByDimensionTransformation",
    "ColumnObj",
    "CoordinateSystem",
    "CoordinateSystemsAttribute",
    "CoordinateTransformation",
    "CoordinateTransformationsAttribute",
    "CoordinatesTransformation",
    "CustomTransformation",
    "DisplacementsTransformation",
    "IdentityTransformation",
    "LabelObj",
    "LabelsAttribute",
    "MapAxisTransformation",
    "PlateAttribute",
    "RgbaColor",
    "RotationTransformation",
    "RowObj",
    "ScaleTransformation",
    "SceneAttribute",
    "SequenceTransformation",
    "TranslationTransformation",
    "WellAttribute",
]
