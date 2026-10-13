"""Open a multi-document collection inlined, inspect across boundaries, snapshot.

A parent collection that *references* two child image documents is opened two
ways: `open()` leaves the cross-document children as `{type, ref, path}`
references, while `open_inlined()` resolves them into one read-only tree, each
reference replaced by the node it points at (verbatim: a reference carries no
name or body of its own). We walk the resolved tree, read each node's on-disk
origin via `ref()`, validate it, and `save_inlined()` a flat copy.

Run with: pixi run python examples/open_inlined_inspect.py
"""

from pathlib import Path

import ngio_collections as ngc

ROOT = "0192f3a0-e000-7000-8000-000000000051"
IMAGE = "0192f3a0-e000-7000-8000-000000000052"
NUCLEI = "0192f3a0-e000-7000-8000-000000000053"


def _setup(base: Path) -> str:
    """Write a parent collection referencing two child image documents."""
    rf_img = ngc.create(
        str(base / "image.zarr"),
        ngc.new_node("multiscale", id=IMAGE, name="image", attributes={"role": "raw"}),
        overwrite=True,
    )
    rf_lbl = ngc.create(
        str(base / "nuclei.zarr"),
        ngc.new_node(
            "multiscale", id=NUCLEI, name="nuclei", attributes={"role": "label"}
        ),
        overwrite=True,
    )
    root = ngc.new_node("collection", id=ROOT, name="root").add_ref(rf_img).add_ref(rf_lbl)
    url = str(base / "collection.json")
    ngc.create(url, root, overwrite=True)
    return url


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = _setup(base)

    # open(): cross-document children stay references (not resolved).
    unresolved = [n.ref().model_dump(exclude_none=True) for n in ngc.open(url).walk() if n.is_reference]
    print("open() unresolved refs :", unresolved)

    # open_inlined(): references resolved across boundaries into one tree.
    view = ngc.open_inlined(url)
    print("inlined ref            :", view.ref().model_dump(exclude_none=True))
    print("inlined nodes:")
    for n in view.walk():
        print(f"  {n.name:<7} {dict(n.attributes)}  origin={n.ref().path.href}")

    print("image attributes       :", dict(view.find(IMAGE).attributes))
    print(
        "validate               :",
        ngc.validate(view, validators=(ngc.id_is_uuid, ngc.well_under_plate)),
        ngc.unique_ids(view),
    )

    # Snapshot the resolved tree into one self-contained document.
    flat = str(base / "flat.json")
    ngc.save_inlined(view, flat, overwrite=True)
    print("snapshot               :", flat)


if __name__ == "__main__":
    main()
