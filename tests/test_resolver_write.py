"""Resolver write path: document-granular saves (ROADMAP M4).

Editing one node's attributes and saving touches exactly one file on disk;
a re-opened tree reflects the edit with everything else byte-identical.
"""

import json
import shutil
from pathlib import Path

import pytest

import ome_zarr_collections as ozc

REFERENCE_DIR = Path(__file__).parent / "data"


@pytest.fixture
def layout(tmp_path):
    """A writable copy of the `externalised` reference layout."""
    target = tmp_path / "externalised"
    shutil.copytree(REFERENCE_DIR / "externalised", target)
    return target


@pytest.fixture
def resolver():
    return ozc.Resolver(ozc.LocalStore())


def _all_files(directory: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(directory)): p.read_bytes()
        for p in sorted(directory.rglob("*.json"))
    }


async def test_save_rewrites_only_the_owning_document(layout, resolver):
    root_doc = await resolver.open(str(layout / "collection.json"))
    child_doc = await resolver.resolve(root_doc.root.nodes[0])

    before = _all_files(layout)
    child_doc.root.attributes["custom:flag"] = True
    await resolver.save(child_doc)

    after = _all_files(layout)
    changed = {rel for rel in before if before[rel] != after[rel]}
    assert changed == {"child/collection.json"}

    saved = json.loads((layout / "child" / "collection.json").read_text())
    assert saved["ome"]["attributes"]["custom:flag"] is True


async def test_edit_save_reopen_round_trip(layout, resolver):
    root_doc = await resolver.open(str(layout / "collection.json"))
    child_doc = await resolver.resolve(root_doc.root.nodes[0])
    child_doc.root.attributes["custom:stage"] = "reviewed"
    await resolver.save(child_doc)

    fresh = ozc.Resolver(ozc.LocalStore())
    reopened_root = await fresh.open(str(layout / "collection.json"))
    reopened_child = await fresh.resolve(reopened_root.root.nodes[0])
    assert reopened_child.root.attributes["custom:stage"] == "reviewed"
    # Everything else is structurally unchanged.
    assert reopened_child.root.id == "plate-1"
    assert reopened_child.root.nodes[0].path is not None


async def test_save_zarr_preserves_sibling_keys(layout, resolver):
    child_doc = await resolver.open(str(layout / "child" / "collection.json"))
    image_doc = await resolver.resolve(child_doc.root.nodes[0])
    assert image_doc.form == "zarr"

    original = json.loads(
        (layout / "child" / "well_a01.zarr" / "zarr.json").read_text()
    )
    image_doc.root.attributes["custom:note"] = "hi"
    await resolver.save(image_doc)

    saved = json.loads((layout / "child" / "well_a01.zarr" / "zarr.json").read_text())
    # Sibling keys of attributes.ome survive the read-modify-write.
    assert saved["zarr_format"] == 3
    assert saved["node_type"] == "group"
    assert saved["custom_key"] == 42
    assert saved["attributes"]["ome"]["attributes"]["custom:note"] == "hi"
    # The singlescale child is written back unchanged.
    assert saved["attributes"]["ome"]["nodes"] == original["attributes"]["ome"]["nodes"]


async def test_save_root_re_emits_stubs(layout, resolver):
    """Resolved children graft back as path stubs, not inlined subtrees."""
    root_doc = await resolver.open(str(layout / "collection.json"))
    child_doc = await resolver.resolve(root_doc.root.nodes[0])
    original = json.loads((layout / "collection.json").read_text())

    # Graft the resolved child over its stub (resolution itself never
    # mutates the tree), then save the root document.
    root_doc.root.nodes[0] = child_doc.root
    await resolver.save(root_doc)

    saved = json.loads((layout / "collection.json").read_text())
    assert saved == original


async def test_save_zarr_creates_default_envelope_when_absent(layout, resolver):
    image_doc = await resolver.open(str(layout / "child" / "well_a01.zarr"))
    (layout / "child" / "well_a01.zarr" / "zarr.json").unlink()

    await resolver.save(image_doc)
    saved = json.loads((layout / "child" / "well_a01.zarr" / "zarr.json").read_text())
    assert saved["zarr_format"] == 3
    assert saved["node_type"] == "group"
    assert saved["attributes"]["ome"]["id"] == "well-a01"


async def test_save_read_only_store_fails_early(layout):
    class ReadOnlyLocalStore(ozc.LocalStore):
        read_only = True

        async def put(self, url: str, data: bytes) -> None:  # pragma: no cover
            raise AssertionError("save() must fail before reaching put()")

    resolver = ozc.Resolver(ReadOnlyLocalStore())
    doc = await resolver.open(str(layout / "collection.json"))
    before = (layout / "collection.json").read_bytes()
    with pytest.raises(ozc.StoreReadOnlyError):
        await resolver.save(doc)
    assert (layout / "collection.json").read_bytes() == before


async def test_save_store_without_put_fails_early(layout):
    local = ozc.LocalStore()

    class GetOnlyStore:
        async def get(self, url: str) -> bytes:
            return await local.get(url)

    resolver = ozc.Resolver(GetOnlyStore())
    doc = await resolver.open(str(layout / "collection.json"))
    with pytest.raises(ozc.StoreReadOnlyError):
        await resolver.save(doc)


async def test_saved_document_visible_through_resolver_cache(layout, resolver):
    doc = await resolver.open(str(layout / "collection.json"))
    doc.root.attributes["custom:k"] = 1
    await resolver.save(doc)
    assert await resolver.open(str(layout / "collection.json")) is doc
