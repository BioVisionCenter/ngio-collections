"""Extension node types and traits are URIs declared in `extension_manifest`.

RFC-8 revision 1 replaces prefixed names (`fractal:table`) with URIs derived
from an extension id, and requires every extension a document uses to be
listed in that document's `extension_manifest`. Here a third-party package:

* registers its extension (`register_extension`) so manifests are derived;
* registers a typed handle for its node type (`register_node_type`);
* writes a collection holding one of its nodes, with its own fields.

A second extension is declared but has no typed handle: its node reads back
as a generic `Node` and its fields / traits round-trip untouched.

Run with: pixi run python examples/extension_types.py
"""

from pathlib import Path

import ngio_collections as ngc
from _ids import uid

TABLE = "https://fractal.example/ngff/table"


class TableNode(ngc.Node):
    """Handle for `https://fractal.example/ngff/table` nodes."""

    @property
    def columns(self) -> list[str]:
        return list(self.get_field("columns") or [])  # type: ignore[arg-type]


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base / "zarr.json")

    ngc.register_extension(
        {
            "id": "https://fractal.example/ngff/",
            "version": "0.1",
            "schemas": [
                {
                    "type": "json_schema",
                    "url": "https://fractal.example/ngff/0.1/schema.json",
                }
            ],
        }
    )
    ngc.register_extension({"id": "https://mobie.example/ngff/", "version": "2.0"})
    ngc.register_node_type(TABLE, TableNode)
    try:
        ngc.register_node_type("fractal:table", TableNode)
    except ValueError as error:
        print("prefixed name rejected:", error)

    root = ngc.new_collection(id=uid(1), name="experiment").add(
        ngc.new_node(
            TABLE, id=uid(2), name="regionprops", fields={"columns": ["area", "mean"]}
        ),
        ngc.new_node(
            "https://mobie.example/ngff/view",
            id=uid(3),
            name="view",
            traits=[{"type": "https://mobie.example/ngff/settings", "opacity": 0.5}],
        ),
    )
    ngc.create(url, root, overwrite=True)

    opened = ngc.open(url)
    table, view = opened.find(uid(2)), opened.find(uid(3))
    print(f"registered  : {type(table).__name__}, columns={table.columns}")
    print(
        f"unregistered: {type(view).__name__}, type={view.type!r}, traits={list(view.traits)}"
    )
    print("manifest    :", [e["id"] for e in opened.extension_manifest])
    print("validation  :", opened.validate(ngc.CORE_VALIDATORS))
    # An undeclared URI type is a validation finding, never a write error.
    undeclared = opened.set_trait({"type": "https://unknown.example/x", "a": 1})
    print(
        "undeclared  :", [e.validator for e in undeclared.validate(ngc.CORE_VALIDATORS)]
    )


if __name__ == "__main__":
    main()
