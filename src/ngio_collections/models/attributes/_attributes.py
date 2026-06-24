"""Built-in label attribute models."""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import Field

from ngio_collections.models._base import (
    BaseAttribute,
    BaseObj,
    ReferenceObj,
)

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
