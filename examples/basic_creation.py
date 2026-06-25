"""Build a small collection in memory and write it to disk.

    root (collection)
    ├── image  (multiscale, 2 single scales)
    └── labels (collection)
        └── nuclei (multiscale label, 2 single scales)

Each multiscale carries a `coordinateSystems` attribute and each single scale a
`coordinateTransformations` attribute, written through the typed RFC-8 models
(`CoordinateSystemsAttribute`, `ScaleTransformation`, ...) via `set_attr` rather
than raw dicts. The `nuclei` multiscale also carries a typed `labels` attribute.

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


def build_multiscale(
    prefix: str, extra_attr: ngc.AnyAttribute | None = None
) -> ngc.MultiscaleNode:
    # The multiscale defines the coordinate system its single scales map into.
    coordinate_systems = ngc.CoordinateSystemsAttribute(
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
    node = ngc.MultiscaleNode(
        id=prefix, name=prefix, nodes=single_scales(prefix)
    ).set_attr(id=prefix, value=coordinate_systems)

    # Attributes are not node fields (nodes are strict); attach any extra typed
    # attribute through `set_attr`, keyed by the multiscale id.
    if extra_attr is not None:
        node = node.set_attr(id=prefix, value=extra_attr)

    # Each single scale maps its array onto the shared coordinate system with a
    # scale transform (level 1 is downsampled 2x).
    for level, factor in enumerate((1.0, 2.0)):
        transforms = ngc.CoordinateTransformationsAttribute(
            [
                ngc.ScaleTransformation(
                    input=ngc.ReferenceObj(id=f"{prefix}_{level}"),
                    output=ngc.ReferenceObj(id=f"{prefix}_space"),
                    scale=[factor, factor],
                )
            ]
        )
        node = node.set_attr(id=f"{prefix}_{level}", value=transforms)
    return node


def build_collection() -> ngc.CollectionNode:
    """The in-memory tree. Frozen and detached until a Resolver writes it."""
    # The label multiscale carries a typed `labels` attribute: a value->color
    # map plus a reference back to the image it segments.
    nuclei = build_multiscale("nuclei").set_attr(
        id="nuclei",
        value=ngc.LabelsAttribute(
            label_attributes=[ngc.LabelObj(label_value=1, color=[255, 0, 0, 255])],
            source=[ngc.ReferenceObj(id="image")],
        ),
    )
    return ngc.CollectionNode(
        id="root",
        nodes=(
            build_multiscale("image"),
            ngc.CollectionNode(id="labels", nodes=(nuclei,)),
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
