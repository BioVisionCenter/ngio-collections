"""Open a document, edit traits / names / fields, save it back.

Two documents are edited: the collection (rename the image's *entry*, set a
trait on it) and the image itself (rename its coordinate system). Each `save`
rewrites exactly one document; edits return a new tree, the opened one is
untouched.

Run with: pixi run python examples/open_edit_save.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid

RENDERING = "https://napari.org/ngff/rendering"


def image(ms_id: str, cs_id: str, scale_id: str) -> ngc.Node:
    return ngc.new_multiscale(
        id=ms_id,
        name="image",
        coordinate_systems=[
            ngc.CoordinateSystem(
                id=cs_id, name="physical", axes=[ngc.Axis(name="y"), ngc.Axis(name="x")]
            )
        ],
        scales=[
            ngc.Scale(
                id=scale_id,
                path=ngc.ZarrPath(href="./s0"),
                coordinate_transformations=[
                    ngc.ScaleTransformation(
                        scale=[1.0, 1.0],
                        input=ngc.ReferenceObj(type="scale", ref=scale_id),
                        output=ngc.ReferenceObj(type="coordinate_system", ref=cs_id),
                    )
                ],
            )
        ],
    )


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
    stub = ngc.create(image_url, image(uid(2), uid(0x20), uid(0xC)), overwrite=True)
    root = ngc.new_collection(id=uid(1), name="experiment").add_external(stub)
    ngc.create(url, root, overwrite=True)

    # Edit the collection: the image's entry gets a new name and a trait.
    root = ngc.open(url)
    root = root.find(uid(2)).rename("Raw image")
    root = root.find(uid(2)).set_trait(
        {"type": RENDERING, "contrast_limits": [0, 1500]}
    )
    ngc.save(root)

    # Edit the image document itself: rename its coordinate system.
    img = ngc.open(image_url)
    assert isinstance(img, ngc.MultiscaleNode)
    (system,) = img.coordinate_systems
    img = img.set_coordinate_systems([system.model_copy(update={"name": "stage"})])
    img = img.rename("image-v2")
    ngc.save(img)

    view = ngc.open_resolved(url)
    node = view.find(uid(2))
    assert isinstance(node, ngc.MultiscaleNode)
    print("entry name wins   :", node.name)
    print("trait on the entry:", node.traits[RENDERING])
    print("image system name :", node.coordinate_systems[0].name)
    print("validation        :", view.validate(ngc.ALL_VALIDATORS))
    print("\n" + Path(url).read_text())


if __name__ == "__main__":
    main()
