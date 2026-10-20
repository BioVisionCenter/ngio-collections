"""`open` vs `open_resolved`, portable references, validation and `delete`.

`open` reads one document: cross-document nodes stay *external* (declaring
entries with a `path`). `open_resolved` follows the paths into one read-only
view: each image's body (`coordinate_systems`, `scales`) is spliced in and its
entry's traits combine with its own. `delete(cascade=True)` removes an entry
*and* the document it points at.

Run with: pixi run python examples/open_resolved_inspect.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid


def image(n: int, name: str) -> ngc.Node:
    cs, sc = uid(0x20 + n), uid(0x30 + n)
    return ngc.new_multiscale(
        id=uid(n),
        name=name,
        coordinate_systems=[
            ngc.CoordinateSystem(id=cs, axes=[ngc.Axis(name="y"), ngc.Axis(name="x")])
        ],
        scales=[
            ngc.Scale(
                id=sc,
                path=ngc.ZarrPath(href="./s0"),
                coordinate_transformations=[
                    ngc.ScaleTransformation(
                        scale=[1.0, 1.0],
                        input=ngc.ReferenceObj(type="scale", ref=sc),
                        output=ngc.ReferenceObj(type="coordinate_system", ref=cs),
                    )
                ],
            )
        ],
    )


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base / "zarr.json")
    img = ngc.create(str(base / "image"), image(2, "image"), overwrite=True)
    nuc = ngc.create(
        str(base / "nuclei"),
        image(3, "nuclei").set_trait(
            ngc.LabelsTrait(source=[ngc.ReferenceObj(type="multiscale", ref=uid(2))])
        ),
        overwrite=True,
    )
    ngc.create(
        url,
        ngc.new_collection(id=uid(1), name="root").add_external(img, nuc),
        overwrite=True,
    )

    opened = ngc.open(url)
    print(
        "open          :", [(n.name, n.is_external, n.ref_path) for n in opened.walk()]
    )
    view = ngc.open_resolved(url)
    print(
        "open_resolved :",
        [(n.name, n.is_external, n.document_url) for n in view.walk()],
    )
    nuclei = view.find(uid(3))
    assert isinstance(nuclei, ngc.MultiscaleNode)
    print("nuclei scales :", [s.path.href for s in nuclei.scales])
    print("portable ref  :", nuclei.ref().to_dict())
    print("validation    :", view.validate(ngc.ALL_VALIDATORS))

    # A resolved view is read-only; edits go through `open` + `save`.
    try:
        ngc.save(view)
    except ngc.NodeStateError as error:
        print("save(view)    :", error)

    # Drop the labels image: the entry from the collection and its document.
    affected = ngc.delete(opened.find(uid(3)), cascade=True)
    print("deleted       :", affected)
    print("after delete  :", [n.name for n in ngc.open_resolved(url).walk()])


if __name__ == "__main__":
    main()
