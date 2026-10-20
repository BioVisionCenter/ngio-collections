"""PROVISIONAL traits: HCS (`plate`, `well`, `acquisition`) and `labels`.

RFC-8 revision 1 (§11) defers HCS and labels to sub-RFCs that do not exist yet,
while its examples still show them as built-in keyword traits in the
"recommended" tier. The shapes here follow those examples
(`rfc8-revision1/examples/plate.json`, `collection.json`) and may change again
when the sub-RFCs land; treat them as a best current guess, not a contract.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import Field

from ngio_collections.models._config import BaseObj
from ngio_collections.models._ids import UuidStr
from ngio_collections.models._references import ReferenceObj
from ngio_collections.models.traits._base import BaseTrait

# -- HCS ----------------------------------------------------------------------


class RowObj(BaseObj):
    """One plate row, named (`"A"`, `"B"`, …)."""

    name: str


class ColumnObj(BaseObj):
    """One plate column, named (`"1"`, `"2"`, …)."""

    name: str


class AcquisitionObj(BaseObj):
    """An `acquisition` declaration inside a plate trait (UUID id)."""

    type: Literal["acquisition"] = "acquisition"
    id: UuidStr
    name: str | None = None
    starttime: int | None = None
    endtime: int | None = None


class PlateTrait(BaseTrait):
    """A plate: its rows, columns and acquisitions. Carried by a collection."""

    applies_to: ClassVar[frozenset[str]] = frozenset({"collection"})

    type: Literal["plate"] = "plate"
    rows: list[RowObj]
    columns: list[ColumnObj]
    acquisitions: list[AcquisitionObj] = Field(default_factory=list)


class WellTrait(BaseTrait):
    """A well: its position in the parent plate's grid. Carried by a collection."""

    applies_to: ClassVar[frozenset[str]] = frozenset({"collection"})

    type: Literal["well"] = "well"
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)


class AcquisitionTrait(BaseTrait):
    """Marks an image as part of one acquisition declared in the plate trait."""

    applies_to: ClassVar[frozenset[str]] = frozenset({"multiscale"})

    type: Literal["acquisition"] = "acquisition"
    acquisition: ReferenceObj


# -- labels ---------------------------------------------------------------------

RgbaColor = Annotated[
    list[Annotated[int, Field(ge=0, le=255)]],
    Field(min_length=4, max_length=4),
]


class LabelObj(BaseObj):
    """Display metadata for one label value."""

    label_value: int
    rgba: RgbaColor | None = None


class LabelsTrait(BaseTrait):
    """Marks a multiscale as a label image of the `source` images."""

    applies_to: ClassVar[frozenset[str]] = frozenset({"multiscale"})

    type: Literal["labels"] = "labels"
    source: list[ReferenceObj] = Field(default_factory=list)
    label_attributes: list[LabelObj] = Field(default_factory=list)
