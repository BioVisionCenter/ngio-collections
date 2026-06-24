"""Traverse a collection with `walk()` and `find()`.

`walk()` yields every node depth-first; `find()` returns one node by id,
or `None` when the id is not present.

Run with: pixi run python examples/navigate.py
"""

from basic_creation import build_collection


def main() -> None:
    root = build_collection()

    # walk() visits every node in the tree, depth-first.
    print("all nodes:")
    for node in root.walk():
        print(f"  {node.id}")

    # find() returns the first node with the given id.
    node = root.find(id="nuclei")
    print("found:", node.id, "—", type(node).__name__)

    # find() returns None when the id does not exist.
    print("missing:", root.find(id="does-not-exist"))


if __name__ == "__main__":
    main()
