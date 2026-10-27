"""Open a document, edit names and fields, save it back.

Two documents are edited: the collection (rename the image's *entry*) and the
image itself (rename it and its coordinate system). Each `save` rewrites
exactly one document; edits return a new tree, the opened one is untouched.

Run with: pixi run python examples/open_edit_save.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid
from _images import image


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    image_url, url = str(base / "image"), str(base / "zarr.json")
    stub = ngc.create(image_url, image(2, "image"), overwrite=True)
    root = ngc.new_collection(id=uid(1), name="experiment").add_external(stub)
    ngc.create(url, root, overwrite=True)

    # Edit the collection: the image's entry gets a new name.
    root = ngc.open(url)
    ngc.save(root.find(uid(2)).rename("Raw image"))

    # Edit the image document itself: rename it and its coordinate system.
    img = ngc.open(image_url)
    assert isinstance(img, ngc.MultiscaleNode)
    (system,) = img.coordinate_systems
    img = img.set_coordinate_systems([system.model_copy(update={"name": "stage"})])
    ngc.save(img.rename("image-v2"))

    view = ngc.open_resolved(url)
    node = view.find(uid(2))
    assert isinstance(node, ngc.MultiscaleNode)
    print("entry name wins   :", node.name)
    print("image system name :", node.coordinate_systems[0].name)
    print("image document    :", ngc.open(image_url).name)
    print("validation        :", view.validate(ngc.ALL_VALIDATORS))
    print("\n" + Path(url).read_text())


if __name__ == "__main__":
    main()
