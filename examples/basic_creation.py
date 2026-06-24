"""Build a small collection in memory and write it to disk.

    root (collection)
    ├── image  (multiscale, 2 single scales)
    └── labels (collection)
        └── nuclei (multiscale label, 2 single scales)

Run with: pixi run python examples/basic_creation.py
"""

from pathlib import Path

import ngio_collections as ngc


def single_scales(prefix: str) -> tuple[ngc.RefSinglescaleNode, ...]:
    # Single scales point at the on-disk zarr arrays ("0", "1"); they are
    # references, not embedded data, so the resolver leaves them as leaves.
    # Ids must be unique across the whole collection (and match the id pattern,
    # which is alphanumeric + -_. ), so we prefix them.
    return (
        ngc.RefSinglescaleNode(id=f"{prefix}_0", path=ngc.ZarrPath(path="./0")),
        ngc.RefSinglescaleNode(id=f"{prefix}_1", path=ngc.ZarrPath(path="./1")),
    )


def build_multiscale(prefix: str, attributes: dict | None = None) -> ngc.MultiscaleNode:
    attributes = attributes or {}
    return ngc.MultiscaleNode(
        id=prefix, name=prefix, nodes=single_scales(prefix), attributes=attributes
    )


def build_collection() -> ngc.CollectionNode:
    """The in-memory tree. Frozen and detached until a Resolver writes it."""
    return ngc.CollectionNode(
        id="root",
        nodes=(
            build_multiscale("image"),
            ngc.CollectionNode(
                id="labels",
                nodes=(build_multiscale("nuclei"),),
            ),
        ),
    )


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")
    ngc.create(url, build_collection(), overwrite=True)

    print(f"wrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()
