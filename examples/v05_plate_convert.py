"""Convert a remote OME-Zarr v0.5 plate (IDR) into local RFC-8 revision-1 documents.

Nothing is downloaded but metadata. For every image the converter writes a
*local* multiscale `zarr.json` whose `scales[*].path` are `format: "http"`
locators of the remote arrays (this package's documented deviation: the
revision makes only `relative` core), translating the v0.5 `multiscales` entry
(axes, datasets, scale transforms) into `coordinate_systems` + `scales`. The
plate and its wells become collections with the provisional HCS traits.

    data/v05_plate_convert/
    ├── zarr.json          plate collection (plate trait)
    └── A/1/zarr.json      well collection  (well trait) -> A/1/0/zarr.json, ...

Set NGC_OFFLINE=1 to skip (CI). Run with: pixi run python examples/v05_plate_convert.py
"""

import os
import sys
from pathlib import Path

import ngio_collections as ngc
from _ids import uid_for

PLATE_URL = "https://livingobjects.ebi.ac.uk/idr/zarr/v0.5/idr0010/76-45.ome.zarr/"
MAX_ROWS, MAX_COLS = 1, 2  # keep the demo small


def convert_multiscale(image_url: str, ome: dict, name: str) -> ngc.Node:
    """Translate one v0.5 `multiscales` entry into a revision-1 multiscale node."""
    ms = ome["multiscales"][0]
    cs_id = uid_for(image_url + "#physical")
    system = ngc.CoordinateSystem(
        id=cs_id,
        name="physical",
        axes=[
            ngc.Axis(name=a["name"], type=a.get("type"), unit=a.get("unit"))
            for a in ms["axes"]
        ],
    )
    scales = []
    for dataset in ms["datasets"]:
        sid = uid_for(image_url + "#" + dataset["path"])
        factors = next(
            t["scale"]
            for t in dataset["coordinateTransformations"]
            if t["type"] == "scale"
        )
        scales.append(
            ngc.Scale(
                id=sid,
                path=ngc.ZarrPath(format="http", href=image_url + dataset["path"]),
                coordinate_transformations=[
                    ngc.ScaleTransformation(
                        scale=factors,
                        input=ngc.ReferenceObj(type="scale", ref=sid),
                        output=ngc.ReferenceObj(type="coordinate_system", ref=cs_id),
                    )
                ],
            )
        )
    return ngc.new_multiscale(
        id=uid_for(image_url), name=name, coordinate_systems=[system], scales=scales
    )


def main() -> None:
    if os.environ.get("NGC_OFFLINE"):
        print("NGC_OFFLINE set: skipping the IDR conversion")
        return
    base = Path(__file__).parent / "data" / Path(__file__).stem
    http = ngc.HttpStore()
    plate_ome = ngc.open  # placeholder to keep flake-free; replaced below

    def read(url: str) -> dict:
        import asyncio

        return asyncio.run(http.get(url + "zarr.json"))["attributes"]["ome"]

    plate_ome = read(PLATE_URL)["plate"]
    rows = [r["name"] for r in plate_ome["rows"][:MAX_ROWS]]
    columns = [c["name"] for c in plate_ome["columns"][:MAX_COLS]]

    wells: list[ngc.Node] = []
    for well in plate_ome["wells"]:
        row, col = well["path"].split("/")
        if row not in rows or col not in columns:
            continue
        well_url = PLATE_URL + well["path"] + "/"
        images = read(well_url)["well"]["images"]
        entries = []
        for image in images:
            image_url = well_url + image["path"] + "/"
            node = convert_multiscale(
                image_url, read(image_url), name=f"{row}{col}_{image['path']}"
            )
            entries.append(
                ngc.create(str(base / row / col / image["path"]), node, overwrite=True)
            )
        well_node = ngc.new_collection(
            id=uid_for(well_url),
            name=f"{row}{col}",
            traits=[
                ngc.WellTrait(
                    row_index=rows.index(row), column_index=columns.index(col)
                )
            ],
        ).add_external(*entries)
        wells.append(ngc.create(str(base / row / col), well_node, overwrite=True))
        print(f"well {row}{col}: {len(entries)} image(s)")

    plate = ngc.new_collection(
        id=uid_for(PLATE_URL),
        name="idr0010 76-45",
        traits=[
            ngc.PlateTrait(
                rows=[ngc.RowObj(name=r) for r in rows],
                columns=[ngc.ColumnObj(name=c) for c in columns],
            )
        ],
    ).add_external(*wells)
    url = str(base / "zarr.json")
    ngc.create(url, plate, overwrite=True)

    view = ngc.open_resolved(url)
    first = next(n for n in view.walk() if n.type == "multiscale")
    assert isinstance(first, ngc.MultiscaleNode)
    print("wrote", url)
    print("first image scales:", [s.path.href for s in first.scales][:2], "...")
    print("validation:", view.validate(ngc.ALL_VALIDATORS))
    print(
        "strict paths:",
        len(view.validate((ngc.paths_are_core,))),
        "non-core path(s), as intended",
    )
    return None


if __name__ == "__main__":
    sys.exit(main())
