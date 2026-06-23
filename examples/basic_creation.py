"""Build a small collection in memory and write it to disk.

    root (collection)
    ├── image  (multiscale, 2 single scales)
    └── labels (collection)
        └── nuclei (multiscale label, 2 single scales)

Run with: pixi run python examples/basic_creation.py
"""

import tempfile
from pathlib import Path

import ngio_collections as ngc


def _single_scales(prefix: str) -> tuple[ngc.RefSinglescaleNode, ...]:
    # Single scales point at the on-disk zarr arrays ("0", "1"); they are
    # references, not embedded data, so the resolver leaves them as leaves.
    # Ids must be unique across the whole collection, so we prefix them.
    return (
        ngc.RefSinglescaleNode(id=f"{prefix}/0", path=ngc.ZarrPath(path="./0")),
        ngc.RefSinglescaleNode(id=f"{prefix}/1", path=ngc.ZarrPath(path="./1")),
    )


def build_collection() -> ngc.CollectionNode:
    """The in-memory tree. Frozen and detached until a Resolver writes it."""
    return ngc.CollectionNode(
        id="root",
        nodes=(
            ngc.MultiscaleNode(id="image", name="image", nodes=_single_scales("image")),
            ngc.CollectionNode(
                id="labels",
                nodes=(
                    # A label is just a multiscale; there is no dedicated type.
                    ngc.MultiscaleNode(
                        id="nuclei", name="nuclei", nodes=_single_scales("nuclei")
                    ),
                ),
            ),
        ),
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        url = str(Path(tmp) / "collection.json")
        ngc.create(url, build_collection())

        print(f"wrote {url}\n")
        print(Path(url).read_text())


if __name__ == "__main__":
    main()
