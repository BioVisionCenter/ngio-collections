# Roadmap

**Status:** revised 2026-06-11 (simplicity over completeness) · companion to
[DESIGN.md](DESIGN.md)

Scope of this roadmap: a complete, round-trip-safe **local** implementation —
parse, validate, navigate, edit, save on the local filesystem. Remote and
mixed-store support remain the primary eventual use case (the core stays
async-native for that reason), but their implementation is deferred:
`FsspecStore` exists only as an interface skeleton; `RouterStore` is
design-only (DESIGN.md �6), with no code yet. Everything
deferred is recorded under [Future work](#future-work) below and in
DESIGN.md §10.

Sequencing principles:

- Bottom-up through the layers (models → document → resolver → store), but
  every milestone ends in a state that is independently testable and useful.
- Round-trip fidelity (parse → edit → save) is the riskiest design area, so
  the roadmap ends when the local write path round-trips.
- CI from milestone 1, so every subsequent milestone lands gated.

Current state: structural skeleton (modules, signatures, and trivial pieces
in place; behavior stubbed), trimmed to the local-scope surface.

---

## M1 — Models complete + CI

The models layer becomes fully spec-faithful; infrastructure catches up.

- [x] Structural validators (currently TODO stubs in `models/nodes.py`):
  - `CollectionNode` / `MultiscaleNode`: exactly one of `nodes`/`path`;
    child names unique.
  - `MultiscaleNode`: inlined form requires `coordinateSystems` attribute.
  - `SinglescaleNode`: requires `coordinateTransformations` attribute when
    no `path` is set.
  - `LabelObj.color`: four integers in [0, 255] (RGBA).
- [x] Registry-driven child parsing (DESIGN.md §3.4): node `PlainValidator`
  reads the `NodeRegistry` from Pydantic's validation context, falling back
  to `DEFAULT_REGISTRY`; unregistered types degrade to `BaseNode`.
- [x] Port/adapt the prototype's model tests (`test_models.py`,
  `test_attributes.py`).

**Done when:** every node/attribute fixture in `tests/data/` validates
through the registry with the right subtypes, invalid shapes fail with clear
errors.

## M2 — Document layer

The single (de)serialization path, with provenance.

- [x] `parse_document()`: detect json vs zarr envelope, validate through the
  registry, enforce document-level unique node ids, set `_document` /
  `_parent` back-references on every parsed node.
- [x] `Document.serialize()` / `serialize_bytes()`: emit the right envelope;
  a child whose `_document` differs from the document being dumped is
  emitted as a path stub via that document's `stub_path` (DESIGN.md §3.6).
- [x] Defined detachment semantics: `model_copy()` / re-validation produce
  `_document is None`; document a clear error story for saving detached
  nodes.
- [x] Round-trip tests against all three fixture layouts, including
  unknown-attribute and custom-prefixed-field fidelity.

**Done when:** `parse_document(serialize_bytes(...))` is byte-stable on the
fixtures (modulo key ordering), in both envelope forms.

## M3 — Local read path

First end-to-end vertical slice: open and navigate a collection on disk.

- [x] `LocalStore.get/put` (plain paths and `file://`; `FileNotFoundError`
  contract).
- [x] `Resolver.open()`: fetch, parse, cache by URL.
- [x] `Resolver.resolve(stub)`: `urljoin` against the declaring document's
  URL; absolute URLs pass through; zarr stubs target `<path>/zarr.json`.
- [x] `Resolver.children(node)`: stubs transparently replaced by resolved
  document roots; never mutates the parsed tree (DESIGN.md §3.3).
- [x] Navigation tests over the `externalised` and `mixed` fixtures.
- [x] `Resolver.resolve_tree(doc, max_depth=, on_error=)` (added 2026-06-12):
  breadth-first cache warming, each frontier fetched concurrently; data
  leaves (`FileNotFoundError` / `NotOmeDocumentError`) skipped under the
  default `on_error="skip"`, every other error raises.
- [x] `Resolver.inline(doc, max_depth=, on_error=)` (added 2026-06-12):
  explicit copy-building merge of a resolved tree into one document; applies
  the DESIGN.md §5 attribute-merge rule (`models.merged_attributes` —
  shallow, key-level, stub wins; stub's `id`/`name` kept) when collapsing a
  stub into its resolved subtree. Never mutates the originals or the cache;
  surviving data paths from non-top documents are rebased to absolute URLs.
  `max_depth` (added 2026-06-12) bounds the collapse by resolution hops;
  boundary stubs are never fetched and survive verbatim (paths rebased).
- [x] Sync convenience API `ome_zarr_collections.api` (added 2026-06-12):
  `open_collection` / `open_multiscale` (fully inlined single tree, direct
  URL only; `max_depth=` / `on_error=` forwarded to the warming pass and
  `inline()`) and `write_collection` / `write_multiscale` (one embedded
  document, form inferred from the URL; returns the typed reference form
  `CollectionRef` / `MultiscaleRef` for composing parent collections, with
  `relativize` path rewriting — added 2026-06-12). Background-loop-thread
  runner, so it works inside Jupyter; the full mirrored sync facade stays
  deferred.

**Done when:** the DESIGN.md §5 read-side sketch (`open` → `children` loop)
runs unmodified against `tests/data/`.

## M4 — Local write path (final milestone)

Document-granular editing — the core value proposition.

- [x] `Resolver.save(doc)`: rewrite ONE document; zarr form does
  read–modify–write of `zarr.json` touching only `attributes.ome`
  (sibling keys like `zarr_format` survive).
- [x] Early `StoreReadOnlyError` when the target store can't write.
- [x] Edit → save → re-open round-trip tests; stub re-emission for
  externalized children; port the prototype's resolver tests.

**Done when:** editing one node's attributes and saving touches exactly one
file on disk, and a re-opened tree reflects the edit with everything else
byte-identical. That is also the end of this roadmap.

---

## Future work

Explicitly deferred, in rough priority order. None of it is scheduled;
re-evaluate once M4 is done. See also DESIGN.md §10.

- **`FsspecStore` implementation** — remote collections over http/s3/gcs;
  the skeleton (interface + `read_only` flag) is in `store/fsspec.py`.
- **`RouterStore` / mixed-store collections** — longest URL-prefix dispatch
  (design in DESIGN.md §6, no code yet). Includes documenting the cross-store
  portability asymmetry.
- **Full sync facade** (`ome_zarr_collections.sync`) — loop-runner wrapper
  mirroring the whole Resolver surface. Partially superseded 2026-06-12 by
  the four-function `ome_zarr_collections.api` module; for everything else,
  `asyncio.run()`.
- **`Resolver.write(node, url, stub_path=...)`** — externalizing a node into
  a new document (collection restructuring). Bottom-up *composition* by
  reference is covered 2026-06-12 by the sync writers returning reference
  stubs (with `relativize` path rewriting); restructuring stays deferred.
- **Attribute-registry extensibility** — removed as dead code (the `attrs`
  view takes attribute classes directly); re-add only if a use case appears.
- **Conformance suite** against the RFC-8 examples; revisit the open spec
  questions in DESIGN.md §9 against the current draft.
- **Docs + release** — `py.typed`, API docs, README examples, PyPI `v0.1.0`.
  Releasing waits until remote support exists (it is the primary use case).
- **Concurrency limits / request batching** in `FsspecStore`.
- **Optional dirty tracking** on top of document-granular saves.
- **Typed RFC-5 coordinate-transformation union** once that spec settles.
