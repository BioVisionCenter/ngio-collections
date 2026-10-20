"""Build the revision's `collection.json` example: two images and a scene.

    experiment (collection, scene trait)
    ├── raw     -> ./raw     (multiscale, its own zarr.json; napari rendering trait on the entry)
    └── nuclei  -> ./nuclei  (multiscale, labels trait pointing at raw)

Under RFC-8 revision 1 a multiscale is never embedded in a collection: each
image is written as its own document first (`create` returns its declaring
entry, a stub carrying the same UUID) and the collection only links it with
`add_external`. The extension trait on the `raw` entry is declared in the
collection's `extension_manifest` automatically, because the extension was
registered with `register_extension`.

Run with: pixi run python examples/create_collection.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid

RENDERING = "https://napari.org/ngff/rendering"


def axes_czyx() -> list[ngc.Axis]:
    return [
        ngc.Axis(name="c", type="channel"),
        ngc.Axis(name="z", type="space", unit="micrometer"),
        ngc.Axis(name="y", type="space", unit="micrometer"),
        ngc.Axis(name="x", type="space", unit="micrometer"),
    ]


def build_multiscale(
    ms_id: str, cs_id: str, scale_ids: list[str], name: str
) -> ngc.Node:
    """A 4D image with two resolution levels mapping into one coordinate system."""
    system = ngc.CoordinateSystem(id=cs_id, name="physical", axes=axes_czyx())
    scales = [
        ngc.Scale(
            id=sid,
            path=ngc.ZarrPath(href=f"./s{level}"),
            coordinate_transformations=[
                ngc.ScaleTransformation(
                    scale=[1, 0.5, 0.1 * (level + 1), 0.1 * (level + 1)],
                    input=ngc.ReferenceObj(type="scale", ref=sid),
                    output=ngc.ReferenceObj(type="coordinate_system", ref=cs_id),
                )
            ],
        )
        for level, sid in enumerate(scale_ids)
    ]
    return ngc.new_multiscale(
        id=ms_id, name=name, coordinate_systems=[system], scales=scales
    )


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    ngc.register_extension(
        {
            "id": "https://napari.org/ngff/",
            "version": "1.0",
            "schemas": [
                {
                    "type": "json_schema",
                    "url": "https://napari.org/ngff/1.0/schema.json",
                }
            ],
            "homepage": "https://napari.org/ngff/",
        }
    )

    # 1. Each image is its own document.
    raw = ngc.create(
        str(base / "raw"),
        build_multiscale(uid(2), uid(0x20), [uid(0xC), uid(0xD)], "raw"),
        overwrite=True,
    )
    nuclei_node = build_multiscale(
        uid(3), uid(0x21), [uid(0xE), uid(0xF)], "nuclei"
    ).set_trait(
        ngc.LabelsTrait(
            source=[ngc.ReferenceObj(type="multiscale", ref=uid(2))],
            label_attributes=[
                ngc.LabelObj(label_value=1, rgba=[255, 0, 0, 255]),
                ngc.LabelObj(label_value=2, rgba=[0, 255, 0, 255]),
            ],
        )
    )
    nuclei = ngc.create(str(base / "nuclei"), nuclei_node, overwrite=True)

    # 2. The collection links them; traits on the entries override the images'.
    raw = raw.set_trait({"type": RENDERING, "contrast_limits": [0, 1500]})
    scene = ngc.SceneTrait(
        coordinate_systems=[
            ngc.CoordinateSystem(id=uid(5), axes=axes_czyx()[1:]),
        ],
        coordinate_transformations=[
            ngc.TranslationTransformation(
                translation=[0, 0, 100],
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
    print("resolved:", [(n.name, n.is_external, list(n.traits)) for n in view.walk()])
    print("validation:", view.validate(ngc.ALL_VALIDATORS))


if __name__ == "__main__":
    main()
