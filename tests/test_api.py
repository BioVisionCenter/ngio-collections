"""The sync convenience API: open/write fully inlined single documents
through the background-loop runner (ome_zarr_collections.api)."""

import json
from pathlib import Path

import pytest

import ome_zarr_collections as ozc

REFERENCE_DIR = Path(__file__).parent / "data"


class CountingStore(ozc.LocalStore):
    """LocalStore that counts get() calls, to assert cache hits."""

    def __init__(self):
        self.gets = 0

    async def get(self, url: str) -> bytes:
        self.gets += 1
        return await super().get(url)


def _build_multiscale() -> ozc.MultiscaleNode:
    systems = ozc.CoordinateSystemsAttribute(
        [ozc.CoordinateSystem(id="physical", axes=[{"name": "x", "type": "space"}])]
    )
    return ozc.MultiscaleNode(
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


def _build_collection() -> ozc.CollectionNode:
    return ozc.CollectionNode(
        id="experiment",
        name="Experiment",
        nodes=[_build_multiscale()],
        attributes={"ngio:description": "demo"},
    )


def test_open_collection_returns_inlined_tree():
    root = ozc.open_collection(str(REFERENCE_DIR / "externalised" / "collection.json"))

    assert isinstance(root, ozc.CollectionNode)
    plate = root.nodes[0]
    # Fully inlined: the externalized child is embedded, not a stub.
    assert plate.path is None
    well = plate.nodes[0]
    assert isinstance(well, ozc.MultiscaleNode)
    assert well.attributes["channel"] == "DAPI"
    # The data leaf survives with an absolute rebased path.
    s0 = well.nodes[0]
    assert s0.path.path == str(
        REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr" / "s0"
    )


def test_open_multiscale_direct_url_only():
    url = str(REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr")
    image = ozc.open_multiscale(url)
    assert isinstance(image, ozc.MultiscaleNode)
    assert image.nodes[0].id == "s0"

    with pytest.raises(TypeError, match="expected a multiscale"):
        ozc.open_multiscale(str(REFERENCE_DIR / "externalised" / "collection.json"))
    with pytest.raises(TypeError, match="expected a collection"):
        ozc.open_collection(url)


def test_write_collection_roundtrip_single_file(tmp_path):
    url = str(tmp_path / "collection.json")
    ozc.write_collection(_build_collection(), url)

    # Exactly one file: the multiscale is embedded, not externalized.
    assert [p.name for p in tmp_path.iterdir()] == ["collection.json"]
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["version"] == "0.x"
    assert payload["nodes"][0]["type"] == "multiscale"
    assert "path" not in payload["nodes"][0]

    reopened = ozc.open_collection(url)
    assert reopened.attributes == {"ngio:description": "demo"}
    assert reopened.nodes[0].nodes[0].id == "s0"


def test_write_multiscale_zarr_form_roundtrip(tmp_path):
    url = str(tmp_path / "image.zarr")
    ozc.write_multiscale(_build_multiscale(), url)

    data = json.loads((tmp_path / "image.zarr" / "zarr.json").read_text())
    assert data["zarr_format"] == 3
    assert data["attributes"]["ome"]["version"] == "0.x"

    image = ozc.open_multiscale(url)
    assert image.name == "DAPI"
    # The singlescale keeps its document-relative data path.
    assert image.nodes[0].path.path == "./s0"


def test_write_embeds_tree_from_open_collection(tmp_path):
    # A tree whose nodes are owned by another document must be embedded
    # (deep-copied + detached), never re-emitted as stubs.
    source = ozc.open_collection(
        str(REFERENCE_DIR / "externalised" / "collection.json")
    )
    owning_doc = source._document
    url = str(tmp_path / "copy.json")
    ozc.write_collection(source, url)

    payload = json.loads(Path(url).read_text())["ome"]
    plate = payload["nodes"][0]
    assert "path" not in plate
    assert plate["nodes"][0]["type"] == "multiscale"
    # The input tree's ownership is untouched.
    assert source._document is owning_doc


async def test_sync_api_works_inside_running_loop():
    # The Jupyter case: a loop is already running in the calling thread.
    root = ozc.open_collection(str(REFERENCE_DIR / "externalised" / "collection.json"))
    assert isinstance(root, ozc.CollectionNode)


def test_shared_resolver_reuses_cache(tmp_path):
    # A two-document fixture without data leaves (failed leaf fetches are
    # never cached, so they would legitimately re-count).
    (tmp_path / "child.json").write_text(
        json.dumps({"ome": {"type": "collection", "id": "c", "name": "c", "nodes": []}})
    )
    url = str(tmp_path / "collection.json")
    Path(url).write_text(
        json.dumps(
            {
                "ome": {
                    "type": "collection",
                    "id": "root",
                    "name": "root",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "c",
                            "name": "c",
                            "path": {"type": "json", "path": "./child.json"},
                        }
                    ],
                }
            }
        )
    )
    store = CountingStore()
    resolver = ozc.Resolver(store)

    ozc.open_collection(url, resolver)
    fetched = store.gets
    assert fetched == 2  # the collection and its child document
    ozc.open_collection(url, resolver)
    assert store.gets == fetched  # second open is pure cache reads


