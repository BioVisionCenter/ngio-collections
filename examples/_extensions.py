"""The extensions the examples use: ids, manifest entries and the table handle.

Three small, illustrative extensions, each exercising one extension point of
RFC-8 revision 1 (§4):

* **Fractal provenance** (`PROVENANCE`): a pure-metadata *trait* recording
  which task produced a node and from which inputs (typed references).
* **Training dataset** (`DATASET`): a structural *trait* on a collection that
  lists its samples as `{image, labels, split}` references to the collection's
  own entries.
* **Fractal table** (`TABLE`): a *node type* whose payload is a CSV file located
  by the custom *path type* `CSV`; the library resolves that path but never
  opens it as a document.

Their ids are raw GitHub URLs into this repository's `examples/schemas/`, where
small JSON Schema files describe each type. They are illustrative and may
change; nothing should depend on them. `validate_all.py` checks the example
documents against the schemas when `jsonschema` is installed.
"""

from __future__ import annotations

from pathlib import Path

import ngio_collections as ngc

BASE = "https://raw.githubusercontent.com/BioVisionCenter/ngio-collections/main/examples/schemas/"
HOMEPAGE = (
    "https://github.com/BioVisionCenter/ngio-collections/tree/main/examples/schemas"
)
SCHEMAS_DIR = Path(__file__).parent / "schemas"

FRACTAL = BASE + "fractal/"
PROVENANCE = FRACTAL + "provenance"
TABLE = FRACTAL + "table"
CSV = FRACTAL + "csv"

TRAINING = BASE + "training/"
DATASET = TRAINING + "dataset"

FRACTAL_ENTRY = {
    "id": FRACTAL,
    "version": "0.1",
    "name": "Fractal",
    "schemas": [
        {"type": "jsonschema", "url": FRACTAL + "provenance.schema.json"},
        {"type": "jsonschema", "url": FRACTAL + "table.schema.json"},
    ],
    "homepage": HOMEPAGE,
}
TRAINING_ENTRY = {
    "id": TRAINING,
    "version": "0.1",
    "name": "Training dataset",
    "schemas": [{"type": "jsonschema", "url": TRAINING + "dataset.schema.json"}],
    "homepage": HOMEPAGE,
}


def register_examples() -> None:
    """Register both extensions so written documents declare them automatically."""
    ngc.register_extension(FRACTAL_ENTRY)
    ngc.register_extension(TRAINING_ENTRY)


class TableNode(ngc.Node):
    """Typed handle for `TABLE` nodes: a CSV located by a `CSV` path."""

    @property
    def columns(self) -> list[str]:
        return list(self.get_field("columns") or [])  # type: ignore[arg-type]

    def csv_url(self) -> str:
        """The absolute location of the CSV (the data path, resolved)."""
        assert self.path is not None, "a table node always carries a CSV path"
        return self.path.resolve(self.document_url)


def register_table_handle() -> None:
    """Make `TABLE` nodes read back as `TableNode`."""
    ngc.register_node_type(TABLE, TableNode)


def schema_file(type_uri: str) -> Path | None:
    """The local schema file for an example type URI, or `None` if it is not one."""
    if not type_uri.startswith(BASE):
        return None
    return SCHEMAS_DIR / (type_uri[len(BASE) :] + ".schema.json")
