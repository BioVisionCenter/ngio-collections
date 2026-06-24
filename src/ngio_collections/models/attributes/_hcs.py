"""High-content screening attribute models: plate, well, acquisition."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from ngio_collections.models._base import (
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
