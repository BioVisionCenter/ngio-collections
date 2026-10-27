"""A small multiscale fixture shared by the examples that are not about images.

`create_collection.py` shows how a multiscale is assembled in full; every other
example only needs *an image* and imports it from here. Ids are stable so the
generated documents are reproducible: node `uid(n)`, coordinate system
`system_id(n)`, scale `level` `uid(0x30 + 0x10 * level + n)`.
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
    scale_paths: Sequence[ngc.ZarrPath] | None = None,
    traits: Sequence[ngc.BaseTrait | Mapping[str, object]] = (),
) -> ngc.Node:
    """A multiscale `uid(n)` with `levels` resolutions (factor `2**level` per axis)."""
    system = ngc.CoordinateSystem(
        id=system_id(n),
        axes=[ngc.Axis(name=a, type="space", unit="micrometer") for a in axes],
    )
    scales = []
    for level in range(levels):
        sid = uid(0x30 + 0x10 * level + n)
        path = (
            scale_paths[level]
            if scale_paths is not None
            else ngc.ZarrPath(href=f"./s{level}")
        )
        scales.append(
            ngc.Scale(
                id=sid,
                path=path,
                coordinate_transformations=[
                    ngc.ScaleTransformation(
                        scale=[float(2**level)] * len(axes),
                        input=ngc.ReferenceObj(type="scale", ref=sid),
                        output=ngc.ReferenceObj(
                            type="coordinate_system", ref=system_id(n)
                        ),
                    )
                ],
            )
        )
    return ngc.new_multiscale(
        id=uid(n),
        name=name,
        coordinate_systems=[system],
        scales=scales,
        traits=list(traits),
    )
