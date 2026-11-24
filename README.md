# ngio-collections

> [!WARNING]
> This package is an early OME-Zarr Collections prototype, intended to explore
> the design space and inform the Fractal platform's collection support.
> RFC-8 is in flux; this implementation targets a *proposed revision* and is
> not complete. Design and API are expected to change significantly.

## Spec version targeted: RFC-8 revision 2 (Fall 2026 proposal)

This package implements the **revision-2 proposal** for
[RFC-8](https://ngff.openmicroscopy.org/rfc/8/) (OME-Zarr collections and
extensibility), not the text as published. The reference is `upstream/rfc8.md`
in [ngff-rfc8-revisions](https://github.com/lorenzocerrone/ngff-rfc8-revisions) at commit
`a19d460` ("Remove singlescale node"). In short:

- the `ome` payload is the root node itself next to the document keys:
  `{version: "0.9dev4", extensionManifest?, type, id, ...}`;
- nodes are `{type, id, name?, traits?}`; `attributes` is gone, every piece of
  metadata is a typed **trait** (a keyword for built-in traits, a URI for
  extensions), and extensions are declared per document in `extensionManifest`
  as `{id, version, schemas, name?, description?, mustUnderstand?, homepage?}`
  with `schemas` a non-empty list of `{type: jsonschema | linkml, url}`;
- **ids are required strings** matching `^[a-zA-Z0-9_.-]+$`; `new_id()` mints a
  UUIDv7 when the caller does not pick one; names are optional and free-form;
- references are typed, `{type, ref, path?}`; paths are `{type, format, href}`;
- a **multiscale** is a leaf node with `coordinateSystems`,
  `coordinateTransformations` and `data`, one
  `{type: "array", name?, path, downsamplingTransformations?}` object per
  resolution level, finest first. Array objects are not nodes and have no
  `id`. Every array but the first carries `downsamplingTransformations` (a
  `scale`, optionally followed by a `translation`) relative to the first. The
  node-level transformations map the array space of the first array into one
  of the node's coordinate systems;
- in a collection a multiscale is either **inlined** (its `data` written in
  place) or an **entry with a `path`** to the image's own document. Traits on
  such an entry override the image's own traits per type. The entry and the
  document root need not share an id;
- ids are unique within a document, and a document's manifest also lists the
  extensions used in the documents it points at;
- wire keys follow the revision's spelling, camelCase and snake_case mixed
  (`coordinateSystems`, `mustUnderstand`, `coordinate_system`); the Python
  attributes stay snake_case (`coordinate_systems`, `arrays`,
  `must_understand`);
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
- **Zero core dependencies.** The core (open / edit / save / resolve, the raw
  traits and fields, the structural validators) runs on the stdlib alone.
  Pydantic is the optional `validate` extra: it powers the typed value models
  (`WellTrait`, `MultiscaleArray`, …), the `node[Trait]` lenses, `MultiscaleNode.arrays`
  and the schema-shape validators; without it those raise an `ImportError`
  naming the extra. Performance-critical seams (persistent maps, JSON) are thin
  interfaces so accelerated backends (`pyrsistent`, `orjson`) can drop in
  without touching callers.
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

Install the core, or add the `validate` extra for the typed value models and
the full validator bundles:

```bash
pip install ngio-collections              # stdlib only
pip install 'ngio-collections[validate]'  # + pydantic: WellTrait, Scale, node[Trait], ...
```

Usage examples are in the [examples/](examples/) directory; each writes its
documents under `examples/data/`. The simplest way to run them is with
[pixi](https://pixi.prefix.dev/latest/):

```bash
pixi run --environment dev python examples/create_collection.py
```

The pattern most examples follow: create each image as its own document
(`create` returns its declaring entry), link the entries into a collection with
`add_external`, then `open` to edit one document or `open_resolved` to read the
whole tree. An image can also be inlined in a collection with `add`. Each
script has one job:

- `create_collection.py`: the revision's `collection.json` (two images, labels,
  scene), and the one place a multiscale is assembled by hand; the others take
  an image from `_images.py`.
- `open_resolved_inspect.py`: `open` vs `open_resolved`, portable references,
  the read-only view.
- `open_edit_save.py`: edit names and fields in two documents, one `save` each,
  then `delete` with cascade.
- `trait_override.py`: traits on the entry vs. in the image document, and
  which wins on `open_resolved`.
- `nested_collections.py`: embedded vs. external nodes (a nested collection, an
  inlined image), `externalize`, `open_ref`.
- `hcs_plate.py`: the provisional plate / well / acquisition traits.
- `remote_collection.py`: the `http` path deviation and strict mode.
- `v05_plate_convert.py`: an IDR v0.5 plate converted to local documents
  (network; skipped with `NGC_OFFLINE=1`).
- `ops_tree.py`, `ops_traits.py`: the in-memory API.
- `extension_provenance.py`: the smallest extension, one metadata trait on an
  entry and the manifest derived from it.
- `extension_plate_training.py`: several extension points on one plate: a
  training-dataset trait, a Fractal table node and its custom CSV path type.
- `validate.py`: the validator bundles and a custom validator.

The two extension examples share three small extensions
(`examples/_extensions.py`): a Fractal *provenance* trait (pure metadata), a
*training dataset* trait on a collection (samples as references to its own
entries), and a Fractal *table* node whose CSV is located by a custom path
type. Their ids are raw GitHub URLs into `examples/schemas/`, where a minimal
JSON Schema describes each type; they are illustrative and may change.
`validate_all.py` checks every example document against those schemas when
`jsonschema` is installed (the library itself never evaluates schemas).

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

- **Multiscale transformations reference the multiscale itself, as a typed
  reference.** Array objects have no `id` (the review of
  [ngff-rfc8-revisions#43](https://github.com/ome/ngff-rfc8-revisions/pull/43)
  removed it on purpose), so the input of a multiscale's
  `coordinateTransformations` is the implicit array space of its
  highest-resolution array. The revision's newest example writes that as the
  multiscale's own id in a bare string; this package keeps typed references
  everywhere and writes `{type: "multiscale", ref: <the node's id>}`, with a
  `{type: "coordinate_system", ref}` output. Bare-string `input` / `output`
  values are not read. The `multiscale_transformations_wellformed` validator
  enforces this shape, that the output is a system the node declares, and that
  all transformations share it.
- **The physical reference is always the highest-resolution array.** A
  consequence of the above: calibration cannot be attached to another level.
  The first entry of `data` is taken as the highest resolution; the revision
  does not say how to identify it.
- **Not in sync with `rfc8_model`.** The pydantic draft in `ngff-rfc8-models`
  still has the earlier layout (`ome.root`, `arrays` of `singlescale`,
  snake_case keys), so documents do not round-trip with it until it follows
  the revision.
- **`absolute` and `http` paths are resolved.** The revision makes only
  `relative` a core format and defers the others to a sub-RFC. This package
  resolves all three (a read-only `HttpStore` behind a scheme-routed default
  store), so a collection or a multiscale document can point at existing local
  or remote data, remote arrays as levels included, without bundling it. Strict
  conformance is opt-in: `open_resolved(..., formats=CORE_FORMATS)` and the
  `paths_are_core` validator.
- **Provisional recommended traits.** HCS and labels are deferred to sub-RFCs;
  the trait models here follow the revision's examples and may change.
- **Version string `0.9dev4`.** The revision's examples only show the
  placeholder `"0.x"`.
- **An entry's id wins over its target's.** The revision only requires the
  document behind a `path` to have a root of the declared type. When the two
  ids differ, the resolved node keeps the entry's id; the target's root id is
  kept on the edge record and both are found by `find()`. Whether the ids
  should match is open upstream (issue #18).
- **Inlined and standalone copies are not reconciled.** The revision accepts
  that an inlined multiscale and the image's own document can go out of sync
  and leaves consistency to implementations. This package reads whichever one
  the document it opened contains and does not compare them.
- **Custom path types are data locators.** The revision makes the path `type`
  an extension point (its `OMEROPath` example). A URI-typed path may omit
  `format` and keeps the extra keys its extension defines; it must be declared
  in the manifest and is never fetched or opened as a node document
  (`DocPath.is_document` is false). One that sits inside a trait or a field
  without a `format` is not recognised as a path. The examples use one for a
  CSV table; `paths_are_core` flags them.
- **Manifest aggregation follows one level.** On `create` / `save` /
  `externalize` the manifests of the directly referenced documents are read
  and merged in (`aggregate_manifest=False` skips the reads). Documents further
  down are covered only if those documents aggregated in turn.
- **`mustUnderstand` is honoured through the process registry.** A custom type
  of a `mustUnderstand` extension is a validation finding unless the extension
  was passed to `register_extension`; nothing is skipped or rejected on read.

## Feedback to the RFC

Points this implementation surfaced, for the revision's authors:

- `traits` as a *list* keyed implicitly by `type` is harder to use than a dict
  keyed by type: same-type duplicates are unspecified and the override rule is
  keyed by type anyway (this package rejects duplicates).
- The revision's examples put an informational `name` inside references
  (`{type, ref, name, path?}`) while its schema table says a reference MUST NOT
  carry other fields; `ReferenceObj` follows the table and rejects `name`.
- Leftovers of the `singlescale` removal (PR #43): the `Declaration` section
  still lists `data` entries and `"array"` as declarations with an `id`; the
  context table still asks for `{type: "array", ref}` as the input of a
  multiscale transformation; and the inlined-multiscale example still gives
  its array an `id` and points the transformation at it.
- The multiscale examples use bare strings for `input` / `output` where the
  `Coordinate Transformation` interface requires typed references. If plain
  ids stay allowed inside one document, the text should say so and say what a
  multiscale's own id means as an `input`.
- With the implicit input, the physical transformation can only start from the
  highest-resolution array, and the text does not say how that array is
  identified (first in `data`, or the one without downsampling).
- `coordinateTransformations` is required on a multiscale, but the
  single-level example omits it, and an image whose pixel size is unknown
  still has to write one.
- Key casing is mixed. Besides the camelCase / snake_case split that a later
  RFC is meant to settle, the text still has `must_understand` in one example
  and `extension_manifest` in the JSON-LD paragraph.
- Without any free-form field, scratch metadata needs a URI trait and a
  manifest entry; one built-in opaque trait would absorb that.
- When an entry in a collection and the document it points at both carry
  traits or a `name`, precedence is unspecified (here the declaring entry
  wins; issue #8). The same holds for their ids (issue #18).
- A collection entry needs an `id` like any node, but the `OMEROPath` and grid
  gallery examples write entries without one.
- Trait rules (which node types a trait applies to, exclusivity, child
  constraints) have no machine-readable home; they live in validator code
  here. The revision lists this as future work.
- `http` for *scale* paths is low-risk (readers already fetch chunks by URL)
  and is what makes collections over existing remote data possible.
