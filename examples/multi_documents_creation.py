"""Compose a multi-document collection bottom-up with references.

Each multiscale is written to its own zarr document; `create()` returns a typed
`RefNode` stub locating it. The parent collection is built in memory and the
references are attached with `add_ref()`; the stored paths are relativized
against the parent document when it is written.

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

    # Write each multiscale to its own zarr; keep the returned stubs.
    rf_image = ngc.create(str(base_path / "image.zarr"), build_multiscale("image"), overwrite=True)
    rf_labels = ngc.create(str(base_path / "labels.zarr"), build_multiscale("labels"), overwrite=True)
    print("image  stub:", rf_image.model_dump())
    print("labels stub:", rf_labels.model_dump())

    # Build the parent in memory and attach the references. The parent can be
    # detached here — paths are relativized when the document is written.
    root = ngc.CollectionNode(id="root")
    root = root.add_ref(parent_id="root", ref=rf_image)
    root = root.add_ref(parent_id="root", ref=rf_labels)
    ngc.create(url, root, overwrite=True)

    print(f"\nwrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()
