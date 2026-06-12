"""An HCS plate as a fully externalized tree, one document per node.

Mirrors the on-disk OME-Zarr plate layout: the plate at the top level, each
well its own document in a ``{row}/{col}`` subdirectory, and each image in
``{row}/{col}/{image}``. Every parent references its children by path stub:

    data/hcs_nested/
    ├── collection.json        <- plate, well stubs -> ./A/1/well.json …
    ├── A/1/well.json          <- well A/1, image stubs -> ./0.zarr
    ├── A/1/0.zarr/zarr.json   <- multiscale image (field 0)
    ├── A/2/well.json
    ├── A/2/0.zarr/zarr.json
    └── …

Built bottom-up with the sync API: each ``write_*`` emits one document and
returns a reference stub, which the parent embeds; ``write_collection``
relativizes the embedded stub paths against the parent's URL, so the well
document references ``./0.zarr`` and the plate references ``./A/1/well.json``.

Run with:

    pixi run -e dev python examples/07_hcs_plate_nested.py
"""

import shutil
from pathlib import Path

import ngio_collections as ngc
from ngio_collections.models import ColumnObj, RowObj

ROOT = Path(__file__).parent / "data" / "hcs_nested"

ROWS = ["A", "B"]
COLUMNS = ["1", "2"]


def build_image(row: str, col: str) -> ngc.MultiscaleNode:
    """A one-level multiscale for field 0 of well ``{row}/{col}``.

    Node ids stay unique across the plate so the inlined-on-read tree (every
    document collapsed into one) has no id collisions.
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


def write_well(row: str, col: str) -> ngc.CollectionRef:
    """Write image then well, each its own document; return the well stub."""
    image_ref = ngc.write_multiscale(
        build_image(row, col), str(ROOT / row / col / "0.zarr")
    )
    well = ngc.WellAttribute(
        row=ngc.ReferenceObj(id=row), column=ngc.ReferenceObj(id=col)
    )
    well_node = ngc.CollectionNode(
        id=f"well_{row}{col}",
        name=f"{row}{col}",
        nodes=[image_ref],
        attributes={
            well.key: well.model_dump(mode="json", by_alias=True, exclude_none=True)
        },
    )
    # Writing the well relativizes the image stub against it: ./0.zarr
    return ngc.write_collection(well_node, str(ROOT / row / col / "well.json"))


def show(node: ngc.BaseNode, depth: int = 0) -> None:
    stub = f" -> {node.path.path}" if node.path is not None else ""
    print(f"{'  ' * depth}[{node.type}] {node.id} attrs={list(node.attributes)}{stub}")
    for child in getattr(node, "nodes", None) or []:
        if isinstance(child, ngc.BaseNode):
            show(child, depth + 1)


def main() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)

    # Each well is its own document; the plate references them by path.
    well_refs = [write_well(row, col) for row in ROWS for col in COLUMNS]
    plate = ngc.PlateAttribute(
        rows=[RowObj(id=row) for row in ROWS],
        columns=[ColumnObj(id=col) for col in COLUMNS],
    )
    plate_node = ngc.CollectionNode(
        id="plate",
        name="My Plate",
        nodes=well_refs,
        attributes={
            plate.key: plate.model_dump(mode="json", by_alias=True, exclude_none=True)
        },
    )
    ngc.write_collection(plate_node, str(ROOT / "collection.json"))

    print("written files (one document per node):")
    for file in sorted(ROOT.rglob("*.json")):
        print(f"  {file.relative_to(ROOT)}")

    # The lazy view: open() reads only the plate; wells stay stubs.
    print("\nplate document alone (wells are stubs):")
    show(ngc.open_collection(str(ROOT / "collection.json"), max_depth=0))

    # The hydrated view: open_collection inlines wells and their images.
    root = ngc.open_collection(str(ROOT / "collection.json"))
    print("\nplate tree (fully inlined):")
    show(root)

    well_a1 = root.find("well_A1")
    assert well_a1 is not None
    location = well_a1.attrs[ngc.WellAttribute]
    print(
        f"\nwell_A1 at row={location.row.id!r} column={location.column.id!r}, "
        f"images={[n.id for n in well_a1.walk() if n.type == 'multiscale']}"
    )


if __name__ == "__main__":
    main()
