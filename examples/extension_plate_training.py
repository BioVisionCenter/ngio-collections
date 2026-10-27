"""Several extension points at once, on an HCS plate.

    plate-001 (collection; plate trait + training-dataset trait)
    └── A1 (collection; well trait)
        ├── fov0        -> ./A/1/0               (multiscale)
        ├── nuclei      -> ./A/1/nuclei          (multiscale, labels -> fov0)
        └── regionprops -> ./A/1/regionprops.csv (Fractal table node)

Built-in provisional traits (plate, well, labels) mix with the extensions from
`_extensions.py`: the *training dataset* trait on the plate pairs the well's
image and labels by reference, and the Fractal *table* is a node of an
extension type whose `path` has the custom type `CSV`. The library resolves that
path like any other (`format` + `href`) but never opens the CSV as a node
document: the node stays a leaf in a resolved view, and that is not a finding.
`register_node_type` gives such nodes a typed handle (`TableNode`).

Run with: pixi run python examples/extension_plate_training.py
"""

from pathlib import Path

import ngio_collections as ngc
from _extensions import (
    CSV,
    DATASET,
    TABLE,
    TableNode,
    register_examples,
    register_table_handle,
)
from _ids import uid
from _images import image


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base / "zarr.json")
    register_examples()
    register_table_handle()

    well_dir = base / "A" / "1"
    fov0 = ngc.create(str(well_dir / "0"), image(9, "fov0", levels=2), overwrite=True)
    nuclei = ngc.create(
        str(well_dir / "nuclei"),
        image(0xA, "nuclei", levels=2).set_trait(
            ngc.LabelsTrait(source=[ngc.ReferenceObj(type="multiscale", ref=uid(9))])
        ),
        overwrite=True,
    )
    well_dir.mkdir(parents=True, exist_ok=True)
    (well_dir / "regionprops.csv").write_text(
        "label,area,mean_intensity\n1,120,0.82\n2,98,0.64\n"
    )
    table = ngc.new_node(
        TABLE,
        id=uid(0xC),
        name="regionprops",
        path=ngc.DocPath(type=CSV, format="relative", href="./A/1/regionprops.csv"),
        fields={"columns": ["label", "area", "mean_intensity"]},
    )
    well = ngc.new_collection(
        id=uid(7), name="A1", traits=[ngc.WellTrait(row_index=0, column_index=0)]
    ).add_external(fov0, nuclei, table)

    plate = ngc.PlateTrait(
        rows=[ngc.RowObj(name="A")], columns=[ngc.ColumnObj(name="1")]
    )
    dataset = {
        "type": DATASET,
        "task": "segmentation",
        "samples": [
            {
                "image": {"type": "multiscale", "ref": uid(9)},
                "labels": {"type": "multiscale", "ref": uid(0xA)},
                "split": "train",
            }
        ],
    }
    root = ngc.new_collection(id=uid(6), name="plate-001", traits=[plate, dataset]).add(
        well
    )
    ngc.create(url, root, overwrite=True)

    opened = ngc.open(url)
    print(
        "manifest  :", [e["id"].rsplit("/", 2)[-2] for e in opened.extension_manifest]
    )
    print("dataset   :", opened.traits[DATASET]["samples"][0]["split"])
    table = opened.find(uid(0xC))
    assert isinstance(table, TableNode)
    print("table     :", table.columns, Path(table.csv_url()).relative_to(base))

    # A data path is never fetched: the table stays external in a resolved view.
    view = ngc.open_resolved(url)
    node = view.find(uid(0xC))
    print(
        "resolved  : external =", node.is_external, "document =", node.path.is_document
    )
    print("validation:", view.validate(ngc.ALL_VALIDATORS))
    print(
        "strict    :",
        [(e.validator, e.node_uuid[-4:]) for e in view.validate((ngc.paths_are_core,))],
    )


if __name__ == "__main__":
    main()
