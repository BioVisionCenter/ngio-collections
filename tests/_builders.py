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
    """The coordinate-system UUID of the multiscale numbered `n`."""
    return mk(0x1000 + n)


def scale_id(n: int, level: int) -> str:
    """The UUID of resolution `level` of the multiscale numbered `n`."""
    return mk(0x2000 + n * 16 + level)


def multiscale(
    n: int,
    *,
    axis_names: Sequence[str] = ("y", "x"),
    levels: int = 2,
    traits: Sequence[object | Mapping] = (),
    name: str | None = None,
    path: ngc.DocPath | None = None,
) -> ngc.Node:
    """A detached multiscale `mk(n)` with `levels` scales mapping into one system."""
    system = {
        "type": "coordinate_system",
        "id": cs_id(n),
        "name": "physical",
        "axes": axes(*axis_names),
    }
    scales = [
        {
            "type": "scale",
            "id": scale_id(n, i),
            "path": ngc.ZarrPath(href=f"./s{i}").to_dict(),
            "coordinate_transformations": [
                {
                    "type": "scale",
                    "scale": [2.0**i] * len(axis_names),
                    "input": {"type": "scale", "ref": scale_id(n, i)},
                    "output": {"type": "coordinate_system", "ref": cs_id(n)},
                }
            ],
        }
        for i in range(levels)
    ]
    return ngc.new_multiscale(
        id=mk(n),
        name=name or f"ms{n}",
        coordinate_systems=[system],
        scales=scales,
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
