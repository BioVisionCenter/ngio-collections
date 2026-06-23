"""The main node-editing API, on the collection from basic_creation.py.

Edits are functional: every method returns a NEW tree and never touches the
original. No IO here — these all operate on the in-memory value.

Run with: pixi run python examples/basic_ops.py
"""

from basic_creation import build_collection


def main() -> None:
    root = build_collection()

    # Navigate: walk() yields every node depth-first; find() grabs one by id.
    print("nodes:", [n.id for n in root.walk()])
    print("found:", root.find("nuclei").id)

    # Attributes: set_attrs merges in, drop_attrs removes keys.
    edited = root.set_attrs("image", {"channels": 2, "stain": "DAPI"})
    edited = edited.drop_attrs("image", "stain")
    print("image attrs:", edited.find("image").attributes)

    # Rename and remove return new trees too.
    edited = edited.rename("nuclei", "nuclei-seg")
    edited = edited.remove("labels")
    print("after remove:", [n.id for n in edited.walk()])

    # The original is untouched throughout — that is the whole point.
    assert root.find("image").attributes == {}
    assert root.find("labels") is not None
    print("\noriginal unchanged:", [n.id for n in root.walk()])


if __name__ == "__main__":
    main()
