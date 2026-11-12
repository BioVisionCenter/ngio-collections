"""Traits on the declaring entry vs. traits in the image's own document.

A multiscale can carry traits in two places (the trait-combination rule of the RFC-8 revision):

* in its **own document** (`open()` the image, `set_trait`, `save()`);
* on the **entry** that declares it in a collection (`set_trait` on the stub
  `create()` returned, or on the entry in an opened collection, as here).

On `open_resolved()` the two lists combine: traits of different types are
united, and when both carry a trait of the *same* type the collection's entry
wins, as a whole object. Here a labels image colours label 1 red; a collection
recolours it blue on the entry alone, so you never need write access to the
image to annotate it.

Run with: pixi run --environment dev python examples/trait_override.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid
from _images import image


def labels(rgba: list[int]) -> ngc.LabelsTrait:
    return ngc.LabelsTrait(label_attributes=[ngc.LabelObj(label_value=1, rgba=rgba)])


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    image_url, url = str(base / "image"), str(base / "zarr.json")

    # The image's own document says label 1 is red.
    stub = ngc.create(
        image_url, image(2, "nuclei", traits=[labels([255, 0, 0, 255])]), overwrite=True
    )
    root = ngc.new_collection(id=uid(1), name="root").add_external(stub)
    ngc.create(url, root, overwrite=True)

    def show(label: str) -> None:
        node = ngc.open_resolved(url).find(uid(2))
        print(f"{label:<20}", node[ngc.LabelsTrait].label_attributes[0].rgba)

    show("image only")  # red: the image's own trait

    # Decorate the ENTRY in the collection (open, not open_resolved: views are
    # read-only): a labels trait of the same type overrides the image's.
    root = ngc.open(url)
    ngc.save(root.find(uid(2)).set_trait(labels([0, 0, 255, 255])))
    show("entry overrides")  # blue: the entry wins as a whole object

    # Edit the IMAGE document: its own colour changes, but the entry still wins.
    ngc.save(ngc.open(image_url).set_trait(labels([0, 255, 0, 255])))
    show("image edited")  # still blue; the image document alone says green

    print("\ncollection document:\n" + Path(url).read_text())


if __name__ == "__main__":
    main()
