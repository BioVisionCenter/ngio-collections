"""Validate a collection with cheap, composable validators.

A validator is just a `Callable[[ngc.Node], None]` that `raise`s a
`ngc.ValidationError` when a node fails its check. `ngc.validate(node, validators)`
runs them over a node and its descendants and *collects* the failures (it tags
each with the node and validator name); pass `raise_on_error=True` to re-raise the
first instead. You pass the validators you want explicitly; the example checks:

* a `well` node must be a child of a `plate` node (reads *up*);
* a `scale` transform's factor count must match its coordinate system's axes
  (follows a *reference*).

Validators key off the *capabilities* a node carries (its attributes), so one
node carrying several roles runs every check — composition over inheritance.

Run with: pixi run python examples/validate.py
"""

import ngio_collections as ngc


def main() -> None:
    # Pick the validators to run as a plain tuple of callables.
    validators = (ngc.well_under_plate, ngc.scale_matches_axes)

    plate_attrs = {"plate": {"columns": [{"id": "1"}], "rows": [{"id": "A"}]}}
    well_attrs = {"well": {"column": {"id": "1"}, "row": {"id": "A"}}}

    # A well placed correctly under a plate: no issues.
    plate = ngc.new_node("collection", id="plate", attributes=plate_attrs).add(
        ngc.new_node("collection", id="A1", attributes=well_attrs)
    )
    print("well under plate :", ngc.validate(plate.find("A1"), validators=validators))

    # An orphan well (parent is not a plate): one issue.
    orphan = ngc.new_node("collection", id="root").add(
        ngc.new_node("collection", id="A1", attributes=well_attrs)
    )
    for error in ngc.validate(orphan.find("A1"), validators=validators):
        print("orphan well      :", error.validator, "—", error)

    # A multiscale whose single scale's scale factors do not match its axes.
    bad = ngc.new_node(
        "multiscale", id="img",
        attributes={"coordinateSystems": [{"id": "space", "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}]}]},
    ).add(
        ngc.new_node("singlescale", id="0", attributes={
            "coordinateTransformations": [{"type": "scale", "output": {"id": "space"}, "scale": [2.0, 2.0]}]
        })
    )
    for error in ngc.validate(bad, validators=validators):
        print("scale vs axes    :", error.validator, "—", error)

    # A custom validator is just a function that raises; pass it alongside the
    # example checks. `raise_on_error` turns validate into an assertion.
    def multiscale_has_scales(node: ngc.Node) -> None:
        if node.type == "multiscale" and not node.children():
            raise ngc.ValidationError("a multiscale needs at least one scale")

    try:
        ngc.validate(
            ngc.new_node("multiscale", id="empty"),
            validators=(*validators, multiscale_has_scales),
            raise_on_error=True,
        )
    except ngc.ValidationError as error:
        print("custom (raised)  :", error.validator, "—", error)


if __name__ == "__main__":
    main()
