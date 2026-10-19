"""We use an existing v0.5 OME-Zarr plate to load OME-Zarr metadata
and use it to build an RFC8 plate.
We write a multi-document RFC8 collection, with each well as a separate document
and a separate RFC8 collection.json for the plate itself.

Run with: pixi run python examples/v05_plate_to_multi_doc.py
"""

from pathlib import Path
import requests

import ngio_collections as ngc

MAX_ROWS = 2
MAX_COLS = 3

plate_url = "https://livingobjects.ebi.ac.uk/idr/zarr/v0.5/idr0010/76-45.ome.zarr/"


def single_scales(prefix: str, paths: list[str]) -> tuple[ngc.Node, ...]:
    nodes = []
    for i, ss_path in enumerate(paths):
        nodes.append(
            ngc.new_node(
                "singlescale",
                id=f"{prefix}_scale{i}",
                name=f"{prefix}_scale{i}",
                ref=ngc.Reference(path=ngc.ZarrPath(path=ss_path)),
            )
        )
    return tuple(nodes)


def build_multiscale(
    prefix: str,
    paths: list[str],
    scales: list[list[float]],
    axes: list[ngc.Axis],
    extra_attr: ngc.AnyAttribute | None = None,
) -> ngc.Node:
    node = ngc.new_node(
        "multiscale", id=prefix, name=prefix, children=single_scales(prefix, paths)
    )

    # The multiscale defines the coordinate system its single scales map into.
    node = node.set_attr(
        ngc.CoordinateSystemsAttribute(
            [ngc.CoordinateSystem(id=f"{prefix}_space", axes=axes)]
        )
    )
    if extra_attr is not None:
        node = node.set_attr(extra_attr)

    # Each single scale maps its array onto the shared coordinate system.
    for level, factor_list in enumerate(scales):
        node = node.find(f"{prefix}_scale{level}").set_attr(
            ngc.CoordinateTransformationsAttribute(
                [
                    ngc.ScaleTransformation(
                        input=ngc.ReferenceObj(id=f"{prefix}_scale{level}"),
                        output=ngc.ReferenceObj(id=f"{prefix}_space"),
                        scale=factor_list,
                    )
                ]
            )
        )
    return node


def build_collection(base_path: Path) -> ngc.Node:
    """The in-memory tree, detached until `create` writes it."""

    # load json from image_url
    json_rsp = requests.get(plate_url + "zarr.json").json()
    plate_json = json_rsp["attributes"]["ome"]["plate"]
    cols_json = plate_json["columns"][:MAX_COLS]
    rows_json = plate_json["rows"][:MAX_ROWS]
    row_names = [row["name"] for row in rows_json]
    col_names = [col["name"] for col in cols_json]

    plate_attrs = {"plate": {"columns": cols_json, "rows": rows_json}}
    plate = ngc.new_node("collection", id="plate", name="plate", attributes=plate_attrs)

    # Only process the first 3 wells for demonstration purposes.
    for well_json in plate_json["wells"]:
        well_path = well_json["path"]
        rowname, colname = well_path.split("/")[-2:]
        if rowname not in row_names:
            continue
        if colname not in col_names:
            continue

        write_path = str(base_path / "wells" / (well_path + ".zarr"))

        well_id = f"well{well_path.replace('/', '')}"
        well_collection_node = ngc.new_node("collection", id=well_id, name=well_id)

        well_url = plate_url + well_path + "/"
        well_json = requests.get(well_url + "zarr.json").json()

        img_paths = [
            img["path"] for img in well_json["attributes"]["ome"]["well"]["images"]
        ]
        for img_path in img_paths:
            img_url = well_url + img_path
            ms_json = requests.get(img_url + "/zarr.json").json()["attributes"]["ome"][
                "multiscales"
            ][0]
            axes = [
                ngc.Axis(name=ax["name"], type=ax["type"], unit=ax.get("unit"))
                for ax in ms_json["axes"]
            ]
            # paths are http URLs to the datasets within the multiscale image
            ds_paths = [well_url + ds["path"] for ds in ms_json["datasets"]]
            scales = [
                ds["coordinateTransformations"][0]["scale"]
                for ds in ms_json["datasets"]
            ]

            multiscale_node = build_multiscale(
                f"A1_field{img_path}", ds_paths, scales, axes
            )
            well_collection_node = well_collection_node.add(multiscale_node)

        print("write_path", write_path)
        rf_well = ngc.create(write_path, well_collection_node, overwrite=True)
        # well_ref = ngc.open(write_path).ref()  # ReferenceObj(id="image", path=image.zarr)

        # plate = plate.add(well_collection_node)
        plate = plate.add_ref(rf_well)

    return plate


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    plate = build_collection(base_path)

    url = str(base_path / "collection.json")
    ngc.create(url, plate, overwrite=True)

    print(f"wrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()

# def main() -> None:
#     base_path = Path(__file__).parent / "data" / Path(__file__).stem
#     url = str(base_path / "collection.json")
#     image_url = str(base_path / "image.zarr")
#     labels_url = str(base_path / "labels.zarr")

#     # Write the image to its own zarr; open it back for a portable reference.
#     rf_image = ngc.create(image_url, build_multiscale("image"), overwrite=True)
#     image_ref = ngc.open(image_url).ref()  # ReferenceObj(id="image", path=image.zarr)

#     # The labels multiscale records, in its `labels` attribute, the image it
#     # segments — via that portable reference.
#     labels = build_multiscale(
#         "labels", extra_attr=ngc.LabelsAttribute(source=[image_ref])
#     )
#     rf_labels = ngc.create(labels_url, labels, overwrite=True)
#     print("image ref :", image_ref.model_dump())

#     # Build the parent in memory and attach both references (still detached:
#     # paths are relativized when the document is written).
#     root = ngc.new_node("collection", id="root", name="root").add_ref(
#         rf_image, rf_labels
#     )
#     ngc.create(url, root, overwrite=True)

#     print(f"\nwrote {url}\n")
#     print(Path(url).read_text())
