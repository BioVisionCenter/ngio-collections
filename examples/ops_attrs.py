"""Remove attribute keys from a node with `drop_attrs()`.

`drop_attrs()` accepts one or more key names and returns a new tree.
Keys that are not present are silently ignored.

Run with: pixi run python examples/drop_attrs.py
"""

from basic_creation import build_collection


def main() -> None:
    root = build_collection()

    # set_attrs() merges the given key-value pairs into the node's attributes.
    attrs = {
        "meta": {"channels": 2, "stain": "DAPI", "extra": "value"},
        "other": {"tag": "image"},
    }
    root = root.set_attrs(id="image", values=attrs)

    # drop_attrs() removes the named keys; missing keys are silently ignored.
    edited = root.drop_attrs(id="image", keys=("other",))

    print("before:", root.find(id="image").attributes)
    print("after: ", edited.find(id="image").attributes)

    # rename() changes the node's name; `None` clears it.
    edited = root.rename(id="image", name="image - new")

    print("before:", root.find(id="image").name)
    print("after: ", edited.find(id="image").name)


if __name__ == "__main__":
    main()
