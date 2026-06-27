"""Update attributes on a *stub* (the reference) vs. on the *target node* itself.

A parent collection references a child document through a stub. Attributes can
live in two places:

* on the **stub** — carried by the reference in the parent; an *overlay* the
  parent layers onto the child when it reads it (`set_attrs` on the stub `Node`
  returned by `create()`);
* on the **target node** — the child document's own attributes (`open()` the
  child, `set_attrs`, `save()`).

On `open_inlined()` the two are merged with the **stub winning** on conflicts,
while keys that exist only on the target survive (see
`resolve/_build.py::_merge_record`). This example writes both and prints the
resolved result so you can see which value wins.

Key point: a stub's overlay attributes are written into the **parent** document,
never into the child — so you never need write access to the child to attach
attributes to it. The child can be read-only or remote (e.g. on http): you only
ever write the local parent. And you don't even need to write the child to
*reference* it — `create(child)` is just a convenience that returns a stub; when
the child already exists you mint the reference in memory with
`new_node(ref=Reference(...))` + `add_ref` (shown at the end). `open_inlined`
still has to *read* the child to merge attributes, but never writes it.

Run with: pixi run python examples/stub_attrs.py
"""

from pathlib import Path

import ngio_collections as ngc


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    child_url = str(base / "image.zarr")
    parent_url = str(base / "collection.json")

    # The child document carries its own attributes ("channels" + "display").
    image = ngc.new_node(
        "multiscale",
        id="image",
        attributes={"channels": ["DAPI"], "display": "target-default"},
    )
    stub = ngc.create(child_url, image, overwrite=True)

    # Decorate the STUB: an overlay stored on the reference in the parent. It
    # overrides "display" and adds "in_collection" — the child file is untouched.
    stub = stub.set_attrs({"display": "stub-override", "in_collection": True})
    root = ngc.new_node("collection", id="root").add_ref(stub)
    ngc.create(parent_url, root, overwrite=True)

    # Resolve: stub overlay wins on "display"; target-only "channels" survives.
    view = ngc.open_inlined(parent_url)
    print("after stub overlay :", dict(view.find("image").attributes))

    # Now edit the TARGET NODE itself: open the child, change its own attribute,
    # and save it back to its own document.
    edited = ngc.open(child_url).set_attrs({"channels": ["DAPI", "GFP"]})
    ngc.save(edited)

    # Resolve again: the target edit shows through ("channels"), but the stub
    # overlay still wins on "display".
    view = ngc.open_inlined(parent_url)
    print("after target edit  :", dict(view.find("image").attributes))

    # Re-open the collection and change the STUB overlay again. `open_inlined`
    # gives a read-only resolved tree, so to edit the stub we `open()` the parent
    # (non-inlined: the child stays a reference whose overlay we can update). An
    # unresolved stub has no local id of its own, so we locate it as the
    # reference child rather than by id, `set_attrs` on it, and `save()` the parent.
    collection = ngc.open(parent_url)
    stub = next(n for n in collection.walk() if n.is_reference)
    collection = stub.set_attrs({"display": "stub-override-v2"})
    ngc.save(collection)

    # Resolve once more: the new overlay wins, the target's "channels" persists.
    view = ngc.open_inlined(parent_url)
    print("after stub re-edit :", dict(view.find("image").attributes))

    # Referencing a child you must NOT (or cannot) write. `create(child)` above
    # was only a convenience to get a stub; when the child already exists — or is
    # read-only / remote (e.g. `ZarrPath(path="http://host/image.zarr")`) — mint
    # the reference in memory with `new_node(ref=...)` and attach it. No write
    # ever touches the child; `create` below writes only the local parent.
    stub = ngc.new_node(
        "multiscale",
        id="image",
        ref=ngc.Reference(path=ngc.ZarrPath(path=child_url), id="image"),
        attributes={"display": "in-memory-stub"},  # overlay set at construction
    )
    other_url = str(base / "collection-readonly-child.json")
    ngc.create(other_url, ngc.new_node("collection", id="root").add_ref(stub), overwrite=True)

    view = ngc.open_inlined(other_url)
    print("ref without writing:", dict(view.find("image").attributes))


if __name__ == "__main__":
    main()
