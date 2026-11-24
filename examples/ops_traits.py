"""Trait operations: typed lenses, upsert by type, drop.

`traits` is an ordered mapping keyed by trait `type`. `node[Trait]` validates a
trait through its model, `set_trait` upserts (a model or a mapping carrying
`type`), `drop_traits` removes by type or model class.

Run with: pixi run --environment dev python examples/ops_traits.py
"""

import ngio_collections as ngc
from _ids import uid


def main() -> None:
    plate = ngc.PlateTrait(
        rows=[ngc.RowObj(name="A")], columns=[ngc.ColumnObj(name="1")]
    )
    node = ngc.new_collection(id=uid(1), name="plate", traits=[plate])

    print(
        "typed read  :",
        node[ngc.PlateTrait].rows[0].name,
        "| has well:",
        node.has_trait(ngc.WellTrait),
    )
    print(
        "membership  :",
        f"PlateTrait={ngc.PlateTrait in node}",
        f"'plate'={'plate' in node}",
        f"'well'={'well' in node}",
    )

    # Upsert: a mapping carrying `type` (extension traits always look like this)
    # and a model are interchangeable; a later set of the same type replaces.
    node = node.set_trait({"type": "well", "row_index": 0, "column_index": 0})
    print(
        "after set   :", list(node.traits), "column:", node[ngc.WellTrait].column_index
    )
    node = node.set_trait(ngc.WellTrait(row_index=0, column_index=1))
    print("replaced    :", node.traits["well"])
    node = node.drop_traits(ngc.WellTrait)
    print("after drop  :", list(node.traits))
    print("raw mapping :", node.traits["plate"])


if __name__ == "__main__":
    main()
