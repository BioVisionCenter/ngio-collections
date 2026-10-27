"""Tests for the trait lenses and the core / recommended validators.

Each validator gets one passing and one failing case over bounded
neighbourhoods; the revision fixtures must validate clean except for the
remote node that a memory store cannot resolve.
"""

from __future__ import annotations

import pytest

import ngio_collections as ngc
import ngio_collections.api._api as aio
from ngio_collections.api import MemoryStore
from ngio_collections.graph import ROOT, NodeRecord, NodeTree
from ngio_collections.validate import (
    CORE_VALIDATORS,
    RECOMMENDED_VALIDATORS,
    get_trait,
    has_trait,
    read_fields,
)
from tests._builders import collection, external, multiscale, scale_id
from tests.conftest import DATA, mk

# Lenses and validators read through the typed models: skip without pydantic.
pytest.importorskip("pydantic")

PLATE = ngc.PlateTrait(rows=[ngc.RowObj(name="A")], columns=[ngc.ColumnObj(name="1")])
WELL = ngc.WellTrait(row_index=0, column_index=0)


def _names(node: ngc.Node, validators=ngc.ALL_VALIDATORS) -> list[str]:
    return [e.validator for e in node.validate(validators)]


def _wrap(record: NodeRecord, *children: NodeRecord) -> ngc.Node:
    """A tree straight from records, bypassing the handle's guards."""
    tree = NodeTree.of(record)
    for child in children:
        tree, _ = tree.add_child(ROOT, child)
    return ngc.wrap_node(tree, ROOT)


# --------------------------------------------------------------------------- #
# Lenses
# --------------------------------------------------------------------------- #


def test_lenses_compose_on_one_record() -> None:
    record = NodeRecord(
        type="collection",
        id=mk(1),
        traits={
            "plate": PLATE.model_dump(mode="json"),
            "well": WELL.model_dump(mode="json"),
        },
    )
    assert has_trait(record, ngc.PlateTrait) and has_trait(record, "well")
    well = get_trait(record, ngc.WellTrait)
    assert well is not None and well.row_index == 0
    assert get_trait(record, ngc.LabelsTrait) is None
    ms = multiscale(4)
    assert len(read_fields(ms.record, ngc.MultiscaleFields).scales) == 2


# --------------------------------------------------------------------------- #
# The revision fixtures
# --------------------------------------------------------------------------- #


async def test_revision_fixtures_validate(revision_store) -> None:
    view = await aio.open_resolved(f"{DATA}/collection/zarr.json", revision_store)
    errors = view.validate(ngc.ALL_VALIDATORS)
    # the only finding: the http node cannot be resolved from a memory store
    assert [(e.validator, e.node_uuid) for e in errors] == [
        ("external_unresolved", mk(4))
    ]
    opened = await aio.open(f"{DATA}/collection/zarr.json", revision_store)
    assert opened.validate(ngc.ALL_VALIDATORS) == []
    plate = await aio.open_resolved(f"{DATA}/plate/zarr.json", revision_store)
    assert plate.validate(ngc.ALL_VALIDATORS) == []
    standalone = await aio.open_resolved(
        f"{DATA}/standalone/collection.json", revision_store
    )
    assert standalone.validate(ngc.ALL_VALIDATORS) == []
    # strict path conformance is opt-in; the fixture's http node fails it
    assert [e.node_uuid for e in view.validate((ngc.paths_are_core,))] == [mk(4)]


# --------------------------------------------------------------------------- #
# Core validators
# --------------------------------------------------------------------------- #


def test_id_is_uuid() -> None:
    assert _names(collection(1), CORE_VALIDATORS) == []
    assert "id_is_uuid" in _names(_wrap(NodeRecord(type="collection", id="img")))
    bad_scale = multiscale(4).set_field(
        "scales",
        [
            {
                "type": "scale",
                "id": "s0",
                "path": {"type": "zarr", "format": "relative", "href": "./s0"},
            }
        ],
    )
    assert "id_is_uuid" in _names(bad_scale)


def test_known_types() -> None:
    assert "known_types" in _names(ngc.new_node("singlescale", id=mk(1)))
    assert "known_types" in _names(collection(1, traits=[{"type": "fractal:table"}]))
    assert "known_types" not in _names(ngc.new_node("https://x.org/t", id=mk(1)))
    assert "known_types" not in _names(
        collection(1, traits=[{"type": "https://x.org/t"}])
    )


def test_node_fields_allowed() -> None:
    bag = _wrap(
        NodeRecord(type="collection", id=mk(1), fields={"attributes": {"a": 1}})
    )
    (error,) = [
        e
        for e in bag.validate((ngc.validate.__self__ if False else CORE_VALIDATORS))
        if e.validator == "node_fields_allowed"
    ]  # noqa: E501
    assert "attributes" in str(error)
    assert "node_fields_allowed" in _names(multiscale(4).set_field("datasets", []))
    assert "node_fields_allowed" not in _names(multiscale(4))


