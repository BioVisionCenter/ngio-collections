"""Registering custom node types (DESIGN.md §3.4).

A third-party package subclasses ``BaseNode``, registers it under its
``type`` key in a ``NodeRegistry``, and children parse as the custom class.
Registries are plain objects, not singletons: pass one to
``parse_metadata_document(..., registry=...)`` or ``Resolver(store,
registry=...)``. Unregistered types degrade gracefully to a plain
``BaseNode`` and round-trip their extra fields untouched.

Run with:

    pixi run -e dev python examples/05_custom_node_types.py
"""

from typing import Literal

import ome_zarr_collections as ozc


class TableNode(ozc.BaseNode):
    """A custom node type with its own typed field."""

    type: Literal["fractal:table"] = "fractal:table"
    region: str | None = None


def build_registry() -> ozc.NodeRegistry:
    # A fresh registry starts empty: register the built-ins you need plus
    # your own types (DEFAULT_REGISTRY keeps the everyday ergonomics).
    registry = ozc.NodeRegistry()
    registry.register("collection", ozc.CollectionNode)
    registry.register("multiscale", ozc.MultiscaleNode)
    registry.register("singlescale", ozc.SinglescaleNode)
    registry.register("fractal:table", TableNode)
    return registry


DATA = {
    "ome": {
        "version": "0.x",
        "type": "collection",
        "id": "experiment",
        "name": "My Experiment",
        "nodes": [
            {
                "type": "fractal:table",
                "id": "t1",
                "name": "regionprops",
                "region": "FOV_1",
            },
            {"type": "mobie:view", "id": "v1", "name": "view", "customField": 42},
        ],
    }
}


def main() -> None:
    doc = ozc.parse_metadata_document(
        DATA, url="memory://collection.json", registry=build_registry()
    )
    table = doc.root.find("t1")
    print(f"registered type parses as {type(table).__name__}, region={table.region!r}")

    # Unregistered types stay opaque BaseNodes; their extras round-trip.
    view = doc.root.find("v1")
    dumped = doc.serialize()["ome"]["nodes"][1]
    print(f"unregistered type parses as {type(view).__name__}, dump={dumped}")

    # Without the registry, the custom type is opaque too (graceful
    # degradation) — same document, no error, no custom field typing.
    plain = ozc.parse_metadata_document(DATA, url="memory://collection.json")
    print("without registry:", type(plain.root.find("t1")).__name__)


if __name__ == "__main__":
    main()
