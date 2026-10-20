"""pydantic is optional: the core runs without it, the typed tier is gated.

Runs the checks in a subprocess with `pydantic` blocked from `sys.modules`, so
the boundary is exercised in every environment, including the ones where
pydantic is installed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

SCRIPT = textwrap.dedent(
    """
    import sys
    sys.modules["pydantic"] = None  # block the import even if installed
    sys.modules["pydantic_core"] = None

    import ngio_collections as ngc
    from ngio_collections.validate import known_types, multiscale_is_complete, references_resolve
    assert "pydantic" not in sys.modules or sys.modules["pydantic"] is None

    def mk(n):
        return f"0192f3a0-7c1e-7b00-9c22-{n:012x}"

    # -- construction, write, read, resolve: all on raw dicts -----------------
    store = ngc.MemoryStore()
    cs, sc = mk(0x10), mk(0x20)
    image = ngc.new_multiscale(
        id=mk(1),
        name="img",
        coordinate_systems=[{"type": "coordinate_system", "id": cs,
                             "axes": [{"name": "y"}, {"name": "x"}]}],
        scales=[{"type": "scale", "id": sc, "path": ngc.ZarrPath(href="./0").to_dict(),
                 "coordinate_transformations": [
                     {"type": "scale", "scale": [1.0, 1.0],
                      "input": {"type": "scale", "ref": sc},
                      "output": {"type": "coordinate_system", "ref": cs}}]}],
        traits=[{"type": "https://example.org/ngff/render", "contrast": [0, 1]}],
    )
    stub = ngc.create("/data/img.zarr", image, store=store)
    plate = ngc.new_collection(
        id=mk(2), name="plate",
        traits=[{"type": "well", "row_index": 0, "column_index": 1}],
        children=[stub],
    )
    ngc.create("/data/plate.zarr", plate, store=store)

    opened = ngc.open("/data/plate.zarr", store=store)
    assert opened.traits["well"]["column_index"] == 1
    assert opened.has_trait("well") and "well" in opened
    ngc.save(opened.rename("renamed"), store=store)
    view = ngc.open_resolved("/data/plate.zarr", store=store)
    child = view.children()[0]
    assert child.type == "multiscale" and child.fields["scales"][0]["id"] == sc
    edge = child.record.edge  # the declaring entry a resolved node collapsed
    assert isinstance(edge.path, ngc.DocPath) and edge.path.href == "../img.zarr"
    entry = opened.children()[0]
    assert isinstance(entry.path, ngc.DocPath) and entry.is_external
    ref = child.ref()
    assert isinstance(ref, ngc.ReferenceObj) and ref.to_dict()["ref"] == mk(1)
    assert ngc.resolve_ref(view, child.ref_local()).id == mk(1)

    # -- the structural validators run; the schema-shape ones are gated -------
    structural = [v for v in ngc.CORE_VALIDATORS if v is not multiscale_is_complete]
    errors = view.validate(structural)
    # the only finding: the URI trait is not declared in a manifest
    assert [e.validator for e in errors] == ["extension_types_declared"], errors
    assert view.validate([known_types, references_resolve]) == []
    try:
        view.validate([multiscale_is_complete])
    except ImportError as exc:
        assert "ngio-collections[validate]" in str(exc), exc
    else:
        raise AssertionError("multiscale_is_complete ran without pydantic")

    # -- the typed tier raises a clear, actionable ImportError ----------------
    for attr in ("WellTrait", "Scale", "CoordinateSystem", "BaseObj", "TraitType"):
        try:
            getattr(ngc, attr)
        except ImportError as exc:
            assert "ngio-collections[validate]" in str(exc), exc
        else:
            raise AssertionError(f"{attr} resolved without pydantic")
    try:
        child.scales
    except ImportError as exc:
        assert "MultiscaleNode.scales" in str(exc), exc
    else:
        raise AssertionError("MultiscaleNode.scales ran without pydantic")
    assert not hasattr(ngc, "NotAThing")
    print("CORE-OK")
    """
)


def test_core_runs_without_pydantic() -> None:
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "CORE-OK" in result.stdout
