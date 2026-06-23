"""Modify a saved collection and resave it.

Two ways to add a child:
  1. a fresh in-memory node -> embeds into the parent document (no new file)
  2. a reference to a node that already lives on disk -> a path stub

Saves are document-granular: only the documents that actually changed get
written.

Run with: pixi run python examples/collection_edit.py
"""

import tempfile
from pathlib import Path

import ngio_collections as ngc
from basic_creation import build_collection


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        # One resolver shared across calls so its document cache is reused.
        resolver = ngc.Resolver(ngc.LocalStore())

        # Persist the base collection, and — separately — a standalone image
        # that "already exists on disk" for scenario 2 below.
        collection_url = str(base / "collection.json")
        ngc.create(collection_url, build_collection(), resolver)
        ngc.create(
            str(base / "extra_image.zarr"),
            ngc.MultiscaleNode(id="extra-image", name="extra"),
            resolver,
        )

        # Reopen the collection to edit it.
        root = ngc.open(collection_url, resolver)

        # 1) A fully in-memory node: detached, so it embeds in root's document.
        root = root.add("root", ngc.CollectionNode(id="analysis"))

        # 2) A reference to the image we wrote above.
        root = root.add(
            "root",
            ngc.RefMultiscaleNode(
                id="extra-image", path=ngc.ZarrPath(path="./extra_image.zarr")
            ),
        )

        # Only the collection document changed: the embedded node needs no file
        # and the referenced image already exists.
        written = ngc.save(root, resolver)
        print("written:", written)

        # Reopen and show both new children, with their storage state.
        reopened = ngc.open(collection_url, resolver)
        for node in reopened.walk():
            print(f"  {node.id:<12} {node.state.value}")


if __name__ == "__main__":
    main()
