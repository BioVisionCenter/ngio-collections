"""Write and reload a collection with `create()`, `open()`, and `save()`.

`create()` writes a new collection to a URL.
`open()` loads it back.
`save()` rewrites only the documents that actually changed.

Run with: pixi run python examples/persist.py
"""

from pathlib import Path

from basic_creation import build_collection

import ngio_collections as ngc


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")
    # Sharing one Resolver lets it reuse its document cache across calls.
    resolver = ngc.Resolver(ngc.LocalStore())

    # create() writes the collection to disk for the first time.
    ngc.create(url, build_collection(), resolver)

    # open() loads it back; each node reports its storage state.
    root = ngc.open(url, resolver)
    for node in root.walk():
        print(f"  {node.id:<14} {node.state.value}")

    # Edit the in-memory tree with an in-memory node.
    root = root.add(parent_id="root", child=ngc.CollectionNode(id="analysis"))

    # save() writes only the documents that actually changed.
    written = ngc.save(root, resolver)
    print("written:", written)

    # A node that already lives on disk is added as a reference stub.
    # First write it independently, then point to it from the collection.

    multiscale_label = ngc.MultiscaleNode(
        id="segmentation",
        name="segmentation",
        attributes={"labels": {"source": "image"}},
    )
    ngc.create(
        str(base_path / "segmentation.zarr"),
        multiscale_label,
        resolver,
    )
    root = root.add(
        parent_id="root",
        child=ngc.RefMultiscaleNode(
            id="segmentation", path=ngc.ZarrPath(path="./segmentation.zarr")
        ),
    )
    written = ngc.save(root, resolver)
    print("written:", written)

    # Reopen and compare storage states:
    # embedded nodes show 'document'; referenced ones show 'boundary'.
    for node in ngc.open(url, resolver).walk():
        print(f"  {node.id:<14} {node.state.value}")


if __name__ == "__main__":
    main()
