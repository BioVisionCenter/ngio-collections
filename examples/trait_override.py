"""Traits on the declaring entry vs. traits in the image's own document.

A multiscale can carry traits in two places (RFC-8 revision 1 §3.1):

* in its **own document** (`open()` the image, `set_trait`, `save()`);
* on the **entry** that declares it in a collection (`set_trait` on the stub
  `create()` returned, or on the entry in an opened collection).

On `open_resolved()` the two lists combine: traits of different types are
united, and when both carry a trait of the *same* type the collection's entry
wins, as a whole object. The entry is written into the collection document
only, so you never need write access to the image to annotate it.

Run with: pixi run python examples/trait_override.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid

RENDERING = "https://napari.org/ngff/rendering"
VISIBLE = "https://napari.org/ngff/visible"


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    image_url, url = str(base / "image"), str(base / "zarr.json")
    ngc.register_extension(
        {
            "id": "https://napari.org/ngff/",
            "version": "1.0",
            "schemas": [
                {"type": "jsonschema", "url": "https://napari.org/ngff/1.0/schema.json"}
            ],
        }
    )

    cs, sc = uid(0x20), uid(0xC)
    image = ngc.new_multiscale(
        id=uid(2),
        name="image",
        coordinate_systems=[
            ngc.CoordinateSystem(id=cs, axes=[ngc.Axis(name="y"), ngc.Axis(name="x")])
        ],
        scales=[
            ngc.Scale(
                id=sc,
                path=ngc.ZarrPath(href="./s0"),
                coordinate_transformations=[
                    ngc.ScaleTransformation(
                        scale=[1.0, 1.0],
                        input=ngc.ReferenceObj(type="scale", ref=sc),
                        output=ngc.ReferenceObj(type="coordinate_system", ref=cs),
                    )
                ],
            )
        ],
        traits=[
            {
                "type": RENDERING,
                "contrast_limits": [0, 4000],
                "gamma": 1.0,
            },  # the image's own default
            ngc.LabelsTrait(),  # only in the image document
        ],
    )
    stub = ngc.create(image_url, image, overwrite=True)

    # Decorate the ENTRY: overrides the rendering trait, adds a visibility trait.
    stub = stub.set_traits(
        {"type": RENDERING, "contrast_limits": [0, 1500]},
        {"type": VISIBLE, "visible": False},
    )
    root = ngc.new_collection(id=uid(1), name="root").add_external(stub)
    ngc.create(url, root, overwrite=True)

    def show(label: str) -> None:
        node = ngc.open_resolved(url).find(uid(2))
        traits = {
            k.rsplit("/", 1)[-1]: {kk: vv for kk, vv in v.items() if kk != "type"}
            for k, v in node.traits.items()
        }
        print(f"{label:<20}", traits)

    show(
        "entry overrides"
    )  # rendering: entry wins whole; labels survives; visible added

    # Edit the IMAGE document: its own rendering trait changes, but the entry still wins.
    img = ngc.open(image_url).set_trait(
        {"type": RENDERING, "contrast_limits": [9, 9], "gamma": 2.0}
    )
    ngc.save(img)
    show("image edited")

    # Edit the ENTRY in the collection (open, not open_resolved: views are read-only).
    root = ngc.open(url)
    ngc.save(root.find(uid(2)).drop_traits(RENDERING))
    show("entry trait dropped")  # the image's own rendering trait shows through

    print("validation:", ngc.open_resolved(url).validate(ngc.ALL_VALIDATORS))
    print("\ncollection document:\n" + Path(url).read_text())


if __name__ == "__main__":
    main()
