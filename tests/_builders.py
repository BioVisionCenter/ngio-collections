"""Builders for revision-shaped detached trees used across the tests.

The multiscale builder works from plain dicts so the core suite runs without
pydantic; tests that need the typed models construct them explicitly.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import ngio_collections as ngc
from tests.conftest import mk


def axes(*names: str) -> list[dict]:
    return [{"name": n, "type": "space", "unit": "micrometer"} for n in names]


def cs_id(n: int) -> str:
    """The coordinate-system id of the multiscale numbered `n`."""
    return mk(0x1000 + n)


def array(n: int, level: int, ndim: int) -> dict:
    """The `array` object of resolution `level` (factor `2**level` per axis).

    Level 0 is the highest resolution and carries no downsampling. Arrays have
    no id; `n` is unused and kept so call sites read as "array of multiscale n".
    """
    entry: dict = {
        "type": "array",
        "path": ngc.ZarrPath(href=f"./s{level}").to_dict(),
    }
    if level:
        entry["downsamplingTransformations"] = [
            {"type": "scale", "scale": [2.0**level] * ndim}
        ]
    return entry


def to_physical(n: int, ndim: int) -> dict:
    """The transformation from the array space of multiscale `n` into its system."""
    return {
        "type": "scale",
        "scale": [0.5] * ndim,
        "input": {"type": "multiscale", "ref": mk(n)},
        "output": {"type": "coordinate_system", "ref": cs_id(n)},
    }


def multiscale(
    n: int,
    *,
    axis_names: Sequence[str] = ("y", "x"),
    levels: int = 2,
    traits: Sequence[object | Mapping] = (),
    name: str | None = None,
    path: ngc.DocPath | None = None,
) -> ngc.Node:
    """A detached multiscale `mk(n)` with `levels` arrays and one coordinate system.

    One `scale` transformation maps the multiscale's array space into the system.
    """
    system = {
        "type": "coordinate_system",
        "id": cs_id(n),
        "name": "physical",
        "axes": axes(*axis_names),
    }
    return ngc.new_multiscale(
        id=mk(n),
        name=name or f"ms{n}",
        coordinate_systems=[system],
        coordinate_transformations=[to_physical(n, len(axis_names))],
        arrays=[array(n, i, len(axis_names)) for i in range(levels)],
        traits=traits,
        path=path,
    )


def collection(
    n: int,
    *children: ngc.Node,
    traits: Sequence[object | Mapping] = (),
    name: str | None = None,
) -> ngc.Node:
    """A detached collection `mk(n)` holding `children` (multiscales must be external)."""
    return ngc.new_collection(
        id=mk(n), name=name or f"c{n}", traits=traits, children=children
    )


def external(n: int, href: str, node_type: str = "multiscale") -> ngc.Node:
    """A detached declaring entry (`{type, id, path}`) pointing at `href`."""
    return ngc.new_node(
        node_type, id=mk(n), name=f"ext{n}", path=ngc.ZarrPath(href=href)
    )
