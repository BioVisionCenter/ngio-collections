"""Validate a collection with the scoped, composable validators.

`node.validate()` runs every applicable validator over a bounded neighbourhood;
`validate_tree(tree)` runs them across the whole collection. The built-ins:

* a `well` node must be a child of a `plate` node (reads *up*);
* a `scale` transform's factor count must match its coordinate system's axes
  (follows a *reference*).

Validators key off the *capabilities* a node carries (its attributes), so one
node carrying several roles runs every applicable validator — composition over
inheritance.

Run with: pixi run python examples/validate.py
"""

import ngio_collections as ngc


def main() -> None:
    plate_attrs = {"plate": {"columns": [{"id": "1"}], "rows": [{"id": "A"}]}}
    well_attrs = {"well": {"column": {"id": "1"}, "row": {"id": "A"}}}

    # A well placed correctly under a plate: no issues.
    plate = ngc.new_node("collection", id="plate", attributes=plate_attrs).add(
        ngc.new_node("collection", id="A1", attributes=well_attrs)
    )
    print("well under plate :", plate.find("A1").validate())

    # An orphan well (parent is not a plate): one issue.
    orphan = ngc.new_node("collection", id="root").add(
        ngc.new_node("collection", id="A1", attributes=well_attrs)
    )
    for issue in orphan.find("A1").validate():
        print("orphan well      :", issue.validator, "—", issue.message)

    # A multiscale whose single scale's scale factors do not match its axes.
    bad = ngc.new_node(
        "multiscale", id="img",
        attributes={"coordinateSystems": [{"id": "space", "axes": [{"name": "z"}, {"name": "y"}, {"name": "x"}]}]},
    ).add(
        ngc.new_node("singlescale", id="0", attributes={
            "coordinateTransformations": [{"type": "scale", "output": {"id": "space"}, "scale": [2.0, 2.0]}]
        })
    )
    for issue in ngc.validate_tree(bad.tree):
        print("scale vs axes    :", issue.validator, "—", issue.message)


if __name__ == "__main__":
    main()