def test_multiscale_is_complete() -> None:
    assert "multiscale_is_complete" not in _names(multiscale(4))
    assert "multiscale_is_complete" in _names(multiscale(4).set_field("scales", []))
    assert "multiscale_is_complete" in _names(ngc.new_node("multiscale", id=mk(1)))
    # an external entry carries no body, so nothing to check
    assert "multiscale_is_complete" not in _names(collection(1, external(2, "./img")))


def test_no_embedded_multiscale() -> None:
    embedded = _wrap(
        NodeRecord(type="collection", id=mk(1), children=()),
        NodeRecord(type="multiscale", id=mk(2), fields=dict(multiscale(2).fields)),
    )
    assert "no_embedded_multiscale" in _names(embedded)
    assert "no_embedded_multiscale" not in _names(collection(1, external(2, "./img")))


def test_references_resolve() -> None:
    labels = ngc.LabelsTrait(source=[ngc.ReferenceObj(type="multiscale", ref=mk(2))])
    ok = collection(1, external(2, "./img"), external(3, "./lbl").set_trait(labels))
    assert "references_resolve" not in _names(ok)
    dangling = collection(1, external(3, "./lbl").set_trait(labels))
    assert "references_resolve" in _names(dangling)
    wrong_kind = collection(
        1,
        external(2, "./img"),
        external(3, "./lbl").set_trait(
            ngc.LabelsTrait(source=[ngc.ReferenceObj(type="collection", ref=mk(2))])
        ),
    )
    assert "references_resolve" in _names(wrong_kind, CORE_VALIDATORS)
    # declarations nested in traits / fields resolve too
    assert "references_resolve" not in _names(multiscale(4))
    scene = ngc.SceneTrait(
        coordinate_systems=[ngc.CoordinateSystem(id=mk(5), axes=[ngc.Axis(name="x")])],
        coordinate_transformations=[
            ngc.TranslationTransformation(
                translation=[1.0],
                input=ngc.ReferenceObj(
                    type="coordinate_system",
                    ref=mk(0x20),
                    path=ngc.ZarrPath(href="./raw"),
                ),
                output=ngc.ReferenceObj(type="coordinate_system", ref=mk(5)),
            )
        ],
    )
    assert "references_resolve" not in _names(collection(1, traits=[scene]))


async def test_extension_types_declared(revision_store) -> None:
    opened = await aio.open(f"{DATA}/collection/zarr.json", revision_store)
    assert "extension_types_declared" not in _names(opened)
    undeclared = opened.set_trait({"type": "https://other.org/ngff/x", "a": 1})
    assert "extension_types_declared" in _names(undeclared)
    # detached trees have no document, so nothing to check against
    assert "extension_types_declared" not in _names(
        collection(1, traits=[{"type": "https://o.org/x"}])
    )


def _with_manifest(entries: list[dict], store: MemoryStore) -> str:
    """Write a collection using one napari trait under a given manifest; return its URL."""
    url = f"{DATA}/m/zarr.json"
    store._data[url] = {
        "zarr_format": 3,
        "node_type": "group",
        "attributes": {
            "ome": {
                "version": "0.x",
                "extension_manifest": entries,
                "type": "collection",
                "id": mk(0x40),
                "traits": [{"type": "https://napari.org/ngff/rendering", "opacity": 1}],
            }
        },
    }
    return url


def _napari(**extra) -> dict:
    return {
        "id": "https://napari.org/ngff/",
        "version": "1.0",
        "schemas": [{"type": "jsonschema", "url": "https://napari.org/ngff/1.0.json"}],
        **extra,
    }


async def test_manifest_well_formed() -> None:
    store = MemoryStore()
    good = await aio.open(_with_manifest([_napari()], store), store)
    assert "manifest_well_formed" not in _names(good)
    for bad in (
        [_napari(), _napari()],  # duplicate id
        [_napari(schemas=[])],  # no schema
        [_napari(schemas=[{"type": "json_schema", "url": "https://x"}])],  # kind
        [_napari(must_understand="yes")],  # malformed entry
    ):
        node = await aio.open(_with_manifest(bad, store), store)
        assert _names(node, CORE_VALIDATORS).count("manifest_well_formed") == 1, bad
    # a document without a manifest has nothing to check
    assert "manifest_well_formed" not in _names(collection(1))


async def test_must_understand_supported(monkeypatch) -> None:
    from ngio_collections.api._extensions import EXTENSIONS

    monkeypatch.setattr(EXTENSIONS, "_by_id", dict(EXTENSIONS._by_id))
    store = MemoryStore()
    relaxed = await aio.open(_with_manifest([_napari()], store), store)
    assert "must_understand_supported" not in _names(relaxed)
    strict_url = _with_manifest([_napari(must_understand=True)], store)
    strict = await aio.open(strict_url, store)
    assert _names(strict, CORE_VALIDATORS).count("must_understand_supported") == 1
    ngc.register_extension(_napari(must_understand=True))
    assert "must_understand_supported" not in _names(await aio.open(strict_url, store))