def test_open_collection_max_depth_keeps_stubs():
    fixture = str(REFERENCE_DIR / "externalised" / "collection.json")

    shallow = ozc.open_collection(fixture, max_depth=0)
    # Nothing collapsed: the plate survives as a stub, path verbatim.
    plate = shallow.nodes[0]
    assert plate.path is not None
    assert plate.path.path == "./child/collection.json"

    partial = ozc.open_collection(fixture, max_depth=1)
    plate = partial.nodes[0]
    assert plate.path is None  # first hop collapsed...
    well = plate.nodes[0]
    assert well.path is not None  # ...second hop survives, rebased absolute
    assert well.attributes == {}
    assert well.path.path == str(
        REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr"
    )


def test_open_collection_on_error_raise(tmp_path):
    url = str(tmp_path / "collection.json")
    Path(url).write_text(
        json.dumps(
            {
                "ome": {
                    "type": "collection",
                    "id": "root",
                    "name": "root",
                    "nodes": [
                        {
                            "type": "collection",
                            "id": "gone",
                            "name": "gone",
                            "path": {"type": "json", "path": "./missing.json"},
                        }
                    ],
                }
            }
        )
    )

    # Default: the unresolvable stub survives (data-leaf semantics).
    root = ozc.open_collection(url)
    assert root.nodes[0].path is not None

    with pytest.raises(FileNotFoundError):
        ozc.open_collection(url, on_error="raise")


def test_writer_type_checks(tmp_path):
    with pytest.raises(TypeError, match="CollectionNode"):
        ozc.write_collection(_build_multiscale(), str(tmp_path / "x.json"))
    with pytest.raises(TypeError, match="MultiscaleNode"):
        ozc.write_multiscale(_build_collection(), str(tmp_path / "x.zarr"))


def test_write_multiscale_returns_reference_stub(tmp_path):
    ref = ozc.write_multiscale(_build_multiscale(), str(tmp_path / "image.zarr"))

    # The reference form is its own type (and still a multiscale).
    assert isinstance(ref, ozc.MultiscaleRef)
    assert isinstance(ref, ozc.MultiscaleNode)
    assert ref.nodes is None
    assert isinstance(ref.path, ozc.ZarrPath)
    # Zarr form: the stub points at the group directory, not zarr.json.
    assert ref.path.path == str(tmp_path / "image.zarr")
    assert (ref.id, ref.name) == ("image", "DAPI")
    assert ref.attributes == {}
    assert ref._document is None


