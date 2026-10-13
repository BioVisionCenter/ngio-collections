"""Insert a child node with `add()`.

`add()` grafts a new (detached) node under the node it is called on and returns
the new tree root. The new node can be any type; `new_node` mints a UUID `id`
when none is given.

Run with: pixi run python examples/ops_add.py
"""

from basic_creation import build_collection

import ngio_collections as ngc


def main() -> None:
    root = build_collection()

    # add() on the root inserts a top-level child; it returns the new tree root.
    analysis = ngc.new_node("collection", name="analysis")
    edited = root.add(analysis)
    print("after add:  ", [n.name for n in edited.walk()])

    # add() on any located node nests under it.
    edited = edited.find(analysis.id).add(ngc.new_node("multiscale", name="result"))
    print("after nest: ", [n.name for n in edited.walk()])


if __name__ == "__main__":
    main()
