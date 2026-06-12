"""Every fixture document in tests/data validates through the registry with
the right subtypes (ROADMAP M1)."""

import json

import ngio_collections as ngc
from ngio_collections.models import validate_node

EXPECTED_TYPES = {
    "collection": ngc.CollectionNode,
    "multiscale": ngc.MultiscaleNode,
    "singlescale": ngc.SinglescaleNode,
}

# Path-bearing collections/multiscales parse as the narrowed reference form.
EXPECTED_REF_TYPES = {
    "collection": ngc.CollectionRef,
    "multiscale": ngc.MultiscaleRef,
    "singlescale": ngc.SinglescaleNode,
}


def _ome_payloads(directory):
    """(file, ome payload) for every metadata document under ``directory``."""
    for path in sorted(directory.rglob("*.json")):
        data = json.loads(path.read_text())
        if path.name == "zarr.json":
            yield path, data["attributes"]["ome"]
        else:
            yield path, data["ome"]


def _walk(node):
    yield node
    for child in getattr(node, "nodes", None) or []:
        yield from _walk(child)


def test_fixture_documents_validate_with_right_subtypes(reference):
    _, directory = reference
    payloads = list(_ome_payloads(directory))
    assert payloads, f"no metadata documents under {directory}"
    for path, payload in payloads:
        root = validate_node(payload)
        for node in _walk(root):
            expected = EXPECTED_REF_TYPES if node.path is not None else EXPECTED_TYPES
            assert type(node) is expected[node.type], (path, node.id)


def test_fixture_stubs_keep_their_path(reference):
    name, directory = reference
    if name == "inline":
        return
    data = json.loads((directory / "collection.json").read_text())
    root = validate_node(data["ome"])
    stub = next(n for n in root.nodes if n.path is not None)
    assert isinstance(stub, ngc.CollectionRef)
    assert stub.nodes is None