def test_write_collection_returns_json_reference_stub(tmp_path):
    url = str(tmp_path / "collection.json")
    ref = ozc.write_collection(_build_collection(), url)

    assert isinstance(ref, ozc.CollectionRef)
    assert ref.nodes is None
    assert isinstance(ref.path, ozc.JsonPath)
    assert ref.path.path == url
    # The reference form cannot carry embedded children.
    with pytest.raises(ValueError):
        ozc.CollectionRef(
            id="e", name="e", path=ozc.JsonPath(path="./c.json"), nodes=[]
        )


def test_reference_workflow_roundtrip(tmp_path):
    ref = ozc.write_multiscale(_build_multiscale(), str(tmp_path / "image.zarr"))
    # Parent-level attributes annotate the reference edge (stub wins on read).
    ref.attributes["ngio:description"] = "the DAPI image"
    collection = ozc.CollectionNode(id="experiment", name="Experiment", nodes=[ref])
    url = str(tmp_path / "collection.json")
    ozc.write_collection(collection, url)

    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["nodes"] == [
        {
            "type": "multiscale",
            "id": "image",
            "name": "DAPI",
            "path": {"type": "zarr", "path": "./image.zarr"},
            "attributes": {"ngio:description": "the DAPI image"},
        }
    ]

    raw = ozc.open_collection(url, max_depth=0)
    # Parsing routes the path-bearing child to the reference form.
    assert isinstance(raw.nodes[0], ozc.MultiscaleRef)
    assert raw.nodes[0].path is not None
    assert raw.nodes[0].attributes == {"ngio:description": "the DAPI image"}

    inlined = ozc.open_collection(url)
    image = inlined.nodes[0]
    assert image.path is None
    assert image.nodes[0].id == "s0"
    # §5 merge: target attributes overlaid by the stub's.
    assert "coordinateSystems" in image.attributes
    assert image.attributes["ngio:description"] == "the DAPI image"


def test_reference_stub_wins_over_target_attribute(tmp_path):
    multiscale = _build_multiscale()
    multiscale.attributes["shared"] = "from-target"
    ref = ozc.write_multiscale(multiscale, str(tmp_path / "image.zarr"))
    ref.attributes["shared"] = "from-stub"
    collection = ozc.CollectionNode(id="experiment", name="Experiment", nodes=[ref])
    url = str(tmp_path / "collection.json")
    ozc.write_collection(collection, url)

    inlined = ozc.open_collection(url)
    assert inlined.nodes[0].attributes["shared"] == "from-stub"


def test_relativize_rules(tmp_path):
    ref = ozc.write_multiscale(
        _build_multiscale(), str(tmp_path / "images" / "image.zarr")
    )

    # Sibling directory: an up-level relative path that still resolves.
    url = str(tmp_path / "meta" / "collection.json")
    ozc.write_collection(
        ozc.CollectionNode(id="e", name="e", nodes=[ref.model_copy()]), url
    )
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["nodes"][0]["path"]["path"] == "../images/image.zarr"
    assert ozc.open_collection(url).nodes[0].nodes[0].id == "s0"

    # Already-relative and cross-scheme paths are kept verbatim.
    stubs = ozc.CollectionNode(
        id="e",
        name="e",
        nodes=[
            ozc.CollectionNode(
                id="rel", name="rel", path=ozc.JsonPath(path="./child.json")
            ),
            ozc.CollectionNode(
                id="remote",
                name="remote",
                path=ozc.JsonPath(path="https://example.com/c.json"),
            ),
        ],
    )
    url = str(tmp_path / "stubs.json")
    ozc.write_collection(stubs, url)
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["nodes"][0]["path"]["path"] == "./child.json"
    assert payload["nodes"][1]["path"]["path"] == "https://example.com/c.json"

    # Opt-out keeps the absolute path on disk.
    url = str(tmp_path / "absolute.json")
    ozc.write_collection(
        ozc.CollectionNode(id="e", name="e", nodes=[ref.model_copy()]),
        url,
        relativize=False,
    )
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["nodes"][0]["path"]["path"] == str(
        tmp_path / "images" / "image.zarr"
    )
