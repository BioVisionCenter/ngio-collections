"""The pure model layer: nodes, typed attributes, and document round-trips.

No IO in this script — nodes and documents are plain Pydantic objects
(DESIGN.md §7). Shows structural validation at construction, the typed
``attrs`` view over the raw attributes dict, ``walk()`` / ``find()``
navigation, and the ``parse_metadata_document`` / ``serialize`` round-trip.

Run with:

    pixi run -e dev python examples/02_models_and_documents.py
"""

import json

from pydantic import ValidationError

import ome_zarr_collections as ozc
from ome_zarr_collections.models import LabelObj


def build_tree() -> ozc.CollectionNode:
    s0 = ozc.SinglescaleNode(
        id="s0",
        name="s0",
        path=ozc.ZarrPath(path="./s0"),
        attributes={
            "coordinateTransformations": [
                {
                    "type": "scale",
                    "scale": [0.65, 0.65],
                    "input": {"id": "s0"},
                    "output": {"id": "physical"},
                }
            ]
        },
    )
    systems = ozc.CoordinateSystemsAttribute(
        [
            ozc.CoordinateSystem(
                id="physical",
                axes=[{"name": "y", "type": "space"}, {"name": "x", "type": "space"}],
            )
        ]
    )
    image = ozc.MultiscaleNode(
        id="image",
        name="DAPI",
        nodes=[s0],
        attributes={systems.key: systems.model_dump(mode="json", by_alias=True)},
    )
    return ozc.CollectionNode(id="experiment", name="My Experiment", nodes=[image])


def main() -> None:
    # --- Structural rules are enforced at construction ----------------------
    try:
        ozc.CollectionNode(id="c", name="c")  # neither `nodes` nor `path`
    except ValidationError as err:
        print("validation error:", err.errors()[0]["msg"])

    root = build_tree()

    # --- walk() / find(): flat traversal and id lookup ----------------------
    print("\nwalk:", [node.id for node in root.walk()])
    image = root.find("image")
    assert isinstance(image, ozc.MultiscaleNode)

    # --- The attrs view: typed, validating reads and writes -----------------
    # Reads validate the raw JSON into the attribute model; assignment dumps
    # the spec shape back into the dict. The raw dict stays the source of
    # truth, so unknown attributes round-trip untouched.
    systems = image.attrs[ozc.CoordinateSystemsAttribute]
    print("axes:", [axis["name"] for axis in systems.root[0].axes])

    image.attrs[ozc.LabelsAttribute] = ozc.LabelsAttribute(
        label_attributes=[LabelObj(label_value=1, color=[255, 0, 0, 255])]
    )
    print("labels set:", ozc.LabelsAttribute in image.attrs)

    # --- Documents: serialize and re-parse, no IO ---------------------------
    # A MetadataDocument is the unit of serialization; the `ome` version
    # lives on it, off the node models.
    doc = ozc.MetadataDocument(
        root=root, url="memory://collection.json", form="json", version="0.x"
    )
    payload = doc.serialize()
    print("\nserialized document:")
    print(json.dumps(payload, indent=2)[:300], "...")

    reparsed = ozc.parse_metadata_document(payload, url="memory://collection.json")
    assert [n.id for n in reparsed.root.walk()] == [n.id for n in root.walk()]
    print("\nround-trip preserves the tree:", [n.id for n in reparsed.root.walk()])

    # --- Graceful degradation: unknown types stay opaque --------------------
    custom = ozc.CollectionNode(
        id="c",
        name="c",
        nodes=[{"type": "mobie:view", "id": "v1", "name": "view", "customField": 42}],
    )
    view = custom.nodes[0]
    print("\nunknown type parses as:", type(view).__name__)
    print("extras round-trip:", view.model_dump(by_alias=True)["customField"])


if __name__ == "__main__":
    main()
