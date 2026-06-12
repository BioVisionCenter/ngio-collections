"""Inline a resolved tree: the attribute merge materialized (DESIGN.md §5).

The collection's `image` stub carries its own attributes
(`ngio:description`) on top of the target multiscale's
(`coordinateSystems`, `labels`). `Resolver.inline()` builds a NEW document
in which the stub is collapsed into a copy of its resolved subtree, with
the merged attributes: target root's overlaid by the stub's (stub wins) and
the stub's id/name. The originals are never touched.

Writes stay explicit and document-granular — annotating a multiscale on a
read-only store means writing to the stub and saving only the collection
document, which this script also demonstrates.

Run with:

    pixi run -e dev python examples/04_inline_and_merge.py
"""

import asyncio
import hashlib
import shutil
from pathlib import Path

import ome_zarr_collections as ozc
from ome_zarr_collections.models import LabelObj

ROOT = Path(__file__).parent / "data" / "inline"
VERSION = "0.x"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


async def write_fixture() -> None:
    """A collection whose stub annotates an externalized multiscale."""
    resolver = ozc.Resolver(ozc.LocalStore())
    systems = ozc.CoordinateSystemsAttribute(
        [ozc.CoordinateSystem(id="physical", axes=[{"name": "x", "type": "space"}])]
    )
    image = ozc.MultiscaleNode(
        id="image",
        name="DAPI",
        nodes=[
            ozc.SinglescaleNode(
                id="s0",
                name="s0",
                path=ozc.ZarrPath(path="./s0"),
                attributes={"coordinateTransformations": []},
            )
        ],
        attributes={systems.key: systems.model_dump(mode="json", by_alias=True)},
    )
    image.attrs[ozc.LabelsAttribute] = ozc.LabelsAttribute(
        label_attributes=[LabelObj(label_value=1, color=[255, 0, 0, 255])]
    )
    await resolver.save(
        ozc.MetadataDocument(
            root=image,
            url=str(ROOT / "image.zarr" / "zarr.json"),
            form="zarr",
            version=VERSION,
            stub_path=ozc.ZarrPath(path="./image.zarr"),
        )
    )
    root = ozc.CollectionNode(
        id="my-experiment",
        name="My Experiment",
        nodes=[
            ozc.MultiscaleNode(
                id="image",
                name="DAPI",
                path=ozc.ZarrPath(path="./image.zarr"),
                attributes={"ngio:description": "stub-side annotation"},
            )
        ],
    )
    await resolver.save(
        ozc.MetadataDocument(
            root=root, url=str(ROOT / "collection.json"), form="json", version=VERSION
        )
    )


async def main() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)
    await write_fixture()

    # A fresh resolver, so open() parses the documents from disk.
    resolver = ozc.Resolver(ozc.LocalStore())
    doc = await resolver.open(str(ROOT / "collection.json"))
    stub = doc.root.nodes[0]

    print("stub attributes:  ", list(stub.attributes))
    target = (await resolver.resolve(stub)).root
    print("target attributes:", list(target.attributes))

    # The §5 merge, materialized: the stub collapsed into its resolved
    # subtree, target attributes overlaid by the stub's (stub wins).
    inlined = await resolver.inline(doc)
    image = inlined.root.nodes[0]
    print("merged attributes:", list(image.attributes))

    # The inlined node is a real node: typed reads via the normal attrs view.
    labels = image.attrs[ozc.LabelsAttribute]
    print("label colors:", [label.color for label in labels.label_attributes])

    # The originals are untouched: the parsed tree keeps its stub.
    print("original stub intact:", stub.path is not None and stub.nodes is None)

    # Annotate the (possibly read-only) multiscale via the stub: only the
    # collection document is rewritten, image.zarr/zarr.json is untouched.
    zarr_json = ROOT / "image.zarr" / "zarr.json"
    before = digest(zarr_json)
    stub.attributes["ngio:reviewed"] = True
    await resolver.save(doc)
    print("\nsaved", doc.url)
    print("image.zarr/zarr.json untouched:", digest(zarr_json) == before)
    reinlined = await resolver.inline(doc)
    print("merged attributes:", list(reinlined.root.nodes[0].attributes))


if __name__ == "__main__":
    asyncio.run(main())
