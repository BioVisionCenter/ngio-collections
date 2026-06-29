# ngio-collections

Python library for RFC-8 OME-Zarr collection metadata. Async-first; local-only
for now (`LocalStore`); `FsspecStore` is a skeleton.

## Commands

```bash
pixi run lint                        # ruff (includes Google-style docstring rules)
pixi run type-check                  # ty
pixi run --environment dev pytest
```

## Rules

- **Immutability:** nodes are frozen Pydantic models. Every edit goes through
  `model_copy` and returns a NEW tree — never mutate in place.
- **No IO in `models/`:** `models/_base.py` is pure Pydantic. The only IO
  surface is the `store/` layer.
- **Docstrings:** Google-style. Use single backticks for code spans (Markdown).
