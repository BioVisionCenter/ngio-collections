# ngio-collections

Python library for RFC-8 OME-Zarr collection metadata. Async-first; local-only
plus a read-only `HttpStore`; `FsspecStore` is a skeleton.

Targets **RFC-8 revision 2**: `upstream/rfc8.md` of
`lorenzocerrone/ngff-rfc8-revisions` at `a19d460` ("Remove singlescale node").
Typed `traits` (no `attributes`), `{type, ref, path?}` references and
`{type, format, href}` paths. The upstream text is the reference; the
`rfc8_model` pydantic draft (`../ngff-rfc8-models`) is behind it and documents
do not round-trip with it for now.
- envelope: the `ome` payload is the root node plus the document keys
  `version` (`"0.9dev4"`) and `extensionManifest?`; there is no `root` key
  (`resolve/_document.py` is the one place that knows this);
- wire keys follow upstream spelling (`coordinateSystems`,
  `coordinateTransformations`, `extensionManifest`, `mustUnderstand`); Python
  attributes and keywords stay snake_case, mapped with `wire(...)`
  (`models/_config.py`). The provisional HCS / labels trait keys stay
  snake_case;
- ids are free-form strings matching `ID_PATTERN` (`^[a-zA-Z0-9_.-]+$`,
  `models/_ids.py`); `new_id()` mints a UUIDv7 as the default;
- a multiscale is a leaf node with `coordinateSystems` +
  `coordinateTransformations` + `data`, all required (`models/_multiscale.py`):
  each entry of `data` is `{type: "array", name?, path,
  downsamplingTransformations?}`. Arrays have no `id` and cannot be referenced
  (settled in the review of `ome/ngff-rfc8-revisions#43`). Only the first
  (highest-resolution) array may omit `downsamplingTransformations`, which is
  one `scale` optionally followed by one `translation`. A multiscale
  transformation's `input` is the multiscale itself, written as the typed
  reference `{type: "multiscale", ref: <own id>}` (upstream examples use a
  bare id string; bare strings are not read), and its `output` is one of the
  node's coordinate systems (`multiscale_transformations_wellformed`).
Manifest entries carry `mustUnderstand`; `register_extension` is what marks an
extension as understood (`must_understand_supported` validator).
In a collection a multiscale is inlined (`add`) or an entry with a `path`
(`create` then `add_external`); both are valid upstream. An entry's id need not
match its target root's: the resolved node keeps the entry's id and
`edge.target_id` holds the other (`graph/_record.py::local_ids`). Relative
paths are rebased when a node is written into another document
(`DocPath.rebase`). Ids are unique per document (`ids_unique_in_document`), a
nested node may repeat the root's `version`, and `create` / `save` /
`externalize` also list the extensions of the referenced documents in the
manifest (`aggregate_manifest`).
Deliberate deviation: `absolute` and `http` paths resolve (spec: `relative`
only); keep it stated in the README and `models/_paths.py`. `DocPath.type`
also admits extension URIs as *data* paths (`format` optional, extension
fields kept in `extra`, never fetched as a document; `is_document` is false). The example extensions and their JSON
Schemas live in `examples/_extensions.py` and `examples/schemas/`; the library
never evaluates schemas.

## Commands

```bash
pixi run lint                        # ruff (includes Google-style docstring rules)
pixi run type-check                  # ty
pixi run --environment dev pytest
pixi run --environment core pytest   # without pydantic
NGC_OFFLINE=1 pixi run --environment test validate-examples
```

## Rules

- **Immutability:** nodes are frozen records. Every edit goes through
  `model_copy` / `dataclasses.replace` and returns a NEW tree — never mutate
  in place.
- **No IO in `models/`:** `models/` is pure data. The only IO
  surface is the `store/` layer.
- **pydantic is optional** (the `validate` extra). Only `models/_config.py`,
  `models/_multiscale.py`, `models/_transformation.py` and `models/traits/`
  may import it at module level. Everything else is stdlib: `DocPath`,
  `ReferenceObj` and the manifest entries are dataclasses with
  `from_dict` / `to_dict`; code that needs a typed model imports it lazily
  after `_optional.require_pydantic(...)`. `tests/test_optional_pydantic.py`
  and the `core` pixi environment guard the boundary.
- **Docstrings:** Google-style. Use single backticks for code spans (Markdown).
