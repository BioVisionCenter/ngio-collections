"""Insert a child node with `add()`.

`add()` grafts a new (detached) node under the node it is called on and returns
the new tree root. The new node can be any type.

Run with: pixi run python examples/ops_add.py
"""

from basic_creation import build_collection

import ngio_collections as ngc


def main() -> None:
    root = build_collection()

    # add() on the root inserts a top-level child; it returns the new tree root.
    edited = root.add(ngc.new_node("collection", id="analysis"))
    print("after add:  ", [n.id for n in edited.walk()])

    # add() on any located node nests under it.
    edited = edited.find("analysis").add(
        ngc.new_node("multiscale", id="result", name="result")
    )
    print("after nest: ", [n.id for n in edited.walk()])


if __name__ == "__main__":
    main()
