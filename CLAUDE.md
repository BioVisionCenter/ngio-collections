# ngio-collections

Python library for RFC-8 OME-Zarr collection metadata. Async-first; local-only
plus a read-only `HttpStore`; `FsspecStore` is a skeleton.

Targets **RFC-8 revision 1** (the proposal in `rfc8-revision1/`): typed
`traits` (no `attributes`), UUID ids, `{type, ref, path?}` references,
`{type, format, href}` paths, and multiscales that are always their own
document (`coordinate_systems` + `scales`; never embedded, `add()` refuses it).
Deliberate deviation: `absolute` and `http` paths resolve (spec: `relative`
only); keep it stated in the README and `models/_paths.py`.

## Commands

```bash
pixi run lint                        # ruff (includes Google-style docstring rules)
pixi run type-check                  # ty
pixi run --environment dev pytest
NGC_OFFLINE=1 pixi run --environment test validate-examples
```

## Rules

- **Immutability:** nodes are frozen records. Every edit goes through
  `model_copy` / `dataclasses.replace` and returns a NEW tree — never mutate
  in place.
- **No IO in `models/`:** `models/` is pure Pydantic. The only IO
  surface is the `store/` layer.
- **Docstrings:** Google-style. Use single backticks for code spans (Markdown).
