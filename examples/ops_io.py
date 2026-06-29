"""Read with `open` / `open_inlined`, write with `create` / `save_inlined`, `delete`.

`open()` reads one document; cross-document children stay reference stubs and the
tree is editable + writable single-document with `save()`. `open_inlined()`
resolves references across boundaries into a read-only tree (a stub's attributes
overlay its target, stub wins); `save_inlined()` snapshots that resolved tree to
one self-contained file. `delete()` removes a node's document from disk.

Documents compose bottom-up: `create()` hands back a reference stub `Node` you
decorate and attach to a parent with `add_ref`.

Run with: pixi run python examples/ops_io.py
"""

from pathlib import Path

import ngio_collections as ngc


def _state(node: ngc.Node) -> str:
    return "detached" if node.is_detached else "document"


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")

    # Write a child image document; create() hands back a reference stub.
    image = ngc.new_node(
        "multiscale", id="image", name="image", attributes={"role": "raw"}
    )
    rf_image = ngc.create(str(base_path / "image.zarr"), image, overwrite=True)

    # Decorate the stub with an overlay the parent layers onto the child on read,
    # then attach it to a detached parent. Paths are relativized when written.
    rf_image = rf_image.set_attrs({"in_collection": True})
    root = ngc.new_node("collection", id="root").add_ref(rf_image)
    ngc.create(url, root, overwrite=True)

    # open(): cross-document children stay references.
    print("open():")
    for node in ngc.open(url).walk():
        print(f"  {str(node.id):<8} {_state(node):<9} {type(node).__name__}")

    # open_inlined(): references resolved by id; stub attributes overlay (win).
    print("open_inlined():")
    view = ngc.open_inlined(url)
    for node in view.walk():
        print(f"  {str(node.id):<8} {_state(node):<9} {type(node).__name__}")
    print("  image attributes:", view.find("image").attributes)
    print("  image ref():", view.find("image").ref().model_dump())

    # save_inlined(): flatten the resolved tree into one self-contained file.
    flat_url = str(base_path / "flat.json")
    ngc.save_inlined(view, flat_url, overwrite=True)
    print("\nflattened snapshot:\n")
    print(Path(flat_url).read_text())

    # delete(): remove the image document from disk (it roots its own file).
    deleted = ngc.delete(view.find("image"))
    print("deleted:", deleted)


if __name__ == "__main__":
    main()
