"""Quickstart: the sync convenience API for scripts and notebooks.

No ``asyncio.run()`` anywhere — that's the point. ``write_multiscale`` /
``write_collection`` emit one document each (children embedded) and return a
reference stub for it, so a collection can reference the written document
instead of embedding a copy; ``open_collection`` / ``open_multiscale`` return
the fully inlined tree. ``walk()`` / ``find()`` navigate the result.

Run with:

    pixi run -e dev python examples/01_sync_api.py
"""

import shutil
from pathlib import Path

import ngio_collections as ngc

ROOT = Path(__file__).parent / "data" / "sync_api"


def build_multiscale() -> ngc.MultiscaleNode:
    systems = ngc.CoordinateSystemsAttribute(
        [
            ngc.CoordinateSystem(
                id="physical",
                axes=[{"name": "y", "type": "space"}, {"name": "x", "type": "space"}],
            )
        ]
    )
    return ngc.MultiscaleNode(
        id="image",
        name="DAPI",
        nodes=[
            ngc.SinglescaleNode(
                id="s0",
                name="s0",
                path=ngc.ZarrPath(path="./s0"),
                attributes={"coordinateTransformations": []},
            )
        ],
        attributes={systems.key: systems.model_dump(mode="json", by_alias=True)},
    )


def show(node: ngc.BaseNode, depth: int = 0) -> None:
    print(f"{'  ' * depth}{node.type} {node.id!r} attrs={list(node.attributes)}")
    for child in getattr(node, "nodes", None) or []:
        if isinstance(child, ngc.BaseNode):
            show(child, depth + 1)


def main() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)

    # A multiscale as its own zarr-form document (singlescales embedded).
    # The writer hands back the reference form: {type, id, name, path}.
    ref: ngc.MultiscaleRef = ngc.write_multiscale(
        build_multiscale(), str(ROOT / "image.zarr")
    )
    # Parent-level attributes live on the stub; they win over the target's
    # attributes when the reference is inlined on read.
    ref.attributes["ngio:description"] = "sync api demo"

    # The collection references the existing document instead of embedding it;
    # the stub path is relativized on write ("./image.zarr").
    collection = ngc.CollectionNode(
        id="experiment",
        name="My Experiment",
        nodes=[ref],
    )
    ngc.write_collection(collection, str(ROOT / "collection.json"))
    root = ngc.open_collection(str(ROOT / "collection.json"))
    print("collection tree (fully inlined):")
    show(root)

    # Navigation: walk() flattens the subtree (self first, depth-first) and
    # find() looks a node up by id — no hand-rolled recursion needed.
    print("\nwalk() — flat view of the tree:")
    for node in root.walk():
        print(f"  {node.type} {node.id!r}")

    s0 = root.find("s0")
    assert s0 is not None
    print(f"\nfind('s0') -> {s0.type} {s0.id!r} name={s0.name!r}")

    # A multiscale document can also be opened directly, and its attributes
    # read through the typed attrs view.
    image = ngc.open_multiscale(str(ROOT / "image.zarr"))
    systems = image.attrs[ngc.CoordinateSystemsAttribute]
    print(f"\nopen_multiscale: coordinate systems = {[cs.id for cs in systems.root]}")

    # the stub's path is the target URL, even on the inlined document
    # this can be used for data access
    print(f"\nimage.nodes[0].target_url -> {image.nodes[0].target_url}")


if __name__ == "__main__":
    main()
