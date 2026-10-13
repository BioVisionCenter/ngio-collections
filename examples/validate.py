"""Validate a collection with cheap, composable validators.

A validator is just a `Callable[[ngc.Node], None]` that `raise`s a
`ngc.ValidationError` when a node fails its check. `ngc.validate(node, validators)`
runs them over a node and its descendants and *collects* the failures (it tags
each with the node and validator name); pass `raise_on_error=True` to re-raise the
first instead. You pass the validators you want explicitly. The built-in ones:

* `id_is_uuid`: every declared `id` is a canonical lowercase UUID;
* `unique_ids` (tree-level, called directly): no id is declared twice;
* `well_under_plate` / `scale_matches_axes`: capability checks on the
  pre-proposal camelCase attribute keys (stale until traits are ported).

Validators key off the *capabilities* a node carries (its attributes), so one
node carrying several roles runs every check — composition over inheritance.

Run with: pixi run python examples/validate.py
"""

import ngio_collections as ngc

PLATE = "0192f3a0-e000-7000-8000-000000000071"
A1 = "0192f3a0-e000-7000-8000-000000000072"
COLUMN = "0192f3a0-e000-7000-8000-000000000073"
ROW = "0192f3a0-e000-7000-8000-000000000074"
IMG = "0192f3a0-e000-7000-8000-000000000075"
SPACE = "0192f3a0-e000-7000-8000-000000000076"


def main() -> None:
    # Pick the validators to run as a plain tuple of callables.
    validators = (ngc.id_is_uuid, ngc.well_under_plate, ngc.scale_matches_axes)

    plate_attrs = {"plate": {"columns": [{"id": "1"}], "rows": [{"id": "A"}]}}
    well_attrs = {
        "well": {
            "column": {"type": "column", "ref": COLUMN},
            "row": {"type": "row", "ref": ROW},
        }
    }

    # A well placed correctly under a plate: no issues.
    plate = ngc.new_node("collection", id=PLATE, name="plate", attributes=plate_attrs).add(
        ngc.new_node("collection", id=A1, name="A1", attributes=well_attrs)
    )
    print("well under plate :", ngc.validate(plate.find(A1), validators=validators))

    # An orphan well (parent is not a plate): one issue.
    orphan = ngc.new_node("collection", name="root").add(
        ngc.new_node("collection", id=A1, name="A1", attributes=well_attrs)
    )
    for error in ngc.validate(orphan.find(A1), validators=validators):
        print("orphan well      :", error.validator, "—", error)

    # A pre-proposal free-form id is flagged by `id_is_uuid`.
    legacy = ngc.new_node("multiscale", id="image", name="image")
    for error in ngc.validate(legacy, validators=validators):
        print("legacy id        :", error.validator, "—", error)

    # The same UUID declared twice: a tree-level check, called directly.
    twice = ngc.new_node("collection", name="root").add(
        ngc.new_node("multiscale", id=IMG, name="a"),
        ngc.new_node("multiscale", id=IMG, name="b"),
    )
    for error in ngc.unique_ids(twice):
        print("duplicate id     :", error.validator, "—", error)

    # A multiscale whose scale factors do not match its coordinate system's axes
    # (pre-proposal camelCase keys; the stale validator still reads these).
    bad = ngc.new_node(
        "multiscale",
        id=IMG,
        name="img",
        attributes={
            "coordinateSystems": [
                {"id": SPACE, "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}]}
            ],
            "coordinateTransformations": [
                {
                    "type": "scale",
                    "output": {"type": "coordinate_system", "ref": SPACE},
                    "scale": [2.0, 2.0],
                }
            ],
        },
    )
    for error in ngc.validate(bad, validators=validators):
        print("scale vs axes    :", error.validator, "—", error)

    # A custom validator is just a function that raises; pass it alongside the
    # built-in checks. `raise_on_error` turns validate into an assertion.
    def multiscale_has_scales(node: ngc.Node) -> None:
        if node.type == "multiscale" and not node.attributes.get("scales"):
            raise ngc.ValidationError("a multiscale needs at least one scale")

    try:
        ngc.validate(
            ngc.new_node("multiscale", name="empty"),
            validators=(*validators, multiscale_has_scales),
            raise_on_error=True,
        )
    except ngc.ValidationError as error:
        print("custom (raised)  :", error.validator, "—", error)


if __name__ == "__main__":
    main()
