"""The async core: externalized documents, lazy reads, document-granular saves.

Writes an RFC-8 collection with one document per externalized node:

    data/resolver/
    ├── collection.json          <- root collection (stubs for the children)
    ├── tables/measurements.json <- nested collection, its own document
    └── image.zarr/zarr.json     <- multiscale, stored in zarr.json form

Then reads it back through the ``Resolver``: ``open()`` reads only the root
document (children stay stubs), ``resolve()`` fetches one child on demand,
``resolve_tree()`` warms the cache for the whole reachable tree, and editing
a node rewrites only its owning document on ``save()``.

Run with:

    pixi run -e dev python examples/03_resolver_read_write.py
"""

import asyncio
import hashlib
import shutil
from pathlib import Path

import ome_zarr_collections as ozc

ROOT = Path(__file__).parent / "data" / "resolver"
VERSION = "0.x"


def build_image() -> ozc.MultiscaleNode:
    """A multiscale image with one resolution level.

    The singlescale's path points at the array data; its scale transformation
    maps it into the "physical" coordinate system declared on the multiscale.
    """
    s0 = ozc.SinglescaleNode(
        id="s0",
        name="s0",
        path=ozc.ZarrPath(path="./s0"),
        attributes={
            "coordinateTransformations": [
                {
                    "type": "scale",
                    "scale": [1.0, 0.65, 0.65],
                    "input": {"id": "s0"},
                    "output": {"id": "physical"},
                }
            ]
        },
    )
    physical = ozc.CoordinateSystem(
        id="physical",
        axes=[
            {"name": "z", "type": "space", "unit": "micrometer"},
            {"name": "y", "type": "space", "unit": "micrometer"},
            {"name": "x", "type": "space", "unit": "micrometer"},
        ],
    )
    systems = ozc.CoordinateSystemsAttribute([physical])
    return ozc.MultiscaleNode(
        id="image",
        name="DAPI",
        nodes=[s0],
        attributes={
            systems.key: systems.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
        },
    )


async def write_fixture(resolver: ozc.Resolver) -> None:
    """One MetadataDocument per externalized node; the root references them
    through path stubs. ``stub_path`` is how the parent document will
    reference each child document."""
    image_doc = ozc.MetadataDocument(
        root=build_image(),
        url=str(ROOT / "image.zarr" / "zarr.json"),
        form="zarr",
        version=VERSION,
        stub_path=ozc.ZarrPath(path="./image.zarr"),
    )
    await resolver.save(image_doc)

    tables = ozc.CollectionNode(
        id="tables",
        name="Tables",
        nodes=[
            # Unregistered node types are perfectly valid: readers treat them
            # as opaque nodes and keep their custom fields.
            {"type": "fractal:table", "id": "t1", "name": "regionprops"},
        ],
    )
    tables_doc = ozc.MetadataDocument(
        root=tables,
        url=str(ROOT / "tables" / "measurements.json"),
        form="json",
        version=VERSION,
        stub_path=ozc.JsonPath(path="./tables/measurements.json"),
    )
    await resolver.save(tables_doc)

    root = ozc.CollectionNode(
        id="my-experiment",
        name="My Experiment",
        nodes=[
            ozc.MultiscaleNode(
                id="image", name="DAPI", path=ozc.ZarrPath(path="./image.zarr")
            ),
            ozc.CollectionNode(
                id="tables",
                name="Tables",
                path=ozc.JsonPath(path="./tables/measurements.json"),
            ),
        ],
    )
    root_doc = ozc.MetadataDocument(
        root=root, url=str(ROOT / "collection.json"), form="json", version=VERSION
    )
    await resolver.save(root_doc)


def print_tree(node: ozc.BaseNode, indent: int = 0) -> None:
    stub = f" -> {node.path.path}" if node.path is not None else ""
    print(f"{'  ' * indent}[{node.type}] {node.id}{stub}")
    for child in getattr(node, "nodes", None) or []:
        if isinstance(child, ozc.BaseNode):
            print_tree(child, indent + 1)


def snapshot() -> dict[Path, str]:
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob("*.json")}


async def main() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)
    await write_fixture(ozc.Resolver(ozc.LocalStore()))

    # A fresh resolver, so open() parses the documents from disk.
    resolver = ozc.Resolver(ozc.LocalStore())

    # --- Open only reads the root document; children stay as stubs ----------
    doc = await resolver.open(str(ROOT / "collection.json"))
    root = doc.root
    print("After open() (lazy, one file read):")
    print_tree(root)

    # --- Resolve a single child on demand ------------------------------------
    # Resolution never mutates the tree: `root` keeps its stub, the resolved
    # document lives in the resolver's URL-keyed cache.
    image_stub = root.find("image")
    image_doc = await resolver.resolve(image_stub)
    systems = image_doc.root.attrs[ozc.CoordinateSystemsAttribute]
    print(
        f"\nResolved {image_doc.root.id!r}: "
        f"coordinate systems = {[cs.id for cs in systems.root]}"
    )

    # --- Or warm the cache for the whole reachable tree ----------------------
    # Stubs whose path points at plain Zarr data rather than an OME metadata
    # document (the singlescale's `./s0` array) are skipped by default
    # (`on_error="skip"`). Afterwards children() / resolve() are cache reads.
    documents = await resolver.resolve_tree(doc)
    print(f"\nresolve_tree() fetched {len(documents)} documents:")
    for d in documents:
        print(f"  {d.form:>4}  {d.url}")

    # children() transparently replaces stubs with their resolved roots.
    for child in await resolver.children(root):
        print(f"child {child.id!r}: attrs={list(child.attributes)}")

    # --- Edit one node and save: only its owning document is rewritten ------
    before = snapshot()
    tables_doc = await resolver.resolve(root.find("tables"))
    tables_doc.root.attributes["fractal:status"] = "validated"
    await resolver.save(tables_doc)
    after = snapshot()

    print("\nFiles changed by save(tables):")
    for path in after:
        if before[path] != after[path]:
            print(f"  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
