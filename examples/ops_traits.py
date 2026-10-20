"""Trait operations: typed lenses, upsert by type, drop.

`traits` is an ordered mapping keyed by trait `type`. `node[Trait]` validates a
trait through its model, `set_trait` upserts (a model or a mapping carrying
`type`), `drop_traits` removes by type or model class.

Run with: pixi run python examples/ops_traits.py
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
    print("membership  :", ngc.PlateTrait in node, "plate" in node, "well" in node)

    # Upsert: a mapping with `type` (any extension trait) and a model.
    node = node.set_traits(
        {"type": "https://napari.org/ngff/rendering", "contrast_limits": [0, 1500]},
        ngc.WellTrait(row_index=0, column_index=0),
    )
    print("after set   :", list(node.traits))
    node = node.set_trait(
        {"type": "https://napari.org/ngff/rendering", "contrast_limits": [0, 100]}
    )
    print("replaced    :", node.traits["https://napari.org/ngff/rendering"])
    node = node.drop_traits(ngc.WellTrait, "https://napari.org/ngff/rendering")
    print("after drop  :", list(node.traits))
    print("raw mapping :", node.traits["plate"])


if __name__ == "__main__":
    main()
