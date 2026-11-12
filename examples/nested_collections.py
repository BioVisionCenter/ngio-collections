"""Nested nodes: embedded or external, `externalize`, and `open_ref`.

A collection or a multiscale may be embedded in its parent document or be its
own document (a `.json` file or a Zarr group). Here the root embeds a `labels`
collection and inlines an `overview` image, while `nuclei` is its own document.
`externalize` moves an embedded node into its own document and leaves its
declaring entry behind; a typed `ReferenceObj` with a `path` can then be opened
directly.

Run with: pixi run --environment dev python examples/nested_collections.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid
from _images import image


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base / "zarr.json")
    stub = ngc.create(str(base / "nuclei"), image(2, "nuclei"), overwrite=True)
    labels = ngc.new_collection(id=uid(3), name="labels").add_external(stub)
    # labels is embedded; the overview image is inlined, `data` and all
    root = ngc.new_collection(id=uid(1), name="root").add(labels, image(4, "overview"))
    ngc.create(url, root, overwrite=True)
    opened = ngc.open(url)
    print("embedded :", [(n.name, n.is_external) for n in opened.walk()])

    # Split the labels collection into a standalone JSON document.
    ngc.externalize(opened.find(uid(3)), str(base / "labels.json"), overwrite=True)
    reopened = ngc.open(url)
    print("external :", [(n.name, n.is_external, n.ref_path) for n in reopened.walk()])

    # A typed reference to the labels collection, resolved from the root document.
    entry = reopened.find(uid(3))
    ref = ngc.ReferenceObj(type="collection", ref=entry.id, path=entry.path)
    labels_doc = ngc.open_ref(ref, reopened.document_url)
    print(
        "open_ref :",
        Path(labels_doc.document_url).name,
        [n.name for n in labels_doc.walk()],
    )
    print("resolved :", [n.name for n in ngc.open_resolved(url).walk()])


if __name__ == "__main__":
    main()
