# PoC of the Fall 2026 RFC-8 revision (ids, refs, paths)

**2026-10-13 · plan, not yet implemented.** Target shapes: deck
`2026-09-30 rfc8_revisions`, slides 5-7, with the slide 7 typo corrected
(`ref`, not `id`, on the collection side). Background and open RFC questions:
`rfc8-inner-node-issue.md`; library impact: `rfc8-inner-node-references.md`.

## Context

The graph layer (`graph/`: `NodeRecord`, `NodeTree`, structural `NodeId`s,
persistent indices) is format-agnostic. The current RFC-8 shapes live in
three places only: the wire value types (`models/_references.py`,
`models/_paths.py`), the resolver's stub path (`resolve/_build.py`) and the
serializer (`resolve/_serialize.py`, `resolve/_jsonrefs.py`). The proposal
*removes* code from all three (no stub merge, no edge overlay, no doc-root
special case), so the PoC is done in place on this branch as a format bump.
There is one payload version (`resolve/_document.py:VERSION`); no dual
support.

Goal of the PoC: show that `id` (declaration), `ref` (reference) and
`{type, format, href}` paths work end to end — open, inline, mint, save,
externalize, round-trip — and that a `ref` with a `path` reaches an inner
node of another document. Acceptance test: the four files in
`docs/examples/rfc8-inner-node/proposal/`.

## Out of scope

- `legacy_multiscale` (mounting 0.5/0.6 images).
- Consolidated metadata (slide 8).
- Typed traits, trait schemas, `extension_manifest`. Traits, scales and
  coordinate systems travel as an opaque body (see step 2). The typed
  attribute layer (`models/attributes/*`) and the built-in validators keep
  compiling but are not ported; their node-level entry points go stale and
  are marked so. Porting them to traits is a follow-up.
- Name uniqueness among siblings, bare `ref` semantics beyond "error",
  absolute/remote path policy.

## Decisions taken up front

- **Both document kinds stay.** The deck shows only `zarr` paths and does
  not say the `json` kind is gone. Keep `DocPath.type: zarr | json`.
- **`format` follows the deck literally:** `relative | absolute | http`.
  Interop beats naming for a PoC. It is derived from `href` when minting and
  checked against `href` when reading (mismatch is an error).
- **UUIDs:** one `new_id()` helper; `uuid.uuid7()` when the interpreter has
  it (3.14+), else `uuid4()`. Validation is format-only (canonical lowercase
  hyphenated); any version is accepted.
- **Body stays in the `attributes` field of `NodeRecord`,** redefined as
  "every key that is not structural" (structural: `type`, `id`, `name`,
  `nodes`, `ref`, `path`). The wire has no `attributes` key any more; the
  serializer splats the bag back at top level. No rename in the PoC: it
  touches `graph/`, `api/`, every test and the typed-access hook for no
  behavioural gain. Rename to `payload` later if it sticks.
- **A multiscale is a leaf.** `scales` and `coordinate_systems` are body
  keys, not child nodes. `singlescale` is removed.
- **A `nodes` entry with both `id` and `ref`, or with neither, is a
  document error** raised by `build` regardless of `on_error`. A `ref`
  without `path` inside `nodes` is left as an unresolved reference record
  (serializes back as `{type, ref}`); resolving it is not attempted.

## Steps

Each step lands with its tests green before the next starts.

### 1. Wire value types

- `models/_paths.py`: `DocPath` becomes `{type, format, href}`. Keep
  `resolve()` / `relativize()` and the module functions as they are, keyed
  on `href`. Add `format_for(href) -> Format` (uses `split_scheme` and
  `_is_local_abs`) and a model validator that `format` agrees with `href`.
  `ZarrPath` / `JsonPath` constructors fill `format` from `href`.
  `relativize()` recomputes `format`.
- `models/_references.py`: `ReferenceObj` becomes `{type: str, ref: UUID,
  path: DocPath | None}`. Replace `ID_PATTERN` / `IdStr` with `UUID_PATTERN`
  / `UuidStr`; add `new_id()`. Keep `IdStr` as a deprecated alias for the
  attribute models until they are ported.
- Callers of `ReferenceObj.id`: `validate/_builtins.py:55-58` (`.id` ->
  `.ref`), `api/_api.py:_ref_url/_locate`, `api/_node.py:Node.ref`.
- Tests: `tests/test_paths.py` (format derivation, mismatch error,
  round-trip), `tests/test_attributes.py:39` (new `ReferenceObj` shape).

### 2. Record layer (`graph/`)

- `graph/_record.py`: `NodeRecord.id: str` required. `Reference` becomes
  `(ref: str, path: DocPath | None = None)`; the record's own `type` is the
  reference's `type`. Delete `EdgeInfo` and `NodeRecord.edge`. Update the
  module docstring (shapes, `singlescale` gone, body semantics).
- `graph/_tree.py`: `_ref_key` returns `record.ref.ref`. `_segment_for`
  unchanged (prefers the id; UUID segments are fine for the PoC).
  `by_local_id` stays a multimap: duplicate detection is a validator, not a
  structural invariant.
- Tests: `tests/test_graph_core.py` fixtures get UUIDs; the duplicate-id
  cases (160, 178, 228) keep passing with duplicate UUIDs.

### 3. Resolver (`resolve/_build.py`)

- `_resolve`: branch on `"ref" in node_dict` (reference) vs `"id"`
  (declaration); both/neither -> `ValueError` always.
- `_materialized_record`: `id=node_dict["id"]`, body = all non-structural
  keys (replace `_attributes()` with `_body()`).
