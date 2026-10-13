"""Remove a subtree with `remove()`.

`remove()` is called on the located node and returns the new tree root with that
node and all its descendants removed (the source tree is untouched).

Run with: pixi run python examples/ops_remove.py
"""

from basic_creation import LABELS, build_collection


def main() -> None:
    root = build_collection()

    edited = root.find(LABELS).remove()

    print("before:", [n.name for n in root.walk()])
    print("after: ", [n.name for n in edited.walk()])


if __name__ == "__main__":
    main()
