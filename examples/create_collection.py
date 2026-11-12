"""Build the revision's `collection.json` example: two images and a scene.

    experiment (collection, scene trait)
    ├── raw     -> ./raw     (multiscale, its own zarr.json)
    └── nuclei  -> ./nuclei  (multiscale; labels trait on its entry, as in the spec)

Each image is written as its own document first (`create` returns its
declaring entry, a stub carrying the same id) and the collection links it with
`add_external`; an image can also be inlined with `add` (see
`nested_collections.py`). This is the one example that assembles a multiscale by hand;
the others import a ready-made image from `_images.py`.

The multiscale layout follows RFC-8 revision 2: a physical coordinate system,
one `array` object per level in `data` (each locating its array by `path`; the
lower levels state how they were downsampled from the full-resolution array)
and a node-level `scale` transformation into the physical system. Array objects
have no id, so the transformation's `input` references the multiscale itself,
which stands for the array space of its full-resolution array.

Run with: pixi run --environment dev python examples/create_collection.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid


def axes_czyx() -> list[ngc.Axis]:
    return [
        ngc.Axis(name="c", type="channel"),
        ngc.Axis(name="z", type="space", unit="micrometer"),
        ngc.Axis(name="y", type="space", unit="micrometer"),
        ngc.Axis(name="x", type="space", unit="micrometer"),
    ]


def build_multiscale(ms_id: str, cs_id: str, name: str, levels: int = 2) -> ngc.Node:
    """A 4D image with two resolution levels: pixel size 0.1 µm, level 1 at half res."""
    physical = ngc.CoordinateSystem(id=cs_id, name="physical", axes=axes_czyx())
    to_physical = ngc.ScaleTransformation(
        scale=[1, 0.5, 0.1, 0.1],  # full-resolution voxel size, the spec's values
        input=ngc.ReferenceObj(type="multiscale", ref=ms_id),
        output=ngc.ReferenceObj(type="coordinate_system", ref=cs_id),
    )
    arrays = [
        ngc.MultiscaleArray(
            path=ngc.ZarrPath(href=f"./s{level}"),
            # the full-resolution array (level 0) carries no downsampling
            downsamplingTransformations=(
                [ngc.ScaleDownsampling(scale=[1, 1, 2**level, 2**level])]
                if level
                else None
            ),
        )
        for level in range(levels)
    ]
    return ngc.new_multiscale(
        id=ms_id,
        name=name,
        coordinate_systems=[physical],
        coordinate_transformations=[to_physical],
        arrays=arrays,
    )


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem

    # 1. Each image is its own document.
    raw = ngc.create(
        str(base / "raw"),
        build_multiscale(uid(2), uid(0x20), "raw"),
        overwrite=True,
    )
    nuclei = ngc.create(
        str(base / "nuclei"),
        build_multiscale(uid(3), uid(0x21), "nuclei"),
        overwrite=True,
    )
    # The labels trait sits on nuclei's ENTRY in the collection, as in the spec's
    # collection.json; the image document itself carries no traits.
    nuclei = nuclei.set_trait(
        ngc.LabelsTrait(
            source=[ngc.ReferenceObj(type="multiscale", ref=uid(2))],
            label_attributes=[
                ngc.LabelObj(label_value=1, rgba=[255, 0, 0, 255]),
                ngc.LabelObj(label_value=2, rgba=[0, 255, 0, 255]),
            ],
        )
    )

    # 2. The collection links them and places both in one scene.
    scene = ngc.SceneTrait(
        coordinate_systems=[
            ngc.CoordinateSystem(id=uid(5), axes=axes_czyx()[1:]),  # spatial: z, y, x
        ],
        coordinate_transformations=[
            ngc.TranslationTransformation(
                translation=[0, 0, 100],  # the spec's values; both images alike
                input=ngc.ReferenceObj(
                    type="coordinate_system", ref=cs, path=ngc.ZarrPath(href=href)
                ),
                output=ngc.ReferenceObj(type="coordinate_system", ref=uid(5)),
            )
            for cs, href in ((uid(0x20), "./raw"), (uid(0x21), "./nuclei"))
        ],
    )
    root = ngc.new_collection(
        id=uid(1), name="hela-nuclei-experiment", traits=[scene]
    ).add_external(raw, nuclei)
    url = str(base / "zarr.json")
    ngc.create(url, root, overwrite=True)

    print(f"wrote {url}\n")
    print(Path(url).read_text())
    view = ngc.open_resolved(url)
    print("resolved:", [(n.name, list(n.traits)) for n in view.walk()])


if __name__ == "__main__":
    main()
