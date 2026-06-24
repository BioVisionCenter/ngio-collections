"""Registering a custom node type for typed dispatch (data stays in attributes).

A third-party package registers a custom `type` so nodes of that kind parse as a
recognizable class instead of a generic `Node` — handy for `isinstance` checks
and for hanging type-specific methods / validation off the class later. The
custom class adds only the `type` literal; all custom *data* lives in the open
`attributes` dict. That keeps written documents portable: they round-trip even in
a process that never registered the type (a generic `Node` keeps the attributes
untouched), whereas a custom *field* would be an unknown node-level key there and
be rejected (nodes are `extra="forbid"`).

The `type` literal is declared once on a `NodeObj` mixin and shared by the three
variants (editable / ref / inlined) through inheritance; `register_family` binds
them under the inferred key, and `isinstance(x, TableType)` holds for all three.

Run with: pixi run python examples/custom_node_types.py
"""

from pathlib import Path
from typing import Literal

import ngio_collections as ngc


class TableType(ngc.NodeObj):
    """Marks the `fractal:table` type; data goes in `attributes`, not fields."""

    type: Literal["fractal:table"] = "fractal:table"


class TableNode(TableType, ngc.Node):
    """Editable table node (table-specific methods / validation would live here)."""


class RefTableNode(TableType, ngc.RefNode):
    """Reference stub pointing at a table document."""


class InlinedTableNode(TableType, ngc.InlinedNode):
    """Resolved (read-only) table node."""


def main() -> None:
    # One call binds all three variants under the inferred "fractal:table" key.
    ngc.register_family(TableNode, RefTableNode, InlinedTableNode)

    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")
    resolver = ngc.Resolver(ngc.LocalStore())

    # A collection with a registered child and an unregistered one side by side;
    # custom data ("region") rides in the open attributes dict.
    root = ngc.CollectionNode(
        id="experiment",
        name="My Experiment",
        nodes=(
            TableNode(id="t1", name="regionprops", attributes={"region": "FOV_1"}),
            ngc.Node(id="v1", name="view", type="mobie:view"),
        ),
    )
    ngc.create(url, root, resolver, overwrite=True)

    # open(): the registered child parses back as TableNode; the unregistered
    # child degrades to a plain Node. Both keep their attributes untouched.
    table = ngc.open(url, resolver).find(id="t1")
    view = ngc.open(url, resolver).find(id="v1")
    print(
        f"open():         {type(table).__name__}, region={table.attributes['region']!r}"
    )
    print(f"unregistered:   {type(view).__name__}, type={view.type!r}")

    # open_inlined(): now an InlinedTableNode — but the mixin is a single
    # isinstance target across the editable and inlined variants.
    inlined = ngc.open_inlined(url, resolver).find(id="t1")
    print(
        f"open_inlined(): {type(inlined).__name__}, region={inlined.attributes['region']!r}"
    )
    print(
        "isinstance(_, TableType):",
        isinstance(table, TableType),
        isinstance(inlined, TableType),
    )


if __name__ == "__main__":
    main()
