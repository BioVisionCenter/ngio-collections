"""Nested collections: embedded or external, `externalize`, and `open_ref`.

Unlike multiscales, a collection may be embedded in its parent document or be
its own document (a `.json` file or a Zarr group). `externalize` moves an
embedded collection into its own document and leaves its declaring entry
behind; a typed `ReferenceObj` with a `path` can then be opened directly.

Run with: pixi run python examples/nested_collections.py
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
    root = ngc.new_collection(id=uid(1), name="root").add(labels)  # labels embedded
    ngc.create(url, root, overwrite=True)
    print("embedded :", [(n.name, n.is_external) for n in ngc.open(url).walk()])

    # Split the labels collection into a standalone JSON document.
    opened = ngc.open(url)
    updated = ngc.externalize(
        opened.find(uid(3)), str(base / "labels.json"), overwrite=True
    )
    print("external :", [(n.name, n.is_external, n.ref_path) for n in updated.walk()])

    # A typed reference to the labels collection, resolved from the root document.
    entry = updated.find(uid(3))
    ref = ngc.ReferenceObj(type="collection", ref=entry.id, path=entry.path)
    labels_doc = ngc.open_ref(ref, updated.document_url)
    print("open_ref :", labels_doc.document_url, [n.name for n in labels_doc.walk()])
    print("resolved :", [n.name for n in ngc.open_resolved(url).walk()])


if __name__ == "__main__":
    main()
