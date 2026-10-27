"""An extension node type: a Fractal table whose CSV sits behind a custom path type.

RFC-8 revision 1 identifies extension types by URI and requires every extension
a document uses to be listed in its `extension_manifest`. Here, with the
extensions from `_extensions.py`:

* the Fractal extension is registered, so the manifest is derived on write;
* a `TABLE` node carries a `path` of the custom type `CSV`. The library resolves
  it like any path (`format` + `href`) but never opens the CSV as a node
  document: `path.is_document` is false, the node stays a leaf in a resolved
  view, and that is not a validation finding;
* a typed handle (`register_node_type`) turns the node into `TableNode`; before
  registration the same node reads back as a generic `Node`, fields intact.

Prefixed names (`fractal:table`) are rejected, and an undeclared URI type is a
validation finding, never a write error.

Run with: pixi run python examples/extension_types.py
"""

from pathlib import Path

import ngio_collections as ngc
from _extensions import CSV, TABLE, TableNode, register_examples, register_table_handle
from _ids import uid


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base / "zarr.json")
    base.mkdir(parents=True, exist_ok=True)
    (base / "regionprops.csv").write_text(
        "label,area,mean_intensity\n1,120,0.82\n2,98,0.64\n"
    )

    register_examples()
    try:
        ngc.register_node_type("fractal:table", TableNode)
    except ValueError as error:
        print("prefixed name rejected:", error)

    table = ngc.new_node(
        TABLE,
        id=uid(2),
        name="regionprops",
        path=ngc.DocPath(type=CSV, format="relative", href="./regionprops.csv"),
        fields={"columns": ["label", "area", "mean_intensity"]},
    )
    root = ngc.new_collection(id=uid(1), name="experiment").add(table)
    ngc.create(url, root, overwrite=True)

    opened = ngc.open(url)
    generic = opened.find(uid(2))
    print(f"before handle: {type(generic).__name__}, fields={generic.fields}")
    register_table_handle()
    typed = ngc.open(url).find(uid(2))
    assert isinstance(typed, TableNode)
    print(f"after handle : {type(typed).__name__}, columns={typed.columns}")
    print("csv location :", Path(typed.csv_url()).relative_to(Path(__file__).parent))
    print("manifest     :", [e["id"] for e in opened.extension_manifest])

    # A data path is never fetched: the node stays external in a resolved view.
    view = ngc.open_resolved(url)
    node = view.find(uid(2))
    print(
        "resolved     : external =",
        node.is_external,
        "document =",
        node.path.is_document,
    )
    print("validation   :", view.validate(ngc.ALL_VALIDATORS))
    # An undeclared URI type is a validation finding, never a write error.
    undeclared = opened.set_trait({"type": "https://unknown.example/x", "a": 1})
    print(
        "undeclared   :",
        [e.validator for e in undeclared.validate(ngc.CORE_VALIDATORS)],
    )


if __name__ == "__main__":
    main()
