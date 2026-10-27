# ngio-collections

Python library for RFC-8 OME-Zarr collection metadata. Async-first; local-only
plus a read-only `HttpStore`; `FsspecStore` is a skeleton.

Targets **RFC-8 revision 1** (the proposal in `rfc8-revision1/`): typed
`traits` (no `attributes`), UUID ids, `{type, ref, path?}` references,
`{type, format, href}` paths, and multiscales that are always their own
document (`coordinate_systems` + `scales`; never embedded, `add()` refuses it).
Manifest entries carry `must_understand`; `register_extension` is what marks an
extension as understood (`must_understand_supported` validator).
Deliberate deviation: `absolute` and `http` paths resolve (spec: `relative`
only); keep it stated in the README and `models/_paths.py`.

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
