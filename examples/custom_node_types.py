"""Registering a custom node type for typed handles (data stays in attributes).

A third-party package registers a custom `type` so nodes of that kind wrap as a
recognizable handle class instead of the generic `Node` — handy for `isinstance`
checks and for hanging type-specific helpers off the class later. The custom class
adds no fields; all custom *data* lives in the open `attributes` dict, so written
documents round-trip even in a process that never registered the type (it just
wraps as a generic `Node`).

In v5 there is one handle class per type (no editable/ref/inlined variants), so a
single `register_node_type` call covers `open` and `open_inlined` alike.

Run with: pixi run python examples/custom_node_types.py
"""

from pathlib import Path

import ngio_collections as ngc


class TableNode(ngc.Node):
    """Handle for `fractal:table` nodes (table-specific helpers would live here)."""


def main() -> None:
    ngc.register_node_type("fractal:table", TableNode)

    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")

    # A registered child and an unregistered one side by side; custom data
    # ("region") rides in the open attributes dict.
    root = (
        ngc.new_node("collection", id="experiment", name="My Experiment")
        .add(
            ngc.new_node(
                "fractal:table",
                id="t1",
                name="regionprops",
                attributes={"region": "FOV_1"},
            )
        )
        .add(ngc.new_node("mobie:view", id="v1", name="view"))
    )
    ngc.create(url, root, overwrite=True)

    # open(): the registered child wraps as TableNode; the unregistered one
    # degrades to a generic Node. Both keep their attributes untouched.
    opened = ngc.open(url)
    table = opened.find("t1")
    view = opened.find("v1")
    print(
        f"open():         {type(table).__name__}, region={table.attributes['region']!r}"
    )
    print(f"unregistered:   {type(view).__name__}, type={view.type!r}")

    # open_inlined(): the same handle class, since v5 has one class per type.
    inlined = ngc.open_inlined(url).find("t1")
    print(
        f"open_inlined(): {type(inlined).__name__}, region={inlined.attributes['region']!r}"
    )
    print(
        "isinstance(_, TableNode):",
        isinstance(table, TableNode),
        isinstance(inlined, TableNode),
    )


if __name__ == "__main__":
    main()
