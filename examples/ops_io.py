"""Read with `open` / `open_inlined`, write with `create` / `save_inlined`, `delete`.

`open()` reads one document; cross-document children stay `{type, ref, path}`
references and the tree is editable + writable single-document with `save()`.
`open_inlined()` resolves references across boundaries into a read-only tree:
each reference is replaced by the node it points at, verbatim (a reference has
no name or body of its own). `save_inlined()` snapshots that resolved tree to
one self-contained file. `delete()` removes a node's document from disk.

Documents compose bottom-up: `create()` hands back a reference stub `Node` you
attach to a parent with `add_ref`.

Run with: pixi run python examples/ops_io.py
"""

from pathlib import Path

import ngio_collections as ngc

ROOT = "0192f3a0-e000-7000-8000-000000000031"
IMAGE = "0192f3a0-e000-7000-8000-000000000032"


def _state(node: ngc.Node) -> str:
    return "detached" if node.is_detached else "document"


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")

    # Write a child image document; create() hands back a reference stub.
    image = ngc.new_node("multiscale", id=IMAGE, name="image", attributes={"role": "raw"})
    rf_image = ngc.create(str(base_path / "image.zarr"), image, overwrite=True)

    # Attach it to a detached parent. Paths are relativized when written.
    root = ngc.new_node("collection", id=ROOT, name="root").add_ref(rf_image)
    ngc.create(url, root, overwrite=True)

    # open(): cross-document children stay references (no id of their own).
    print("open():")
    for node in ngc.open(url).walk():
        label = node.name if node.id else f"-> {node.ref_path}"
        print(f"  {label:<16} {_state(node):<9} {type(node).__name__}")

    # open_inlined(): references resolved by id into the declared nodes.
    print("open_inlined():")
    view = ngc.open_inlined(url)
    for node in view.walk():
        print(f"  {node.name:<16} {_state(node):<9} {type(node).__name__}")
    print("  image attributes:", view.find(IMAGE).attributes)
    print("  image ref():", view.find(IMAGE).ref().model_dump(exclude_none=True))

    # save_inlined(): flatten the resolved tree into one self-contained file.
    flat_url = str(base_path / "flat.json")
    ngc.save_inlined(view, flat_url, overwrite=True)
    print("\nflattened snapshot:\n")
    print(Path(flat_url).read_text())

    # delete(): remove the image document from disk (it roots its own file).
    deleted = ngc.delete(view.find(IMAGE))
    print("deleted:", deleted)


if __name__ == "__main__":
    main()
