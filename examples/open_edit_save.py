"""Open an on-disk collection, edit a node, and save the change back.

Single-document round-trip: `open()` reads one document into an editable tree; a
positioned edit returns a new tree (the source is untouched); `save()` writes it
back to the same file. Re-opening confirms the edit persisted. Nodes are located
by their UUID `id`.

Run with: pixi run python examples/open_edit_save.py
"""

from pathlib import Path

import ngio_collections as ngc

ROOT = "0192f3a0-e000-7000-8000-000000000021"
IMAGE = "0192f3a0-e000-7000-8000-000000000022"
NUCLEI = "0192f3a0-e000-7000-8000-000000000023"


def _setup(url: str) -> None:
    """Write a small starting collection to disk (so the example is standalone)."""
    root = (
        ngc.new_node("collection", id=ROOT, name="experiment")
        .add(ngc.new_node("multiscale", id=IMAGE, name="image", attributes={"role": "raw"}))
        .add(
            ngc.new_node(
                "multiscale", id=NUCLEI, name="nuclei", attributes={"role": "label"}
            )
        )
    )
    ngc.create(url, root, overwrite=True)


def main() -> None:
    url = str(Path(__file__).parent / "data" / Path(__file__).stem / "collection.json")
    _setup(url)

    # Open the document as an editable tree (it is now document-backed).
    root = ngc.open(url)
    print("opened :", [n.name for n in root.walk()], "->", root.document_url)

    # Positioned edits return the new tree root, so they chain through `find`.
    edited = root.find(IMAGE).set_attrs({"role": "raw", "channel": "DAPI"})
    edited = edited.find(NUCLEI).rename("Nuclei segmentation")

    # Write the edited tree back into its own document.
    ngc.save(edited)

    # Re-open to confirm the edits are on disk.
    reopened = ngc.open(url)
    print("image  :", dict(reopened.find(IMAGE).attributes))
    print("nuclei :", reopened.find(NUCLEI).name)


if __name__ == "__main__":
    main()
