"""Typed and untyped attribute access on a node.

Reads/membership use subscript on the located node; writes are positioned edits
that return the new tree root (nodes are immutable):

    plate = node[PlateAttribute]                    # typed, validated read
    PlateAttribute in node                          # membership
    root  = root.find(id).set_attr(plate)           # write -> new tree root

The raw `attributes` dict stays the source of truth, so untyped `set_attrs` /
`drop_attrs` keep working for arbitrary keys that have no typed model.

Run with: pixi run python examples/ops_attrs.py
"""

import ngio_collections as ngc
from basic_creation import build_collection


def main() -> None:
    root = build_collection()

    # Typed write: set_attr() validates a model instance, then returns the root.
    plate = ngc.PlateAttribute(
        columns=[ngc.ColumnObj(id="1"), ngc.ColumnObj(id="2")],
        rows=[ngc.RowObj(id="A")],
    )
    root = root.find("image").set_attr(plate)

    # Typed read + membership, straight off the located node.
    img = root.find("image")
    if ngc.PlateAttribute in img:
        plate = img[ngc.PlateAttribute]
        print(f"plate: {len(plate.rows)} rows x {len(plate.columns)} columns")

    # Untyped merge for arbitrary keys with no typed model.
    root = root.find("image").set_attrs({"other": {"tag": "image"}})
    edited = root.find("image").drop_attrs("other")
    print("with other:", list(root.find("image").attributes))
    print("dropped:   ", list(edited.find("image").attributes))

    # Typed delete: drop_attrs() accepts attribute classes or raw string keys.
    no_plate = root.find("image").drop_attrs(ngc.PlateAttribute)
    print("plate present:", ngc.PlateAttribute in no_plate.find("image"))


if __name__ == "__main__":
    main()
