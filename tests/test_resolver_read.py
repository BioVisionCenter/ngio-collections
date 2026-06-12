"""Resolver read path: open / resolve / children over the on-disk fixtures
(ROADMAP M3)."""

import json
from pathlib import Path

import pytest

import ngio_collections as ngc

REFERENCE_DIR = Path(__file__).parent / "data"


@pytest.fixture
def resolver():
    return ngc.Resolver(ngc.LocalStore())


async def test_open_parses_and_caches(resolver):
    url = str(REFERENCE_DIR / "externalised" / "collection.json")
    doc = await resolver.open(url)
    assert isinstance(doc.root, ngc.CollectionNode)
    assert doc.root.id == "experiment-b"
    assert doc.form == "json"
    # Cached by URL: a second open returns the same MetadataDocument.
    assert await resolver.open(url) is doc


async def test_resolve_json_stub_against_declaring_document(resolver):
    doc = await resolver.open(str(REFERENCE_DIR / "externalised" / "collection.json"))
    stub = doc.root.nodes[0]
    assert stub.path is not None

    child = await resolver.resolve(stub)
    assert isinstance(child.root, ngc.CollectionNode)
    assert child.root.id == "plate-1"
    assert child.form == "json"
    assert child.stub_path == stub.path
    # Resolution is cached.
    assert await resolver.resolve(stub) is child


async def test_resolve_zarr_stub_targets_zarr_json(resolver):
    child = await resolver.open(
        str(REFERENCE_DIR / "externalised" / "child" / "collection.json")
    )
    stub = child.root.nodes[0]
    assert isinstance(stub.path, ngc.ZarrPath)

    image = await resolver.resolve(stub)
    assert image.form == "zarr"
    assert image.url.endswith("well_a01.zarr/zarr.json")
    assert isinstance(image.root, ngc.MultiscaleNode)
    assert image.root.nodes[0].id == "s0"


async def test_children_replaces_stubs_without_mutating(resolver):
    doc = await resolver.open(str(REFERENCE_DIR / "mixed" / "collection.json"))
    children = await resolver.children(doc.root)

    assert len(children) == 2
    # The inline child is returned as-is.
    assert children[0] is doc.root.nodes[0]
    assert isinstance(children[0], ngc.MultiscaleNode)
    # The stub is transparently replaced by the resolved document root...
    assert isinstance(children[1], ngc.CollectionNode)
    assert children[1].nodes == []
    # ...but the parsed tree itself keeps the stub in place (DESIGN.md §3.3).
    assert doc.root.nodes[1].path is not None
    assert doc.root.nodes[1].nodes is None


async def test_navigation_loop_over_fixtures(resolver, reference):
    """The DESIGN.md §5 read-side sketch, unmodified."""
    name, directory = reference
    doc = await resolver.open(str(directory / "collection.json"))
    root = doc.root

    seen = []
    for child in await resolver.children(root):
        seen.append((child.type, child.name))
    assert seen, name
    for child_type, child_name in seen:
        assert child_type in {"collection", "multiscale"}
        assert child_name


async def test_resolve_document_root_returns_its_document(resolver):
    doc = await resolver.open(str(REFERENCE_DIR / "inline" / "collection.json"))
    assert await resolver.resolve(doc.root) is doc


async def test_resolve_pathless_inline_node_rejected(resolver):
    doc = await resolver.open(str(REFERENCE_DIR / "inline" / "collection.json"))
    inline_child = doc.root.nodes[0]
    with pytest.raises(ValueError, match="nothing to resolve"):
        await resolver.resolve(inline_child)


async def test_resolve_detached_node_rejected(resolver):
    foreign = ngc.CollectionNode(
        id="x", name="x", path=ngc.JsonPath(path="./nowhere.json")
    )
    with pytest.raises(ValueError, match="detached"):
        await resolver.resolve(foreign)


async def test_resolve_missing_target_raises_file_not_found(resolver, tmp_path):
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "root",
                    "name": "root",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "gone",
                            "name": "gone",
                            "path": {"type": "json", "path": "./gone.json"},
                        }
                    ],
                }
            }
        )
    )
    doc = await resolver.open(str(doc_path))
    with pytest.raises(FileNotFoundError):
        await resolver.resolve(doc.root.nodes[0])


async def test_absolute_path_passes_through(resolver, tmp_path):
    target = tmp_path / "elsewhere" / "doc.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "remote",
                    "name": "remote",
                    "nodes": [],
                }
            }
        )
    )
    doc_path = tmp_path / "collection.json"
    doc_path.write_text(
        json.dumps(
            {
                "ome": {
                    "version": "0.x",
                    "type": "collection",
                    "id": "root",
                    "name": "root",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "remote",
                            "name": "remote",
                            "path": {"type": "json", "path": str(target)},
                        }
                    ],
                }
            }
        )
    )
    doc = await resolver.open(str(doc_path))
    resolved = await resolver.resolve(doc.root.nodes[0])
    assert resolved.url == str(target)
    assert resolved.root.id == "remote"


async def test_open_zarr_group_directory_appends_zarr_json(resolver):
    url = str(REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr")
    doc = await resolver.open(url)
    assert doc.form == "zarr"
    assert doc.url.endswith("well_a01.zarr/zarr.json")
    assert isinstance(doc.root, ngc.MultiscaleNode)


async def test_resolver_uses_its_registry(tmp_path):
    registry = ngc.NodeRegistry()  # nothing registered
    resolver = ngc.Resolver(ngc.LocalStore(), registry=registry)
    doc = await resolver.open(str(REFERENCE_DIR / "inline" / "collection.json"))
    assert type(doc.root) is ngc.BaseNode
