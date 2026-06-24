"""Delete a subtree with `remove()`.

`remove()` takes a node id and returns a new tree with that node and all
its descendants removed.

Run with: pixi run python examples/remove.py
"""

from basic_creation import build_collection

from ngio_collections import delete


def main() -> None:
    root = build_collection()

    # remove() unlinks the node and all its descendants.
    # If the node is still present on disk, it will be restored.
    edited = root.remove(id="labels")

    print("before:", [n.id for n in root.walk()])
    print("after: ", [n.id for n in edited.walk()])


if __name__ == "__main__":
    main()
