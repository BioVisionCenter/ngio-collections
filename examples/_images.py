"""A small multiscale fixture shared by the examples that are not about images.

`create_collection.py` shows how a multiscale is assembled in full; every other
example only needs *an image* and imports it from here. Ids are stable so the
generated documents are reproducible: node `uid(n)`, coordinate system
`system_id(n)`. Array objects carry no id.
"""

from collections.abc import Mapping, Sequence

import ngio_collections as ngc
from _ids import uid


def system_id(n: int) -> str:
    """The coordinate-system id of `image(n)`."""
    return uid(0x20 + n)


def image(
    n: int,
    name: str | None = None,
    *,
    axes: Sequence[str] = ("y", "x"),
    levels: int = 1,
    array_paths: Sequence[ngc.DocPath] | None = None,
    traits: Sequence[ngc.BaseTrait | Mapping[str, object]] = (),
) -> ngc.Node:
    """A multiscale `uid(n)` with `levels` arrays (level `i` downsampled by `2**i`).

    Arrays live at `./s<level>` unless `array_paths` locates them elsewhere. One
    `scale` transformation (1 µm pixels) maps the image's array space into its
    coordinate system.
    """
    system = ngc.CoordinateSystem(
        id=system_id(n),
        axes=[ngc.Axis(name=a, type="space", unit="micrometer") for a in axes],
    )
    arrays = [
        ngc.MultiscaleArray(
            path=(
                array_paths[level]
                if array_paths is not None
                else ngc.ZarrPath(href=f"./s{level}")
            ),
            downsamplingTransformations=(
                [ngc.ScaleDownsampling(scale=[float(2**level)] * len(axes))]
                if level
                else None
            ),
        )
        for level in range(levels)
    ]
    return ngc.new_multiscale(
        id=uid(n),
        name=name,
        coordinate_systems=[system],
        coordinate_transformations=[
            ngc.ScaleTransformation(
                scale=[1.0] * len(axes),
                input=ngc.ReferenceObj(type="multiscale", ref=uid(n)),
                output=ngc.ReferenceObj(type="coordinate_system", ref=system.id),
            )
        ],
        arrays=arrays,
        traits=list(traits),
    )
