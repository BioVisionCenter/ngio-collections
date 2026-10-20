"""Build the revision's `plate.json` example with the provisional HCS traits.

    plate-001 (collection, plate trait: rows A/B, columns 1/2, acquisition t0)
    └── A1 (collection, well + scene traits)
        ├── fov0 -> ./A/1/0 (multiscale, acquisition trait)
        └── fov1 -> ./A/1/1

HCS is deferred to a sub-RFC; `PlateTrait` / `WellTrait` / `AcquisitionTrait`
follow the revision's example and are marked provisional. Note the well is an
*embedded* collection (nested collections may be inlined; only multiscales may
not), and that `acquisition` on an image is a typed reference to the
acquisition *declared* in the plate trait.

Run with: pixi run python examples/hcs_plate.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid


def build_fov(ms_id: str, cs_id: str, scale_ids: list[str], name: str) -> ngc.Node:
    system = ngc.CoordinateSystem(
        id=cs_id,
        axes=[ngc.Axis(name=a, type="space", unit="micrometer") for a in ("y", "x")],
    )
    scales = [
        ngc.Scale(
            id=sid,
            path=ngc.ZarrPath(href=f"./s{level}"),
            coordinate_transformations=[
                ngc.ScaleTransformation(
                    scale=[0.1 * 2**level] * 2,
                    input=ngc.ReferenceObj(type="scale", ref=sid),
                    output=ngc.ReferenceObj(type="coordinate_system", ref=cs_id),
                )
            ],
        )
        for level, sid in enumerate(scale_ids)
    ]
    acquisition = ngc.AcquisitionTrait(
        acquisition=ngc.ReferenceObj(type="acquisition", ref=uid(0xB))
    )
    return ngc.new_multiscale(
        id=ms_id,
        name=name,
        coordinate_systems=[system],
        scales=scales,
        traits=[acquisition],
    )


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem

    fov0 = ngc.create(
        str(base / "A" / "1" / "0"),
        build_fov(uid(9), uid(0x22), [uid(0x30), uid(0x31)], "fov0"),
        overwrite=True,
    )
    fov1 = ngc.create(
        str(base / "A" / "1" / "1"),
        build_fov(uid(0xA), uid(0x23), [uid(0x32), uid(0x33)], "fov1"),
        overwrite=True,
    )

    scene = ngc.SceneTrait(
        coordinate_systems=[
            ngc.CoordinateSystem(
                id=uid(8),
                axes=[
                    ngc.Axis(name="y", type="space", unit="micrometer"),
                    ngc.Axis(name="x", type="space", unit="micrometer"),
                ],
            )
        ],
        coordinate_transformations=[
            ngc.TranslationTransformation(
                translation=[0, dx],
                input=ngc.ReferenceObj(
                    type="coordinate_system", ref=cs, path=ngc.ZarrPath(href=href)
                ),
                output=ngc.ReferenceObj(type="coordinate_system", ref=uid(8)),
            )
            for cs, href, dx in ((uid(0x22), "./A/1/0", 0), (uid(0x23), "./A/1/1", 820))
        ],
    )
    well = ngc.new_collection(
        id=uid(7), name="A1", traits=[ngc.WellTrait(row_index=0, column_index=0), scene]
    ).add_external(fov0, fov1)

    plate = ngc.PlateTrait(
        rows=[ngc.RowObj(name="A"), ngc.RowObj(name="B")],
        columns=[ngc.ColumnObj(name="1"), ngc.ColumnObj(name="2")],
        acquisitions=[
            ngc.AcquisitionObj(
                id=uid(0xB), name="t0", starttime=1727683200, endtime=1727686800
            )
        ],
    )
    root = ngc.new_collection(id=uid(6), name="plate-001", traits=[plate]).add(well)
    url = str(base / "zarr.json")
    ngc.create(url, root, overwrite=True)

    print(f"wrote {url}\n")
    print(Path(url).read_text())
    view = ngc.open_resolved(url)
    print(
        "fov0 acquisition:",
        view.find(uid(9))[ngc.AcquisitionTrait].acquisition.ref == uid(0xB),
    )
    print("validation:", view.validate(ngc.ALL_VALIDATORS))


if __name__ == "__main__":
    main()
