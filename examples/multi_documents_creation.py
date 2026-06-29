"""Compose a multi-document collection bottom-up with references.

Each multiscale is written to its own zarr document; `create()` returns a
reference stub `Node` locating it. The parent collection is built in memory and
the references are attached with `add_ref()`; stored paths are relativized against
the parent document when it is written.

    root (collection.json)
    ├── image  -> ./image.zarr
    └── labels -> ./labels.zarr

Run with: pixi run python examples/multi_documents_creation.py
"""

from pathlib import Path

from basic_creation import build_multiscale

import ngio_collections as ngc


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")
    image_url = str(base_path / "image.zarr")
    labels_url = str(base_path / "labels.zarr")

    # Write the image to its own zarr; open it back for a portable reference.
    rf_image = ngc.create(image_url, build_multiscale("image"), overwrite=True)
    image_ref = ngc.open(image_url).ref()  # ReferenceObj(id="image", path=image.zarr)

    # The labels multiscale records, in its `labels` attribute, the image it
    # segments — via that portable reference.
    labels = build_multiscale(
        "labels", extra_attr=ngc.LabelsAttribute(source=[image_ref])
    )
    rf_labels = ngc.create(labels_url, labels, overwrite=True)
    print("image ref :", image_ref.model_dump())

    # Build the parent in memory and attach both references (still detached:
    # paths are relativized when the document is written).
    root = ngc.new_node("collection", id="root").add_ref(rf_image).add_ref(rf_labels)
    ngc.create(url, root, overwrite=True)

    print(f"\nwrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()
