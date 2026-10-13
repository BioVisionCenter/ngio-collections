"""Reference a child document without writing it; edit the target, not the ref.

A parent references a child through a `{type, ref, path}` entry and nothing
else: no name, no body. The referenced node brings its own, and `open_inlined()`
splices it in verbatim. So to change what a consumer sees of a child, edit the
**target node** in its own document (`open()` the child, `set_attrs`, `save()`);
trying to decorate the reference itself raises `NodeStateError`.

You never need to write the child to reference it. `create(child)` returns a
stub as a convenience; when the child already exists — or is read-only or
remote (e.g. `ZarrPath(href="http://host/image.zarr")`) — mint the reference in
memory with `new_node(ref=Reference(...))` + `add_ref`, or `node.ref_stub()` on
an opened child. `open_inlined` still has to *read* the child, but never writes
it; `create` below writes only the local parent.

Run with: pixi run python examples/stub_attrs.py
"""

from pathlib import Path

import ngio_collections as ngc

ROOT = "0192f3a0-e000-7000-8000-000000000061"
IMAGE = "0192f3a0-e000-7000-8000-000000000062"
OTHER = "0192f3a0-e000-7000-8000-000000000063"


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    child_url = str(base / "image.zarr")
    parent_url = str(base / "collection.json")

    # The child document carries its own attributes.
    image = ngc.new_node(
        "multiscale", id=IMAGE, name="image", attributes={"channels": ["DAPI"]}
    )
    stub = ngc.create(child_url, image, overwrite=True)
    print("stub               :", stub.ref().model_dump(exclude_none=True))

    # A reference cannot be decorated: it has no body of its own.
    try:
        stub.set_attrs({"display": "overlay"})
    except ngc.NodeStateError as error:
        print("set_attrs on a ref :", error)

    root = ngc.new_node("collection", id=ROOT, name="root").add_ref(stub)
    ngc.create(parent_url, root, overwrite=True)
    view = ngc.open_inlined(parent_url)
    print("inlined            :", dict(view.find(IMAGE).attributes))

    # Edit the TARGET NODE itself: open the child, change its own attribute,
    # and save it back to its own document. The parent is untouched.
    edited = ngc.open(child_url).set_attrs({"channels": ["DAPI", "GFP"]})
    ngc.save(edited)
    view = ngc.open_inlined(parent_url)
    print("after target edit  :", dict(view.find(IMAGE).attributes))

    # Reference a child you must NOT (or cannot) write: mint the reference in
    # memory and attach it. No write ever touches the child.
    stub = ngc.new_node(
        "multiscale",
        ref=ngc.Reference(ref=IMAGE, path=ngc.ZarrPath(href=child_url)),
    )
    other_url = str(base / "collection-readonly-child.json")
    ngc.create(
        other_url,
        ngc.new_node("collection", id=OTHER, name="root").add_ref(stub),
        overwrite=True,
    )
    view = ngc.open_inlined(other_url)
    print("ref without writing:", dict(view.find(IMAGE).attributes))

    # When the child *is* readable, skip the hand-built Reference: `ref_stub()`
    # mints the same stub from an opened node (still never writing the child).
    stub = ngc.open(child_url).ref_stub()
    print("ref_stub shortcut  :", stub.type, stub.record.ref.ref, stub.ref_path)


if __name__ == "__main__":
    main()
