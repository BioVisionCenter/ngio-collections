"""An HCS plate as a SINGLE collection document, images externalized.

One ``collection.json`` holds the whole plate->well hierarchy inline: the
plate is a collection carrying the ``plate`` attribute, each well a child
collection carrying the ``well`` attribute. Only the multiscale images are
externalized, into per-field subdirectories the wells reference by path:

    data/hcs_single/
    ├── collection.json        <- plate + wells inline, image stubs
    ├── A/1/0.zarr/zarr.json   <- multiscale image (field 0 of well A/1)
    ├── A/2/0.zarr/zarr.json
    ├── B/1/0.zarr/zarr.json
    └── B/2/0.zarr/zarr.json

Built bottom-up with the sync API: ``write_multiscale`` emits each image and
hands back a reference stub, the wells embed those stubs, and
``write_collection`` emits the one plate document — relativizing every nested
image path against it (``./A/1/0.zarr`` …).

Run with:

    pixi run -e dev python examples/06_hcs_plate_single_collection.py
"""

import shutil
from pathlib import Path

import ngio_collections as ngc
from ngio_collections.models import ColumnObj, RowObj

ROOT = Path(__file__).parent / "data" / "hcs_single"

ROWS = ["A", "B"]
COLUMNS = ["1", "2"]


def build_image(row: str, col: str) -> ngc.MultiscaleNode:
    """A one-level multiscale for field 0 of well ``{row}/{col}``.

    Node ids are unique per well so the whole plate stays collision-free once
    every image is inlined into one tree on read.
    """
    systems = ngc.CoordinateSystemsAttribute(
        [
            ngc.CoordinateSystem(
                id="physical",
                axes=[{"name": "y", "type": "space"}, {"name": "x", "type": "space"}],
            )
        ]
    )
    return ngc.MultiscaleNode(
        id=f"img_{row}{col}",
        name="0",
        nodes=[
            ngc.SinglescaleNode(
                id=f"s0_{row}{col}",
                name="s0",
                path=ngc.ZarrPath(path="./s0"),
                attributes={"coordinateTransformations": []},
            )
        ],
        attributes={systems.key: systems.model_dump(mode="json", by_alias=True)},
    )


def build_well(row: str, col: str) -> ngc.CollectionNode:
    """A well collection whose single child is the externalized image stub."""
    image_ref = ngc.write_multiscale(
        build_image(row, col), str(ROOT / row / col / "0.zarr")
    )
    well = ngc.WellAttribute(
        row=ngc.ReferenceObj(id=row), column=ngc.ReferenceObj(id=col)
    )
    return ngc.CollectionNode(
        id=f"well_{row}{col}",
        name=f"{row}{col}",
        nodes=[image_ref],
        attributes={
            well.key: well.model_dump(mode="json", by_alias=True, exclude_none=True)
        },
    )


def show(node: ngc.BaseNode, depth: int = 0) -> None:
    stub = f" -> {node.path.path}" if node.path is not None else ""
    print(f"{'  ' * depth}[{node.type}] {node.id} attrs={list(node.attributes)}{stub}")
    for child in getattr(node, "nodes", None) or []:
        if isinstance(child, ngc.BaseNode):
            show(child, depth + 1)


def main() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)

    # Wells (with their image stubs) stay inline; only images are externalized.
    wells = [build_well(row, col) for row in ROWS for col in COLUMNS]
    plate = ngc.PlateAttribute(
        rows=[RowObj(id=row) for row in ROWS],
        columns=[ColumnObj(id=col) for col in COLUMNS],
    )
    plate_node = ngc.CollectionNode(
        id="plate",
        name="My Plate",
        nodes=wells,
        attributes={
            plate.key: plate.model_dump(mode="json", by_alias=True, exclude_none=True)
        },
    )
    ngc.write_collection(plate_node, str(ROOT / "collection.json"))

    print("written files:")
    for file in sorted(ROOT.rglob("*.json")):
        print(f"  {file.relative_to(ROOT)}")

    # Read back: open_collection inlines the image documents into the plate.
    root = ngc.open_collection(str(ROOT / "collection.json"))
    print("\nplate tree (fully inlined):")
    show(root)

    # Navigate the flattened plate with walk() / find().
    plate_attr = root.attrs[ngc.PlateAttribute]
    print(
        f"\nplate: {len(plate_attr.rows)} rows x {len(plate_attr.columns)} columns, "
        f"{sum(n.type == 'collection' for n in root.walk()) - 1} wells"
    )
    well_b2 = root.find("well_B2")
    assert well_b2 is not None
    location = well_b2.attrs[ngc.WellAttribute]
    print(f"well_B2 at row={location.row.id!r} column={location.column.id!r}")


if __name__ == "__main__":
    main()
