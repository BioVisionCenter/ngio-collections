"""Built-in attribute models: plate, well, acquisition, labels."""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import Field

from ome_zarr_collections.models.base import (
    BaseAttribute,
    BaseObj,
    IdStr,
    PathObj,
    ReferenceObj,
)


class AcquisitionObj(BaseObj):
    id: IdStr
    name: str | None = None


class ColumnObj(BaseObj):
    id: IdStr
    name: str | None = None


class RowObj(BaseObj):
    id: IdStr
    name: str | None = None


class PlateAttribute(BaseAttribute):
    key: ClassVar[str] = "plate"

    acquisitions: list[AcquisitionObj] = Field(default_factory=list)
    columns: list[ColumnObj]
    rows: list[RowObj]


class WellAttribute(BaseAttribute):
    key: ClassVar[str] = "well"

    column: ReferenceObj
    row: ReferenceObj


class AcquisitionAttribute(BaseAttribute):
    key: ClassVar[str] = "acquisition"

    id: IdStr
    path: PathObj | None = None


RgbaColor = Annotated[
    list[Annotated[int, Field(ge=0, le=255)]],
    Field(min_length=4, max_length=4),
]


class LabelObj(BaseObj):
    label_value: int
    color: RgbaColor | None = None


class LabelsAttribute(BaseAttribute):
    key: ClassVar[str] = "labels"

    label_attributes: list[LabelObj] = Field(default_factory=list)
    source: list[ReferenceObj] = Field(default_factory=list)
