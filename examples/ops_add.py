"""Insert a child node with `add()`.

`add()` takes the parent id and a new node, and returns a new root with
the child inserted. The new node can be any node type.

Run with: pixi run python examples/add.py
"""

from basic_creation import build_collection

import ngio_collections as ngc


def main() -> None:
    root = build_collection()

    # add() inserts a child under the given parent id.
    edited = root.add(parent_id="root", child=ngc.CollectionNode(id="analysis"))
    print("after add:  ", [n.id for n in edited.walk()])

    # add() can be called on any node already in the tree.
    edited = edited.add(
        parent_id="analysis", child=ngc.MultiscaleNode(id="result", name="result")
    )
    print("after nest: ", [n.id for n in edited.walk()])


if __name__ == "__main__":
    main()
