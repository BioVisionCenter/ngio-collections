# Examples

Each script is self-contained (it writes its own fixture data under
`examples/data/`, which is gitignored) and runnable with:

```bash
pixi run -e dev python examples/<script>.py
```

| Script | Covers |
| --- | --- |
| `01_sync_api.py` | Quickstart: the sync API (`write_multiscale` / `write_collection` / `open_collection` / `open_multiscale`), reference stubs, `walk()` / `find()` navigation. |
| `02_models_and_documents.py` | The pure model layer (no IO): node construction and validation, the typed `attrs` view, `MetadataDocument` serialize / re-parse round-trip, graceful degradation of unknown types. |
| `03_resolver_read_write.py` | The async core: one document per externalized node, lazy `open()`, on-demand `resolve()`, `resolve_tree()` cache warming, `children()`, document-granular `save()`. |
| `04_inline_and_merge.py` | `Resolver.inline()` and the stub-wins attribute merge (DESIGN.md §5); annotating a read-only target via its stub. |
| `05_custom_node_types.py` | Registering custom node types in a `NodeRegistry`; unregistered types degrade to opaque `BaseNode`s. |
| `06_hcs_plate_single_collection.py` | An HCS plate as one collection document — plate and wells inline, only the multiscale images externalized into subdirectories. |
| `07_hcs_plate_nested.py` | An HCS plate fully externalized, one document per node: plate at the top, each well at `{row}/{col}`, each image at `{row}/{col}/{image}`. |
