# RFC-8: how can one reference a non-root node inside a collection document?

**2026-10-05 · confirmed against the RFC-8 text and this implementation**

## The question

Suppose `consumer.json` wants a multiscale that is defined inside
`source.json`, below its root:

```jsonc
"nodes": [
  { "type": "multiscale",
    "id": "image",
    "name": "Image",
    "path": { "type": "json", "path": "./source.json" },
    "attributes": { ... }
  }
]
```

What does `id` mean on this stub? There are two readings.

## Reading 1: `id` is a declaration

`id` is the stub's own id in `consumer.json`, and `path` means the root of
`source.json`. This is what the text says: a Node's `id` "MUST be unique
within the JSON document", and a `Path` reaches "the metadata of the
referenced node", i.e. the document root. No field on a Node selects a node
inside the target.

- A consistent `consumer.json` can always be written, whatever ids
  `source.json` uses.
- A non-root node of `source.json` can never be referenced. The stub above is
  a type mismatch against a collection root. The only way is for the owner of
  `source.json` to externalize the multiscale into a document of its own.
- `id` behaves like the `name` field and similarly to `attributes` field, at least
  in my own personal implementation.

## Reading 2: `id` is a lookup

`id` selects the node with that id inside the document at `path`; a stub
without `id` means the root. This is exactly how the RFC's own `Reference`
object (`{id, path?}`) already works inside `attributes` (transformation
`input`/`output`, label `source`, HCS well `row`/`column`).

- An inner multiscale inside `source.json` becomes reachable.
- The stub's `id` is also its own id in `consumer.json`, and the Node schema
  has no second field for a local name. So every node a consumer references
  must carry an id distinct from all others it uses. RFC-8 only mandates
  uniqueness per document, so this reading needs globally unique ids
  by convention.
- In this view, there is no mechanism for a `consumer.json` to redeclare
  an `id` for a node.


## Follow-up
As a follow-up, of settling this one should also clarify how to interpret `name`,
`type`, and `attributes`. 
- For `name` feels natural to allow for renaming, 
- While for `type` to me there is never a reason to disagree with the stub's `type`,
- For `attributes`, it would be great to define a mechanism for inlining the attributes from the stub's target. (Replace, shallow update, or deep update)


## Example (`docs/examples/rfc8-inner-node/`)

`scene-a.jsonc` and `scene-b.jsonc` each define a multiscale inline, below
the root, both with the natural id `image`. `training-data.jsonc` wants both:

```jsonc
{ "type": "multiscale", "id": "image", "name": "scene A image",
  "path": { "type": "json", "path": "./scene-a.jsonc" } },
{ "type": "multiscale", "id": "image", "name": "scene B image",
  "path": { "type": "json", "path": "./scene-b.jsonc" } }
```

- Reading 1: both stubs mean a scene root, a `collection`, so neither
  multiscale is reached. Renaming the stub ids changes nothing.
- Reading 2: both stubs must say `image` to reach their target, which
  violates id uniqueness in `training-data.jsonc`. With UUIDs on the two
  multiscales the stubs copy them and both resolve.

Observed with the current library on the comment-stripped files:

```
open_inlined(training-data.json)   skip  -> both stubs left unresolved
                                   raise -> TypeError: stub type 'multiscale' does not
                                            match target root type 'collection'
open_ref(ReferenceObj(id='image', path=./scene-b.json)) -> the inner multiscale
```

## In this implementation

- Reading 1 is implemented: `resolve/_build.py:197-208` checks the stub
  `type` against the target root and splices `target.root`; the stub `id`
  (stored at 228-238) is never read.
- Reading 2 exists only as an API call: `api/_api.py:110-155` (`open_ref`)
  takes a `ReferenceObj`, opens the whole target, and finds `id` in it.
- Every stub this library mints carries its target root's id (`e4d3113`),
  so all fixtures resolve identically under either reading.
- Cost of reading 2: `_inline_stub` looks the id up in the target and runs
  the existing type check and merge on that node instead of `target.root`.

## Alternatives to reading 2

