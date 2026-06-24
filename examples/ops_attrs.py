"""Typed and untyped attribute access on a node.

Reads/membership use subscript on the node; writes are functional and return a
new tree (nodes are immutable):

    plate = node[PlateAttribute]                 # typed, validated read
    PlateAttribute in node                       # membership
    root  = root.set_attr(id=..., value=plate)   # write -> new tree

The raw `attributes` dict stays the source of truth, so untyped `set_attrs` /
`drop_attrs` keep working for arbitrary keys that have no typed model.

Run with: pixi run python examples/ops_attrs.py
"""

import ngio_collections as ngc
from basic_creation import build_collection


def main() -> None:
    root = build_collection()

    # Typed write: set_attr() validates and writes a spec-shaped value, then
    # returns a new tree (`value` may be a model instance or a raw dict + attr).
    plate = ngc.PlateAttribute(
        columns=[ngc.ColumnObj(id="1"), ngc.ColumnObj(id="2")],
        rows=[ngc.RowObj(id="A")],
    )
    root = root.set_attr(id="image", value=plate)

    # Typed read + membership, straight off the node.
    img = root.find(id="image")
    if ngc.PlateAttribute in img:
        plate = img[ngc.PlateAttribute]
        print(f"plate: {len(plate.rows)} rows x {len(plate.columns)} columns")

    # Untyped merge for arbitrary keys with no typed model.
    root = root.set_attrs(id="image", values={"other": {"tag": "image"}})
    edited = root.drop_attrs(id="image", keys=("other",))
    print("with other:", list(root.find(id="image").attributes))
    print("dropped:   ", list(edited.find(id="image").attributes))

    # Typed delete: drop_attr() removes the key the model maps to.
    no_plate = root.drop_attr(id="image", attr=ngc.PlateAttribute)
    print("plate present:", ngc.PlateAttribute in no_plate.find(id="image"))


if __name__ == "__main__":
    main()
