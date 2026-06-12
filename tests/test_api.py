"""The sync convenience API: open/write fully inlined single documents
through the background-loop runner (ngio_collections.api)."""

import json
from pathlib import Path

import pytest

import ngio_collections as ngc

REFERENCE_DIR = Path(__file__).parent / "data"


class CountingStore(ngc.LocalStore):
    """LocalStore that counts get() calls, to assert cache hits."""

    def __init__(self):
        self.gets = 0

    async def get(self, url: str) -> bytes:
        self.gets += 1
        return await super().get(url)


def _build_multiscale() -> ngc.MultiscaleNode:
    systems = ngc.CoordinateSystemsAttribute(
        [ngc.CoordinateSystem(id="physical", axes=[{"name": "x", "type": "space"}])]
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


def _build_collection() -> ngc.CollectionNode:
    return ngc.CollectionNode(
        id="experiment",
        name="Experiment",
        nodes=[_build_multiscale()],
        attributes={"ngio:description": "demo"},
    )


def test_open_collection_returns_inlined_tree():
    root = ngc.open_collection(str(REFERENCE_DIR / "externalised" / "collection.json"))

    assert isinstance(root, ngc.CollectionNode)
    plate = root.nodes[0]
    # Fully inlined: the externalized child is embedded, not a stub.
    assert plate.path is None
    well = plate.nodes[0]
    assert isinstance(well, ngc.MultiscaleNode)
    assert well.attributes["channel"] == "DAPI"
    # The data leaf survives with an absolute rebased path.
    s0 = well.nodes[0]
    assert s0.path.path == str(
        REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr" / "s0"
    )


def test_open_multiscale_direct_url_only():
    url = str(REFERENCE_DIR / "externalised" / "child" / "well_a01.zarr")
    image = ngc.open_multiscale(url)
    assert isinstance(image, ngc.MultiscaleNode)
    assert image.nodes[0].id == "s0"

    with pytest.raises(TypeError, match="expected a multiscale"):
        ngc.open_multiscale(str(REFERENCE_DIR / "externalised" / "collection.json"))
    with pytest.raises(TypeError, match="expected a collection"):
        ngc.open_collection(url)


def test_write_collection_roundtrip_single_file(tmp_path):
    url = str(tmp_path / "collection.json")
    ngc.write_collection(_build_collection(), url)

    # Exactly one file: the multiscale is embedded, not externalized.
    assert [p.name for p in tmp_path.iterdir()] == ["collection.json"]
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["version"] == "0.x"
    assert payload["nodes"][0]["type"] == "multiscale"
    assert "path" not in payload["nodes"][0]

    reopened = ngc.open_collection(url)
    assert reopened.attributes == {"ngio:description": "demo"}
    assert reopened.nodes[0].nodes[0].id == "s0"


def test_write_multiscale_zarr_form_roundtrip(tmp_path):
    url = str(tmp_path / "image.zarr")
    ngc.write_multiscale(_build_multiscale(), url)

    data = json.loads((tmp_path / "image.zarr" / "zarr.json").read_text())
    assert data["zarr_format"] == 3
    assert data["attributes"]["ome"]["version"] == "0.x"

    image = ngc.open_multiscale(url)
    assert image.name == "DAPI"
    # The singlescale keeps its document-relative data path.
    assert image.nodes[0].path.path == "./s0"


def test_write_embeds_tree_from_open_collection(tmp_path):
    # A tree whose nodes are owned by another document must be embedded
    # (deep-copied + detached), never re-emitted as stubs.
    source = ngc.open_collection(
        str(REFERENCE_DIR / "externalised" / "collection.json")
    )
    owning_doc = source._document
    url = str(tmp_path / "copy.json")
    ngc.write_collection(source, url)

    payload = json.loads(Path(url).read_text())["ome"]
    plate = payload["nodes"][0]
    assert "path" not in plate
    assert plate["nodes"][0]["type"] == "multiscale"
    # The input tree's ownership is untouched.
    assert source._document is owning_doc


async def test_sync_api_works_inside_running_loop():
    # The Jupyter case: a loop is already running in the calling thread.
    root = ngc.open_collection(str(REFERENCE_DIR / "externalised" / "collection.json"))
    assert isinstance(root, ngc.CollectionNode)


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
    resolver = ngc.Resolver(store)

    ngc.open_collection(url, resolver)
    fetched = store.gets
    assert fetched == 2  # the collection and its child document
    ngc.open_collection(url, resolver)
    assert store.gets == fetched  # second open is pure cache reads


def test_open_collection_max_depth_keeps_stubs():
    fixture = str(REFERENCE_DIR / "externalised" / "collection.json")

    shallow = ngc.open_collection(fixture, max_depth=0)
    # Nothing collapsed: the plate survives as a stub, path verbatim.
    plate = shallow.nodes[0]
    assert plate.path is not None
    assert plate.path.path == "./child/collection.json"

    partial = ngc.open_collection(fixture, max_depth=1)
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
    root = ngc.open_collection(url)
    assert root.nodes[0].path is not None

    with pytest.raises(FileNotFoundError):
        ngc.open_collection(url, on_error="raise")


def test_writer_type_checks(tmp_path):
    with pytest.raises(TypeError, match="CollectionNode"):
        ngc.write_collection(_build_multiscale(), str(tmp_path / "x.json"))
    with pytest.raises(TypeError, match="MultiscaleNode"):
        ngc.write_multiscale(_build_collection(), str(tmp_path / "x.zarr"))


def test_write_multiscale_returns_reference_stub(tmp_path):
    ref = ngc.write_multiscale(_build_multiscale(), str(tmp_path / "image.zarr"))

    # The reference form is its own type (and still a multiscale).
    assert isinstance(ref, ngc.MultiscaleRef)
    assert isinstance(ref, ngc.MultiscaleNode)
    assert ref.nodes is None
    assert isinstance(ref.path, ngc.ZarrPath)
    # Zarr form: the stub points at the group directory, not zarr.json.
    assert ref.path.path == str(tmp_path / "image.zarr")
    assert (ref.id, ref.name) == ("image", "DAPI")
    assert ref.attributes == {}
    assert ref._document is None


def test_write_collection_returns_json_reference_stub(tmp_path):
    url = str(tmp_path / "collection.json")
    ref = ngc.write_collection(_build_collection(), url)

    assert isinstance(ref, ngc.CollectionRef)
    assert ref.nodes is None
    assert isinstance(ref.path, ngc.JsonPath)
    assert ref.path.path == url
    # The reference form cannot carry embedded children.
    with pytest.raises(ValueError):
        ngc.CollectionRef(
            id="e", name="e", path=ngc.JsonPath(path="./c.json"), nodes=[]
        )


def test_reference_workflow_roundtrip(tmp_path):
    ref = ngc.write_multiscale(_build_multiscale(), str(tmp_path / "image.zarr"))
    # Parent-level attributes annotate the reference edge (stub wins on read).
    ref.attributes["ngio:description"] = "the DAPI image"
    collection = ngc.CollectionNode(id="experiment", name="Experiment", nodes=[ref])
    url = str(tmp_path / "collection.json")
    ngc.write_collection(collection, url)

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

    raw = ngc.open_collection(url, max_depth=0)
    # Parsing routes the path-bearing child to the reference form.
    assert isinstance(raw.nodes[0], ngc.MultiscaleRef)
    assert raw.nodes[0].path is not None
    assert raw.nodes[0].attributes == {"ngio:description": "the DAPI image"}

    inlined = ngc.open_collection(url)
    image = inlined.nodes[0]
    assert image.path is None
    assert image.nodes[0].id == "s0"
    # §5 merge: target attributes overlaid by the stub's.
    assert "coordinateSystems" in image.attributes
    assert image.attributes["ngio:description"] == "the DAPI image"


def test_reference_stub_wins_over_target_attribute(tmp_path):
    multiscale = _build_multiscale()
    multiscale.attributes["shared"] = "from-target"
    ref = ngc.write_multiscale(multiscale, str(tmp_path / "image.zarr"))
    ref.attributes["shared"] = "from-stub"
    collection = ngc.CollectionNode(id="experiment", name="Experiment", nodes=[ref])
    url = str(tmp_path / "collection.json")
    ngc.write_collection(collection, url)

    inlined = ngc.open_collection(url)
    assert inlined.nodes[0].attributes["shared"] == "from-stub"


def test_relativize_rules(tmp_path):
    ref = ngc.write_multiscale(
        _build_multiscale(), str(tmp_path / "images" / "image.zarr")
    )

    # Sibling directory: an up-level relative path that still resolves.
    url = str(tmp_path / "meta" / "collection.json")
    ngc.write_collection(
        ngc.CollectionNode(id="e", name="e", nodes=[ref.model_copy()]), url
    )
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["nodes"][0]["path"]["path"] == "../images/image.zarr"
    assert ngc.open_collection(url).nodes[0].nodes[0].id == "s0"

    # Already-relative and cross-scheme paths are kept verbatim.
    stubs = ngc.CollectionNode(
        id="e",
        name="e",
        nodes=[
            ngc.CollectionNode(
                id="rel", name="rel", path=ngc.JsonPath(path="./child.json")
            ),
            ngc.CollectionNode(
                id="remote",
                name="remote",
                path=ngc.JsonPath(path="https://example.com/c.json"),
            ),
        ],
    )
    url = str(tmp_path / "stubs.json")
    ngc.write_collection(stubs, url)
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["nodes"][0]["path"]["path"] == "./child.json"
    assert payload["nodes"][1]["path"]["path"] == "https://example.com/c.json"

    # Opt-out keeps the absolute path on disk.
    url = str(tmp_path / "absolute.json")
    ngc.write_collection(
        ngc.CollectionNode(id="e", name="e", nodes=[ref.model_copy()]),
        url,
        relativize=False,
    )
    payload = json.loads(Path(url).read_text())["ome"]
    assert payload["nodes"][0]["path"]["path"] == str(
        tmp_path / "images" / "image.zarr"
    )
