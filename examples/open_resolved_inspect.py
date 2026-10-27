"""`open` vs `open_resolved`: external entries, spliced-in bodies, a read-only view.

`open` reads one document: cross-document nodes stay *external* (declaring
entries with a `path`). `open_resolved` follows the paths into one read-only
view: each image's body (`coordinate_systems`, `scales`) is spliced in and its
entry's traits combine with its own.

Run with: pixi run --environment dev python examples/open_resolved_inspect.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid
from _images import image


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
    assert isinstance(
        nuclei, ngc.MultiscaleNode
    )  # narrows the type for the access below
    print("nuclei scales :", [s.path.href for s in nuclei.scales])
    print("nuclei traits :", list(nuclei.traits))
    # A reference usable from another document: the path is `absolute` because
    # this document is local; `ref_local()` is the same-document form.
    print("portable ref  :", nuclei.ref().to_dict())
    print("local ref     :", nuclei.ref_local().to_dict())

    # A resolved view is read-only; edits go through `open` + `save`.
    try:
        ngc.save(view)
    except ngc.NodeStateError as error:
        print("save(view)    :", error)


if __name__ == "__main__":
    main()
