"""Build the revision's `plate.json` example with the provisional HCS traits.

    plate-001 (collection, plate trait: rows A/B, columns 1/2, acquisition t0)
    └── A1 (collection, well + scene traits)
        ├── fov0 -> ./A/1/0 (multiscale; acquisition trait on its entry)
        └── fov1 -> ./A/1/1 (multiscale; acquisition trait on its entry)

HCS is deferred to a sub-RFC; `PlateTrait` / `WellTrait` / `AcquisitionTrait`
follow the revision's example and are marked provisional. Note the well is an
*embedded* collection (any node may be inlined or be its own document), and
that `acquisition` on an image's entry is a typed reference to the
acquisition *declared* in the plate trait. The generated document mirrors
the revision's `examples/plate.json`.

Run with: pixi run --environment dev python examples/hcs_plate.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid
from _images import image, system_id


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem

    fov0 = ngc.create(
        str(base / "A" / "1" / "0"), image(9, "fov0", levels=2), overwrite=True
    )
    fov1 = ngc.create(
        str(base / "A" / "1" / "1"), image(0xA, "fov1", levels=2), overwrite=True
    )
    # The acquisition trait goes on each ENTRY in the plate document (as in the
    # spec), not into the image documents.
    acquisition = ngc.AcquisitionTrait(
        acquisition=ngc.ReferenceObj(type="acquisition", ref=uid(0xB))
    )
    fov0, fov1 = fov0.set_trait(acquisition), fov1.set_trait(acquisition)

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
            for cs, href, dx in (
                (system_id(9), "./A/1/0", 0),
                (system_id(0xA), "./A/1/1", 820),
            )
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

    print(f"wrote {url}")
    view = ngc.open_resolved(url)
    # The entry's typed reference resolves to the acquisition the plate declares.
    ref = view.find(uid(9))[ngc.AcquisitionTrait].acquisition
    (acquired,) = [a for a in view[ngc.PlateTrait].acquisitions if a.id == ref.ref]
    print("fov0 acquisition:", acquired.name)
    print("validation      :", view.validate(ngc.ALL_VALIDATORS))


if __name__ == "__main__":
    main()