def test_paths_are_core_is_opt_in() -> None:
    remote = multiscale(4).set_field(
        "scales",
        [
            {
                "type": "scale",
                "id": scale_id(4, 0),
                "path": {"type": "zarr", "format": "http", "href": "https://h.org/a/0"},
            }
        ],
    )
    assert _names(remote, (ngc.paths_are_core,)) == ["paths_are_core"]
    absolute = collection(
        1, ngc.new_node("multiscale", id=mk(2), path=ngc.DocPath.for_url("/abs/img"))
    )
    assert _names(absolute, (ngc.paths_are_core,)) == ["paths_are_core"]
    assert _names(collection(1, external(2, "./img")), (ngc.paths_are_core,)) == []
    assert ngc.paths_are_core not in ngc.ALL_VALIDATORS


# --------------------------------------------------------------------------- #
# Recommended validators
# --------------------------------------------------------------------------- #


def test_well_under_plate_and_plate_children() -> None:
    plate = collection(0, collection(1, traits=[WELL]), traits=[PLATE])
    assert _names(plate, RECOMMENDED_VALIDATORS) == []
    orphan = collection(0, collection(1, traits=[WELL]))
    assert _names(orphan, RECOMMENDED_VALIDATORS) == ["well_under_plate"]
    bad_child = collection(0, external(2, "./img"), traits=[PLATE])
    assert _names(bad_child, RECOMMENDED_VALIDATORS) == ["plate_children_are_wells"]


def test_trait_applies_to() -> None:
    labels_on_collection = collection(1, traits=[ngc.LabelsTrait()])
    assert _names(labels_on_collection, (ngc.validate and RECOMMENDED_VALIDATORS)) == [
        "trait_applies_to"
    ]
    well_on_multiscale = multiscale(4, traits=[WELL])
    assert "trait_applies_to" in _names(well_on_multiscale, RECOMMENDED_VALIDATORS)
    assert (
        _names(multiscale(4, traits=[ngc.LabelsTrait()]), RECOMMENDED_VALIDATORS) == []
    )


def test_scale_matches_axes() -> None:
    ok = multiscale(4, axis_names=("z", "y", "x"))
    assert "scale_matches_axes" not in _names(ok)
    scales = [s.model_dump(mode="json", exclude_none=True) for s in ok.scales]
    scales[0]["coordinate_transformations"][0]["scale"] = [
        1.0,
        1.0,
    ]  # 2 factors, 3 axes
    bad = ok.set_field("scales", scales)
    errors = bad.validate(RECOMMENDED_VALIDATORS)
    assert [e.validator for e in errors] == ["scale_matches_axes"]
    assert errors[0].node_uuid == mk(4)
    scene = ngc.SceneTrait(
        coordinate_systems=[ngc.CoordinateSystem(id=mk(5), axes=[ngc.Axis(name="x")])],
        coordinate_transformations=[
            ngc.ScaleTransformation(
                scale=[1.0, 2.0],
                input=ngc.ReferenceObj(type="coordinate_system", ref=mk(5)),
                output=ngc.ReferenceObj(type="coordinate_system", ref=mk(5)),
            )
        ],
    )
    assert "scale_matches_axes" in _names(collection(1, traits=[scene]))


def test_labels_source_resolves() -> None:
    img = external(2, "./img")
    good = collection(
        1,
        img,
        external(3, "./lbl").set_trait(
            ngc.LabelsTrait(source=[ngc.ReferenceObj(type="multiscale", ref=mk(2))])
        ),
    )
    assert "labels_source_resolves" not in _names(good)
    wrong_type = collection(
        1,
        img,
        external(3, "./lbl").set_trait(
            ngc.LabelsTrait(source=[ngc.ReferenceObj(type="collection", ref=mk(2))])
        ),
    )
    assert "labels_source_resolves" in _names(wrong_type, RECOMMENDED_VALIDATORS)
    missing = collection(
        1,
        external(3, "./lbl").set_trait(
            ngc.LabelsTrait(source=[ngc.ReferenceObj(type="multiscale", ref=mk(9))])
        ),
    )
    assert "labels_source_resolves" in _names(missing, RECOMMENDED_VALIDATORS)


def test_raise_on_error_reraises_first_failure() -> None:
    orphan = collection(0, collection(1, traits=[WELL]))
    with pytest.raises(ngc.ValidationError) as exc_info:
        orphan.validate(RECOMMENDED_VALIDATORS, raise_on_error=True)
    assert exc_info.value.validator == "well_under_plate"
    assert exc_info.value.node_id == (mk(1),) and exc_info.value.node_uuid == mk(1)