A separate `target` field on the stub (keeps local ids, no global-id
precondition, one more field); a `#fragment` on the path string (overloads
the locator); a JSON-pointer path type (positional, breaks on reorder).

## Housekeeping

- `graph/_record.py:37-43`: the `Reference` docstring already describes
  reading 2; the resolver implements reading 1.
- `README.md` "Discrepancy with RFC-8": add a one-line pointer here.

## Against the 2026-09-30 proposal

**2026-10-13 · deck `2026-09-30 rfc8_revisions`, slides 5-7.** Everything
above this line is the pre-proposal baseline and still describes the code.

Slide 7 shows the collection-side `nodes` entry with `"id": "…10"` and the
target `raw/zarr.json` with the same `"id"`. The author confirmed the left
side is a typo for `"ref"`. With that fix the model is: `id` declares a
UUID once, in the document that holds the body; `ref` points to it; a `ref`
with a `path` resolves inside the document at `path` (slide 5 already does
this for a nested `coordinate_system`); a reference carries only `type`,
`ref` and `path`.

### Settled

- Reading 2, with a dedicated key. A `nodes` entry
  `{type, ref: <uuid>, path}` reaches an inner node of another document.
  This is option (3) in `training-data.jsonc` and the "separate selector
  field" alternative above, adopted outright.
- The global-uniqueness precondition is no longer a convention: ids are
  required UUIDs.
- The merge question is moot. A reference has no `name` and no `traits`;
  the referenced node brings its own. `type` must equal the target's.
- `README.md` "Discrepancy with RFC-8" (ids as primary handle, names
  optional and non-unique) describes positions the proposal adopts.

### Dissolved rather than solved

- Inline multiscales and `singlescale` are gone (scales replace datasets),
  so the scene example below the root cannot be written any more. The
  residual case is an inline *collection* below a root, which slide 6
  still allows ("child nodes" in a declaration).
- The stub overlay (`name`, `attributes` on a path-carrying entry) has no
  counterpart. `legacy_multiscale` (slide 10) is the one parent-side
  declaration left, because a 0.5/0.6 image has no id.

### Impact on this implementation

- `resolve/_build.py:164-208` `_inline_stub` must look `ref` up inside the
  target and type-check the found node, not `target.root`. That is the
  "cost of reading 2" paragraph above; `api/_api.py:102-107` `_locate`
  already does the lookup for `open_ref`.
- `_merge_record` (`_build.py:241-267`) and the `EdgeInfo` overlay
  (`graph/_record.py:49-63`) lose their purpose: nothing to merge.
- `api/_node.py:401-415` `_reference_stub` writes `ref=node.id` only, no
  `id` on the stub. The e4d3113 contract survives in spirit.
- The structural `Reference(path, id | None)` and the wire
  `ReferenceObj(id, path?)` collapse into one `{type, ref, path?}` object.
  `id = None` meaning "document root" goes away: a root is addressed by its
  UUID like any other node.
- `models/_paths.py`: `DocPath{type, path}` becomes `{type, format, href}`;
  the scheme inference in `split_scheme` becomes an explicit field. Whether
  the `json` document type survives is unanswered (only `zarr` appears).
- Node `id` becomes required (UUID; `new_node` must mint), `singlescale`
  handle removed, inline multiscales removed, the `attributes` layer
  becomes traits, and `input`/`output`, labels `source`, HCS `row`/`column`
  take `{type, ref}`.
- `validate/`: add UUID format and per-tree uniqueness checks; none exist.

### Still to clarify in the RFC text

See the "Sentences still missing" list in `rfc8-inner-node-issue.md`:
references in `nodes` by key not by location, resolution scope of a `ref`
with a `path`, no overlay on a reference, bare `ref` inside `nodes`, and
`type` on a reference MUST match.

### Example in the proposed shapes

`docs/examples/rfc8-inner-node/proposal/`: `scene-a` and `scene-b` each hold
an inline child collection and reference a multiscale document;
`training-data` references both inner collections by UUID through the scene
documents, and one multiscale root the same way. Not parseable by the
current code (new keys); it documents the target shapes.
