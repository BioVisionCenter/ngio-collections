# ngio-collections

> [!WARNING]
> This package is an early OME-Zarr Collections prototype, intended to explore
> the design space and inform the Fractal platform's collection support.
> RFC-8 is in flux; this implementation targets a *proposed revision* and is
> not complete. Design and API are expected to change significantly.

## Spec version targeted: RFC-8 revision 1 (Fall 2026 proposal)

This package implements the **revision-1 proposal** for
[RFC-8](https://ngff.openmicroscopy.org/rfc/8/) (OME-Zarr collections and
extensibility), not the text as published. The proposal lives in the
`rfc8-revision1/` checkout (`rfc8_revision_changes.md`, the three example
documents, and the upstream draft it amends). In short:

- nodes are `{type, id, name?, traits?}`; `attributes` is gone, every piece of
  metadata is a typed **trait** (a keyword for built-in traits, a URI for
  extensions), and extensions are declared per document in `extension_manifest`;
- **ids are required UUIDs** (v7 minted by `new_id()`), names are optional and
  free-form;
- references are typed, `{type, ref, path?}`; paths are `{type, format, href}`;
- a **multiscale is always its own document** (`coordinate_systems` + `scales`
  directly on the node, no `singlescale` nodes), declared in a collection by an
  entry that shares its UUID; traits on that entry override the image's own
  traits per type;
- HCS and labels are deferred to sub-RFCs but kept here as provisional traits
  (`PlateTrait`, `WellTrait`, `AcquisitionTrait`, `LabelsTrait`) following the
  revision's examples.

## Scope

Its primary goal is to inform the RFC-8 specification process, not production
use. In particular, it aims to make it cheap to test ideas in the collection
design space and to verify that the spec's concepts are concretely implementable.

Specifically, this repository exists to validate:

- that the core RFC-8 concepts can be implemented faithfully and ergonomically;
- the extensibility mechanisms of the spec (URI types, traits, manifests);
- path resolution across documents and the trait-combination rules
  (consolidated metadata, the revision's one-request mechanism, is planned);
- that RFC-8 collections remain tractable at scale (target: 1M-node
  collections, which under the revision means ~10⁵ image documents).

Findings, including the deliberate deviations below, are meant to be fed back
into RFC-8 discussions.

### Non-goals

- **Production readiness.** No stability guarantees; design and API change
  without notice.
- **A general OME-Zarr IO library.** Reading and writing image data is
  [ngio](https://github.com/BioVisionCenter/ngio)'s job; this package deals
  only with collection metadata.
- **Remote stores beyond plain HTTP GET** (`FsspecStore` is a skeleton).

## Design principles

- **Immutability first.** Nodes are frozen records; every edit returns a new
  tree, never mutates in place. Versions share structure, so holding many
  snapshots stays cheap.
- **Layered architecture.** `models/` is pure data with no IO; the only IO
  surface is the store layer, behind a small protocol.
- **Minimal core dependencies.** The core runs on the stdlib plus Pydantic.
  Performance-critical seams (persistent maps, JSON) are thin interfaces so
  accelerated backends (`pyrsistent`, `orjson`) can drop in without touching
  callers.
- **Lazy, explicit validation.** Loading a document never validates it.
  Validators are cheap, composable callables run on demand over a subtree, and
  each check reads only a bounded neighborhood of its node. Three bundles ship:
  `CORE_VALIDATORS` (the revision's structural rules), `RECOMMENDED_VALIDATORS`
  (the provisional traits) and `ALL_VALIDATORS`.
- **Scalability by design.** Per-node operations are O(neighborhood), never
  O(tree); the 1M-node target above is the acceptance test for this rule.
- **Async-first.** The async API is the real implementation; the sync API is
  a thin wrapper over it.

## Getting started

Usage examples are in the [examples/](examples/) directory; each writes its
documents under `examples/data/`. The simplest way to run them is with
[pixi](https://pixi.prefix.dev/latest/):

```bash
pixi run python examples/create_collection.py
```

The pattern every example follows: create each image as its own document
(`create` returns its declaring entry), link the entries into a collection with
`add_external`, then `open` to edit one document or `open_resolved` to read the
whole tree.

## Public surface

Everything supported for downstream use is importable from the top level:

```python
import ngio_collections as ngc
```

The subpackages (`ngio_collections.graph`, `resolve`, `io`, `models`,
`validate`, `api`) are internal layout and may be reorganized without notice.
If something you legitimately need is not re-exported at the top level, that is
a bug worth reporting rather than a reason to deep-import.

## Deviations and experimental extensions

- **`absolute` and `http` paths are resolved.** The revision makes only
  `relative` a core format and defers the others to a sub-RFC. This package
  resolves all three (a read-only `HttpStore` behind a scheme-routed default
  store), so a collection or a multiscale document can point at existing local
  or remote data, remote arrays as scales included, without bundling it. Strict
  conformance is opt-in: `open_resolved(..., formats=CORE_FORMATS)` and the
  `paths_are_core` validator.
- **Provisional recommended traits.** HCS and labels are deferred to sub-RFCs;
  the trait models here follow the revision's examples and may change.
- **`json` path type kept.** The revision only shows `type: "zarr"`; the
  upstream draft defines `json` too, and standalone `collection.json` documents
  rely on it.
- **Multiscales are never embedded, even in memory.** `add()` refuses a
  multiscale without a `path`; the way to link an image is `create` then
  `add_external`.

## Feedback to the RFC

Points this implementation surfaced, for the revision's authors:

- `traits` as a *list* keyed implicitly by `type` is harder to use than a dict
  keyed by type (the upstream draft's shape): same-type duplicates are
  unspecified and the §3.1 override rule is keyed by type anyway.
- Without any free-form field, scratch metadata needs a URI trait and a
  manifest entry; one built-in opaque trait would absorb that.
- "No conflict rules needed" (§8.1) is only half true: the trait-combination
  rule still exists, and `name` precedence is unspecified (here the declaring
  entry wins).
- `input: {type: scale, ref: <self>}` on every scale transform is redundant.
- §12's trait rules (`applies_to`, `excludes`, child constraints) have no
  machine-readable home; they live in validator code here.
- `http` for *scale* paths is low-risk (readers already fetch chunks by URL)
  and is what makes collections over existing remote data possible.
