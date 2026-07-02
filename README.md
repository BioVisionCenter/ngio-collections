# ngio-collections

> [!WARNING]
> This package is a very early OME-Zarr Collections prototype, intended to explore the design space and inform the 
> development of the Fractal platform's collection support.  
> RFC-8 is in flux, and this implementation is not a complete implementation.
> Design and API are expected to change significantly.


## Getting started
This repository is a early prototype. Some usage examples are available in the [examples/](examples/) directory.
The simplest way to run them is with [pixi](https://pixi.prefix.dev/latest/).

```bash
pixi run python examples/01_sync_api.py
```

## Public surface

Everything supported for downstream use is importable from the top level:

```python
import ngio_collections as ngc
```

The subpackages (`ngio_collections.graph`, `resolve`, `io`, `models`,
`validate`, `api`) are internal layout and may be reorganized without notice —
import from them at your own risk. If something you legitimately need is not
re-exported at the top level, that is a bug worth reporting rather than a
reason to deep-import.

## Discrepancy with RFC-8

- **`id` is required.** RFC-8 makes `id` optional on every node; this package
  requires it on all nodes. Ids are the primary handle this package uses for
  addressing and merging nodes (`find()`, `Resolver.inline()`,
  `ReferenceObj`).
- **`name` is optional**, while RFC-8 makes it required. Moreover, this package 
  does not enforce uniqueness of names within a collection, while RFC-8 does.