- `_reference_record`: `Reference(ref=node_dict["ref"], path=DocPath or
  None)`; no `name`, no body on a reference record.
- `_inline_stub`: after the cycle and fetched checks, locate the target
  with a new `_find_declared(root_dict, ref) -> dict | None` that walks
  inline `nodes` recursively and does **not** descend into entries carrying
  `ref` (non-transitive). Not found -> `LookupError` (raise) or leave.
  Type check against the *found* node, then splice it:
  `NodeRecord(type, name=found.name, id=found.id, attributes=body(found),
  children=() if "nodes" in found, origin_url=target.url)`.
- Delete `_merge_record`, the payload-free-target branch (193-196: there
  are no array-pointing stubs any more; a target without `ome` is an
  error/leave like a missing one) and the `edge` plumbing. Update the
  module docstring.
- `resolve/_fetch.py:reference_targets` / `_walk`: prefetch the `path` of
  entries carrying `ref` (today it keys on `path` on any node dict; the
  shape is the same, only the sibling key changes). Do not prefetch refs
  inside the body.
- Tests: `tests/test_resolve.py`: rewrite the merge/edge cases as
  "spliced node is the found declaration, no overlay"; add inner-node
  resolution, non-transitive lookup, not-found under skip/raise, both-keys
  error, bare `ref` left in place.

### 4. Serializer and write path

- `resolve/_serialize.py:node_dict`: reference record -> `{type, ref,
  path?}`; declaration -> `{type, id, name?, **body, nodes?}` in that key
  order. Relativize `path.href`.
- `resolve/_jsonrefs.py`: match the new path shape (`type in (zarr, json)`,
  `href` is a `str`) and relativize `href`; recompute `format`.
- `resolve/_write.py`: no change expected; verify.
- `VERSION` stays `"0.x"`.
- Tests: `tests/test_serialize.py` (reference stub shape, body splat,
  key order, href relativization, unedited document re-serializes
  byte-identical).

### 5. API (`api/`)

- `api/_node.py`:
  - `new_node(id=None)` mints via `new_id()`; `id` is always set after.
  - `_reference_stub(node, url)` -> `new_node(node.type,
    ref=Reference(ref=node.id, path=reference_path(url)))`; no `id`/`name`
    on the stub. Update `ref_stub` / `find` docstrings (no id-less stubs).
  - `Node.ref()` -> `ReferenceObj(type=self.type, ref=self.id,
    path=reference_path(url))`. Remove `require_id` (id is required) or keep
    as a no-op shim; remove.
  - `Node.ref_path` -> `ref.path.href` (or `None` for a bare ref).
  - Remove `SinglescaleNode`, its registration and the `api/__init__.py`
    export. `MultiscaleNode` stays (leaf).
  - `reference_path(url)`: unchanged logic, builds the new `DocPath`.
- `api/_api.py`:
  - `_locate(root, ref, url)`: `root.find(ref.ref)` plus a type check
    against `ref.type` (mismatch -> `TypeError`).
  - `externalize` (312-318): stub record carries only `type`, `ref`,
    `origin_url`.
  - `delete`, `create`, `save`, `save_inlined`: unchanged apart from the
    stub shape; `delete`'s "no id" branch goes.
- Tests: `tests/test_api.py` (minted stubs have `ref` and no `id`, 84 and
  103 rewritten; `open_ref` type mismatch), `tests/test_node.py`.

### 6. Validation

- `validate/_builtins.py`: add `id_is_uuid(node)` (per-node, fits the
  engine) and a tree-level `unique_ids(root) -> list[ValidationError]`
  (walk once, report every duplicate with all its `NodeId`s). Expose both
  from `validate/__init__.py` and the package root.
- `scale_matches_axes`: `.id` -> `.ref`; it still reads the old
  `coordinateSystems` attribute key, so mark it stale (docstring + xfail on
  the node-level test) until traits are ported. `well_under_plate` same.
- Tests: `tests/test_validate.py` for the two new checks.

### 7. Fixtures, examples, acceptance

- Regenerate `examples/data/*` by running the `examples/*.py` scripts once
  the API is green (they are the source of those fixtures). Drop
  `singlescale` from `custom_node_types.py` / `open_inlined_inspect.py` if
  they use it; a multiscale example is a leaf with `scales` in its body.
- Acceptance test `tests/test_proposal_examples.py`: load the four
  `docs/examples/rfc8-inner-node/proposal/*.jsonc` files (strip `//`
  comments), write them into the memory store at
  `/x/{scene-a,scene-b,image-a,training-data}/zarr.json` (plus `image-b` as
  a copy of `image-a` with the b UUIDs), then assert:
  - `open("/x/training-data")`: three reference children with the expected
    `ref`s, no ids on them;
  - `open_inlined("/x/training-data")`: children are the two inner `crop`
    collections (ids `…a1`, `…b1`) and the `image-a` multiscale (`…a2`);
    each `crop` has one child that is a reference to its image; with
    `depth=None` those resolve to multiscale leaves whose body holds
    `scales` and `coordinate_systems`;
  - `open_inlined(..., on_error="raise")` on a training-data variant with a
    wrong `type` raises `TypeError`, with an unknown `ref` raises
    `LookupError`;
  - save round-trip of `training-data` re-serializes identically.
- README: replace the "Discrepancy with RFC-8" section with a short
  "Targets the Fall 2026 proposal" note pointing at this plan.

## Verification

```bash
pixi run lint
pixi run type-check
pixi run --environment dev pytest
```

plus the acceptance test above. Done when every step's tests pass and the
seven fixture directories are regenerated from their scripts.
