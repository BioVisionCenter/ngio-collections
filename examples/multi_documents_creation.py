"""Compose a multi-document collection bottom-up with references.

Each multiscale is written to its own zarr document; `create()` returns a
reference stub `Node` (`{type, ref, path}`, nothing else) locating it. The
parent collection is built in memory and the references are attached with
`add_ref()`; stored paths are relativized against the parent document when it
is written.

    root (collection.json)
    ├── -> ./image.zarr  (ref = the image's id)
    └── -> ./labels.zarr (ref = the labels' id)

Run with: pixi run python examples/multi_documents_creation.py
"""

from pathlib import Path

from basic_creation import IMAGE, IMAGE_SCALES, IMAGE_SPACE, ROOT, build_multiscale

import ngio_collections as ngc

LABELS = "0192f3a0-e000-7000-8000-000000000011"
LABELS_SPACE = "0192f3a0-e000-7000-8000-000000000012"
LABELS_SCALES = (
    "0192f3a0-e000-7000-8000-000000000013",
    "0192f3a0-e000-7000-8000-000000000014",
)


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")
    image_url = str(base_path / "image.zarr")
    labels_url = str(base_path / "labels.zarr")

    # Write the image to its own zarr; open it back for a portable reference.
    image = build_multiscale(IMAGE, "image", IMAGE_SPACE, IMAGE_SCALES)
    rf_image = ngc.create(image_url, image, overwrite=True)
    image_ref = ngc.open(image_url).ref()  # ReferenceObj(type, ref=IMAGE, path=...)

    # The labels multiscale records, in its `labels` attribute, the image it
    # segments — via that portable reference (relativized when written).
    labels = build_multiscale(
        LABELS,
        "labels",
        LABELS_SPACE,
        LABELS_SCALES,
        extra_attr=ngc.LabelsAttribute(source=[image_ref]),
    )
    rf_labels = ngc.create(labels_url, labels, overwrite=True)
    print("image ref :", image_ref.model_dump(exclude_none=True))

    # Build the parent in memory and attach both references (still detached:
    # paths are relativized when the document is written).
    root = ngc.new_node("collection", id=ROOT, name="root").add_ref(
        rf_image, rf_labels
    )
    ngc.create(url, root, overwrite=True)

    print(f"\nwrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()
