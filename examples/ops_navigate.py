"""Traverse a collection with `walk()` and `find()`.

`walk()` yields every node depth-first; `find(id)` returns the first node that
declares that UUID in the subtree, or `None` when absent. Both return `Node`
handles.

Run with: pixi run python examples/ops_navigate.py
"""

from basic_creation import NUCLEI, build_collection


def main() -> None:
    root = build_collection()

    # walk() visits every node in the tree, depth-first.
    print("all nodes:")
    for node in root.walk():
        print(f"  {node.name:<8} {node.id}")

    # find() returns the first node declaring the given id.
    node = root.find(NUCLEI)
    print("found:", node.name, "—", type(node).__name__)

    # find() returns None when the id does not exist.
    print("missing:", root.find("0192f3a0-dead-7000-8000-000000000000"))


if __name__ == "__main__":
    main()
