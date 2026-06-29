"""Build a small collection in memory and write it to disk.

    root (collection)
    ├── image  (multiscale, 2 single scales)
    └── labels (collection)
        └── nuclei (multiscale label, 2 single scales)

Trees are built handle-rooted and fluent: `new_node(...)` seeds a detached root and
`add(child)` grafts a subtree. Each multiscale carries a `coordinateSystems`
attribute and each single scale a `coordinateTransformations` attribute, written
through the typed RFC-8 models via `set_attr`. Edits return the new tree root, so
`node.find(id).set_attr(...)` round-trips into `create`.

Run with: pixi run python examples/basic_creation.py
"""

from pathlib import Path

import ngio_collections as ngc


def single_scales(prefix: str) -> tuple[ngc.Node, ...]:
    # Single scales reference on-disk zarr arrays ("0", "1"): reference nodes, not
    # embedded data. Ids must be unique across the collection, so we prefix them.
    return (
        ngc.new_node(
            "singlescale",
            id=f"{prefix}_0",
            ref=ngc.Reference(path=ngc.ZarrPath(path="./0")),
        ),
        ngc.new_node(
            "singlescale",
            id=f"{prefix}_1",
            ref=ngc.Reference(path=ngc.ZarrPath(path="./1")),
        ),
    )


def build_multiscale(
    prefix: str, extra_attr: ngc.AnyAttribute | None = None
) -> ngc.Node:
    node = ngc.new_node("multiscale", id=prefix, name=prefix)
    for scale in single_scales(prefix):
        node = node.add(scale)  # tree-out: node is the multiscale root again

    # The multiscale defines the coordinate system its single scales map into.
    node = node.set_attr(
        ngc.CoordinateSystemsAttribute(
            [
                ngc.CoordinateSystem(
                    id=f"{prefix}_space",
                    axes=[
                        ngc.Axis(name="y", type="space", unit="micrometer"),
                        ngc.Axis(name="x", type="space", unit="micrometer"),
                    ],
                )
            ]
        )
    )
    if extra_attr is not None:
        node = node.set_attr(extra_attr)

    # Each single scale maps its array onto the shared coordinate system.
    for level, factor in enumerate((1.0, 2.0)):
        node = node.find(f"{prefix}_{level}").set_attr(
            ngc.CoordinateTransformationsAttribute(
                [
                    ngc.ScaleTransformation(
                        input=ngc.ReferenceObj(id=f"{prefix}_{level}"),
                        output=ngc.ReferenceObj(id=f"{prefix}_space"),
                        scale=[factor, factor],
                    )
                ]
            )
        )
    return node


def build_collection() -> ngc.Node:
    """The in-memory tree, detached until `create` writes it."""
    nuclei = build_multiscale("nuclei").set_attr(
        ngc.LabelsAttribute(
            label_attributes=[ngc.LabelObj(label_value=1, color=[255, 0, 0, 255])],
            source=[ngc.ReferenceObj(id="image")],
        )
    )
    labels = ngc.new_node("collection", id="labels").add(nuclei)
    return (
        ngc.new_node("collection", id="root").add(build_multiscale("image")).add(labels)
    )


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")
    ngc.create(url, build_collection(), overwrite=True)

    print(f"wrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()
