"""Traverse a collection with `walk()` and `find()`.

`walk()` yields every node depth-first; `find(id)` returns the first node with
that id in the subtree, or `None` when absent. Both return `Node` handles.

Run with: pixi run python examples/ops_navigate.py
"""

from basic_creation import build_collection


def main() -> None:
    root = build_collection()

    # walk() visits every node in the tree, depth-first.
    print("all nodes:")
    for node in root.walk():
        print(f"  {node.id}")

    # find() returns the first node with the given id.
    node = root.find("nuclei")
    print("found:", node.id, "—", type(node).__name__)

    # find() returns None when the id does not exist.
    print("missing:", root.find("does-not-exist"))


if __name__ == "__main__":
    main()
