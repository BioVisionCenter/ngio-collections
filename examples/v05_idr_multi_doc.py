"""We use an existing v0.5 OME-Zarr plate to load OME-Zarr metadata
and use it to build an RFC8 plate.
We write a multi-document RFC8 collection, with each well as a separate document
and a separate RFC8 collection.json for the plate itself.

Run with: pixi run python examples/v05_plate_to_multi_doc.py
"""

from pathlib import Path
import requests
import csv

import ngio_collections as ngc

idr_url = "https://raw.githubusercontent.com/IDR/ome-ngff-samples/refs/heads/main/_data/table.csv"


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


def write_image(zarr_url: str, base_path: Path, ome_attrs: dict):

    img_name = str(Path(zarr_url).stem).replace(".zarr", "")
    img_name = img_name.replace(" ", "_").replace("(", "").replace(")", "")
    print("image name", img_name)
    ms_json = ome_attrs["multiscales"][0]

    axes = [
        ngc.Axis(name=ax["name"], type=ax["type"], unit=ax.get("unit"))
        for ax in ms_json["axes"]
    ]
    # paths are http URLs to the datasets within the multiscale image
    ds_paths = [str(Path(zarr_url) / ds["path"]) for ds in ms_json["datasets"]]
    print("dataset paths", ds_paths)
    scales = [ds["coordinateTransformations"][0]["scale"] for ds in ms_json["datasets"]]

    ms_id = f"{img_name}"
    multiscale_node = build_multiscale(ms_id, ds_paths, scales, axes)
    print("base path", base_path, "image name", img_name)
    write_path = f"{base_path}/{img_name}.zarr"

    print("image write_path", write_path)
    return ngc.create(write_path, multiscale_node, overwrite=True)


def build_collection(base_path: Path) -> ngc.Node:
    """The in-memory tree, detached until `create` writes it."""

    # load csv from idr_url and read rows to list
    csv_rsp = requests.get(idr_url).text
    # use csv reader
    csv_rows = list(csv.reader(csv_rsp.splitlines()))

    version_col = csv_rows[0].index("OME-NGFF version")
    filepath_col = csv_rows[0].index("File Path")
    wells_col = csv_rows[0].index("Wells")

    v05_image_rows = [
        row
        for row in csv_rows[1:]
        if row[version_col] == "0.5" and row[wells_col] == ""
    ]
    idr_collection_node = ngc.new_node("collection", id="idr_images", name="idr_images")

    # for each row, we load the zarr json...
    for index, row in enumerate(v05_image_rows):
        zarr_url = row[filepath_col]
        zarr_json = requests.get(zarr_url + "/zarr.json").json()
        ome_attrs = zarr_json["attributes"]["ome"]

        if "bioformats2raw.layout" in ome_attrs:
            img_name = str(Path(zarr_url).stem).replace(".zarr", "")
            bf_node = ngc.new_node(
                "collection", id=f"{index}_bf2raw", name=f"{index}_bf2raw"
            )
            series = 0
            while True:
                try:
                    print("loading", f"{zarr_url}/{series}/zarr.json")
                    series_json = requests.get(f"{zarr_url}/{series}/zarr.json").json()
                    ome_attrs = series_json["attributes"]["ome"]
                    print("write image", f"{img_name}/{series}")
                    rf_image = write_image(
                        f"{zarr_url}/{series}", f"{base_path}/{img_name}", ome_attrs
                    )
                    bf_node = bf_node.add_ref(rf_image)
                except Exception as e:
                    print(f"Error writing image {img_name} series {series}: {e}")
                    break
                series += 1

            idr_collection_node = idr_collection_node.add(bf_node)

        else:
            rf_image = write_image(zarr_url, base_path, ome_attrs)
            idr_collection_node = idr_collection_node.add_ref(rf_image)

    return idr_collection_node


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    idr_collection_node = build_collection(base_path)

    url = str(base_path / "collection.json")
    ngc.create(url, idr_collection_node, overwrite=True)

    print(f"wrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()
