"""Open a document, edit names and fields, save it back, delete it.

Two documents are edited: the collection (rename the image's *entry*) and the
image itself (rename it and its coordinate system). Each `save` rewrites
exactly one document; edits return a new tree and the opened one is untouched.
On `open_resolved` the entry's name wins over the document's. Finally
`delete(cascade=True)` removes a second, scratch image: its entry *and* the
document it points at.

Run with: pixi run --environment dev python examples/open_edit_save.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid
from _images import image


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    image_url, url = str(base / "image"), str(base / "zarr.json")
    stub = ngc.create(image_url, image(2, "image"), overwrite=True)
    scratch = ngc.create(str(base / "scratch"), image(3, "scratch"), overwrite=True)
    root = ngc.new_collection(id=uid(1), name="experiment").add_external(stub, scratch)
    ngc.create(url, root, overwrite=True)

    # Edit the collection: the image's entry gets a new name.
    opened = ngc.open(url)
    edited = opened.find(uid(2)).rename("Raw image")
    ngc.save(edited)
    print("opened tree still :", opened.find(uid(2)).name)  # edits never mutate

    # Edit the image document itself: rename it and its coordinate system.
    img = ngc.open(image_url)
    assert isinstance(img, ngc.MultiscaleNode)  # narrows the type for the access below
    (system,) = img.coordinate_systems
    img = img.set_coordinate_systems([system.model_copy(update={"name": "stage"})])
    ngc.save(img.rename("image-v2"))

    view = ngc.open_resolved(url)
    node = view.find(uid(2))
    assert isinstance(node, ngc.MultiscaleNode)
    print("entry name wins   :", node.name)
    print("image document    :", ngc.open(image_url).name)
    print("image system name :", node.coordinate_systems[0].name)

    # Drop the scratch image: its entry from the collection and its own document.
    touched = ngc.delete(ngc.open(url).find(uid(3)), cascade=True)
    print(
        "documents touched :", [Path(u).relative_to(base).as_posix() for u in touched]
    )
    print("after delete      :", [n.name for n in ngc.open(url).walk()])


if __name__ == "__main__":
    main()
