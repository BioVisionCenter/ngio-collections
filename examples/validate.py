"""Validate collections with cheap, composable validators.

A validator is a `Callable[[ngc.Node], None]` that raises `ngc.ValidationError`
when a node fails its check. `ngc.validate(node, validators)` runs them over a
node and its descendants and collects the failures. Three bundles ship:

* `CORE_VALIDATORS`: the structural rules of RFC-8 revision 2 (valid ids, known
  types, no `attributes` bag, complete multiscales, no embedded multiscale,
  same-document references resolve, extension types declared, among others);
* `RECOMMENDED_VALIDATORS`: the provisional trait rules (well under plate,
  `applies_to`, scale factors vs axes, labels sources, among others);
* `ALL_VALIDATORS`: both. `paths_are_core` is opt-in (this package resolves
  `absolute` / `http` paths on purpose).

Run with: pixi run --environment dev python examples/validate.py
"""

import ngio_collections as ngc
from _ids import uid
from _images import image


def report(label: str, node: ngc.Node, validators=ngc.ALL_VALIDATORS) -> None:
    errors = ngc.validate(node, validators)
    print(f"{label:<22}", "ok" if not errors else "")
    for error in errors:
        print(f"{'':<22} {error.validator}: {error}")


def main() -> None:
    well = ngc.WellTrait(row_index=0, column_index=0)
    plate = ngc.PlateTrait(
        rows=[ngc.RowObj(name="A")], columns=[ngc.ColumnObj(name="1")]
    )

    report(
        "well under plate",
        ngc.new_collection(
            id=uid(1),
            traits=[plate],
            children=[ngc.new_collection(id=uid(2), traits=[well])],
        ),
    )
    report(
        "orphan well",
        ngc.new_collection(
            id=uid(1), children=[ngc.new_collection(id=uid(2), traits=[well])]
        ),
    )
    report(
        "labels on collection",
        ngc.new_collection(id=uid(1), traits=[ngc.LabelsTrait()]),
    )
    report("unknown node type", ngc.new_node("singlescale", id=uid(1)))
    report(  # a prefixed name is not a URI, so it is not an extension type either
        "unknown trait type",
        ngc.new_collection(id=uid(1), traits=[{"type": "fractal:table"}]),
    )

    good = image(3, axes=("z", "y", "x"), levels=2)
    report("complete multiscale", good)
    bad_arrays = [a.model_dump(mode="json", exclude_none=True) for a in good.arrays]
    two_factors = [2.0, 2.0]  # but the multiscale has 3 axes
    bad_arrays[1]["downsamplingTransformations"][0]["scale"] = two_factors
    report("downsampling vs axes", good.set_field("data", bad_arrays))
    report("empty multiscale", good.set_field("data", []))
    report(  # the typed models reject a bad id early; a raw trait reaches the validator
        "invalid id",
        ngc.new_collection(id=uid(1)).set_trait(
            {
                "type": "plate",
                "rows": [],
                "columns": [],
                "acquisitions": [{"type": "acquisition", "id": "t 0"}],  # no spaces
            }
        ),
    )
    report(
        "dangling reference",
        good.set_trait(
            ngc.LabelsTrait(source=[ngc.ReferenceObj(type="multiscale", ref=uid(9))])
        ),
    )
    report(
        "remote array (strict)",
        good.set_field(
            "data",
            [
                {
                    "type": "array",
                    "path": {
                        "type": "zarr",
                        "format": "http",
                        "href": "https://h.org/img/0",
                    },
                }
            ],
        ),
        (ngc.paths_are_core,),
    )

    # A custom validator is just a function that raises; `raise_on_error` turns
    # `validate` into an assertion.
    def has_a_name(node: ngc.Node) -> None:
        if node.name is None:
            raise ngc.ValidationError("every node in this project is named")

    try:
        ngc.validate(
            ngc.new_collection(id=uid(1)),
            validators=(*ngc.CORE_VALIDATORS, has_a_name),
            raise_on_error=True,
        )
    except ngc.ValidationError as error:
        print(
            f"{'custom (raised)':<22} {error.validator}: {error} (node ...{error.declared_id[-4:]})"
        )


if __name__ == "__main__":
    main()
