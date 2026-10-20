"""A local collection pointing at a *remote* image: the `http` path deviation.

RFC-8 revision 1 makes only `relative` a core path format and defers `absolute`
and `http` to a sub-RFC. This package deliberately resolves all three, so a
collection can reference existing data (a published image, remote arrays) with
nothing copied. Strict conformance is one flag away: `formats=CORE_FORMATS`
leaves such nodes unresolved, and the `paths_are_core` validator flags them.

No network here: the "remote" document lives in a `MemoryStore` behind
`RoutedStore`, which dispatches `http(s)://` URLs to one backend and local
paths to another (the default store does the same with `HttpStore`).

Run with: pixi run python examples/remote_collection.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid

REMOTE = "https://example.org/data/reference.ome.zarr"


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base / "zarr.json")

    # The published image, as it would exist on a server (remote arrays as scales too).
    cs, sc = uid(0x20), uid(0xC)
    remote_image = ngc.new_multiscale(
        id=uid(4),
        name="published-reference",
        coordinate_systems=[
            ngc.CoordinateSystem(id=cs, axes=[ngc.Axis(name="y"), ngc.Axis(name="x")])
        ],
        scales=[
            ngc.Scale(
                id=sc,
                path=ngc.ZarrPath(format="http", href=f"{REMOTE}/0"),
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
    remote = ngc.MemoryStore()
    ngc.create(REMOTE, remote_image, remote)

    # The local collection only declares the entry: same UUID, http path.
    entry = ngc.new_node(
        "multiscale",
        id=uid(4),
        name="published-reference",
        path=ngc.DocPath.for_url(REMOTE),
    )
    ngc.create(
        url,
        ngc.new_collection(id=uid(1), name="my-analysis").add_external(entry),
        overwrite=True,
    )
    print(Path(url).read_text())

    store = ngc.RoutedStore(http=remote)  # local paths go to LocalStore
    view = ngc.open_resolved(url, store)
    node = view.find(uid(4))
    assert isinstance(node, ngc.MultiscaleNode)
    print(
        "resolved (deviation):",
        not node.is_external,
        [s.path.href for s in node.scales],
    )
    strict = ngc.open_resolved(url, store, formats=ngc.CORE_FORMATS)
    print("resolved (strict)   :", not strict.find(uid(4)).is_external)
    print(
        "paths_are_core      :",
        [(e.validator, e.node_uuid[-4:]) for e in view.validate((ngc.paths_are_core,))],
    )
    print("bundled validators  :", view.validate(ngc.ALL_VALIDATORS))


if __name__ == "__main__":
    main()
