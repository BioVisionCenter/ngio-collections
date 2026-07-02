# ngio-collections

> [!WARNING]
> This package is a very early OME-Zarr Collections prototype, intended to explore the design space and inform the 
> development of the Fractal platform's collection support.  
> RFC-8 is in flux, and this implementation is not a complete implementation.
> Design and API are expected to change significantly.


## Scope

This package is a concrete implementation of
[RFC-8](https://ngff.openmicroscopy.org/rfc/8/) (OME-Zarr collections).
Its primary goal is to inform the RFC-8 specification process, not production
use. In particular, it aims to make it cheap to test ideas in the collection design
space and to verify that the spec's concepts are concretely implementable.

Specifically, this repository exists to validate:

- that the core RFC-8 concepts can be implemented faithfully and ergonomically;
- the extensibility mechanisms of the spec;
- candidate mechanisms for inlining (resolving cross-document references
  into a single tree);
- that RFC-8 collections remain tractable at scale (target: 1M-node
  collections).

Findings — including deliberate deviations from the spec (see
[Discrepancy with RFC-8](#discrepancy-with-rfc-8)) — are meant to be fed
back into RFC-8 discussions.

### Non-goals

- **Production readiness.** No stability guarantees; design and API change
  without notice.
- **A general OME-Zarr IO library.** Reading and writing image data is
  [ngio](https://github.com/BioVisionCenter/ngio)'s job; this package deals
  only with collection metadata.
- **Remote stores** are out of scope for now (`FsspecStore` is a skeleton).

## Design principles

- **Immutability first.** Nodes are frozen models; every edit returns a new
  tree, never mutates in place. Versions share structure, so holding many
  snapshots stays cheap.
- **Layered architecture.** `models/` is pure data with no IO; the only IO
  surface is the store layer, behind a small protocol.
- **Minimal core dependencies.** The core runs on the stdlib plus Pydantic 
  (planned to be also optional). Performance-critical seams 
  (persistent maps, JSON) are thin interfaces so accelerated backends 
  (`pyrsistent`, `orjson`) can drop in without touching callers.
- **Lazy, explicit validation.** Loading a document never validates it.
  Validators are cheap, composable callables run on demand over a subtree,
  and each check reads only a bounded neighborhood of its node.
- **Scalability by design.** Per-node operations are O(neighborhood), never
  O(tree); the 1M-node target above is the acceptance test for this rule.
- **Async-first.** The async API is the real implementation; the sync API is
  a thin wrapper over it.

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
