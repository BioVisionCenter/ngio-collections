"""Open a multi-document collection inlined, inspect across boundaries, snapshot.

A parent collection that *references* two child image documents is opened two
ways: `open()` leaves the cross-document children as references, while
`open_inlined()` resolves them into one read-only tree (a stub's attributes
overlay its target, stub wins). We walk the resolved tree, read each node's
on-disk origin via `ref()`, validate it, and `save_inlined()` a flat copy.

Run with: pixi run python examples/open_inlined_inspect.py
"""

from pathlib import Path

import ngio_collections as ngc


def _setup(base: Path) -> str:
    """Write a parent collection referencing two child image documents."""
    rf_img = ngc.create(
        str(base / "image.zarr"),
        ngc.new_node("multiscale", id="image", attributes={"role": "raw"}),
        overwrite=True,
    )
    rf_lbl = ngc.create(
        str(base / "nuclei.zarr"),
        ngc.new_node("multiscale", id="nuclei", attributes={"role": "label"}),
        overwrite=True,
    )
    # Decorate the image stub: this overlay wins when read inlined.
    rf_img = rf_img.set_attrs({"display": "grayscale"})
    root = ngc.new_node("collection", id="root").add_ref(rf_img).add_ref(rf_lbl)
    url = str(base / "collection.json")
    ngc.create(url, root, overwrite=True)
    return url


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = _setup(base)

    # open(): cross-document children stay references (not resolved).
    unresolved = [n.type for n in ngc.open(url).walk() if n.is_reference]
    print("open() unresolved refs :", unresolved)

    # open_inlined(): references resolved across boundaries into one tree.
    view = ngc.open_inlined(url)
    print("inlined ref            :", view.ref())
    print("inlined nodes:")
    for n in view.walk():
        origin = None if n.is_detached else n.ref().path.path
        print(f"  {n.id!s:<7} {dict(n.attributes)}  origin={origin}")

    # The image stub's 'display' overlay is merged on top of its target.
    print("image attributes       :", dict(view.find("image").attributes))
    print(
        "validate               :",
        ngc.validate(view, validators=(ngc.well_under_plate, ngc.scale_matches_axes)),
    )

    # Snapshot the resolved tree into one self-contained document.
    flat = str(base / "flat.json")
    ngc.save_inlined(view, flat, overwrite=True)
    print("snapshot               :", flat)


if __name__ == "__main__":
    main()
