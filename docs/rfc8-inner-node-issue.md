# How can a collection reference a non-root node of another document?

**Status, 2026-10-13:** answered by the Fall 2026 revision proposal
(`2026-09-30 rfc8_revisions`, slides 5-7). A few sentences are still missing
from the text; they are listed at the end.

## The question, as asked against the current RFC-8

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

What does `id` mean on this stub? Two readings were possible.

- **Reading 1, `id` is a declaration.** `id` is the stub's own id in
  `consumer.json`, and `path` means the root of `source.json`. This is what
  the text implies (a Node's `id` "MUST be unique within the JSON document",
  a `Path` reaches "the metadata of the referenced node"). A non-root node
  of `source.json` can never be referenced.
- **Reading 2, `id` is a lookup.** `id` selects the node with that id inside
  the document at `path`, as the RFC's own `Reference` object `{id, path?}`
  already does inside `attributes`. An inner node becomes reachable, but the
  stub's `id` is also its own id in `consumer.json`, so two sources that
  both call their multiscale `image` cannot be mounted side by side. This
  reading needs globally unique ids by convention.

## What the proposal does

- `id` declares a UUID; `ref` points to one. A reference holds only `type`,
  `ref` and an optional `path`. Both keys on one object is a contradiction.
- A bare `ref` resolves in the current document. A `ref` with a `path`
  resolves in the referenced document. Slide 5 already uses this to reach a
  `coordinate_system` nested inside the target multiscale.
- An entry in `nodes` that points at another document is a reference
  (slide 7 reads `"id"` on the collection side; the author confirmed this is
  a typo for `"ref"`). So a UUID is declared exactly once, in the document
  that holds the body.
- Multiscales are never inlined; every multiscale is its own document.
- `attributes` is replaced by typed `traits`; `name` is optional and
  free-form.

Put together, this is reading 2 with a dedicated key and globally unique
ids, which removes the objection to reading 2. The consumer writes:

```jsonc
"nodes": [
  { "type": "collection",
    "ref": "0192f3a0-a000-7000-8000-0000000000a1",
    "path": { "type": "zarr", "format": "relative", "href": "./scene-a" } },
  { "type": "collection",
    "ref": "0192f3a0-b000-7000-8000-0000000000b1",
    "path": { "type": "zarr", "format": "relative", "href": "./scene-b" } }
]
```

Each `ref` is an inner node of the document at `path`. No `id`, `name` or
`traits` on the entry: the referenced node brings its own. A document root
is referenced the same way, by its UUID, so there is no special "root stub"
any more.

The follow-up questions about `name`, `type` and `attributes` on a stub
become moot: a reference has no `name` and no `traits` to merge, and its
`type` must simply equal the target's. The one place where a parent still
declares on behalf of a target is `legacy_multiscale` (slide 10), because a
0.5 or 0.6 image has no id of its own.

A worked example in the proposed shapes is in
`docs/examples/rfc8-inner-node/proposal/`.

## Sentences still missing from the text

1. **References in `nodes`.** Slide 6 says references live "in fields"
   (`input`, `output`, `source`) and declarations "in arrays" (`nodes`,
   `scales`, `coordinate_systems`). With slide 7 corrected, `nodes` holds
   references too. Define the two by key only: `id` declares, `ref` points,
   both on one object is an error.
2. **Resolution scope of a `ref` with a `path`.** The document at `path`,
   including its inline children, and not transitively through further
   paths. Say so, otherwise a resolver has to crawl.
3. **No overlay on a reference.** Confirm that a reference in `nodes`
   carries no `name` and no `traits`, so a consumer cannot rename or
   decorate a mounted node locally. It decorates its own collection, or
   wraps. Name `legacy_multiscale` as the one exception.
4. **Bare `ref` inside `nodes`.** A `ref` without a `path` makes the same
   node a child of two parents in one document, or a cycle. Forbid it, or
   define the behaviour.
5. **`type` on a reference** MUST equal the target's type; a mismatch is an
   error.

## Other remarks on slides 5-7

- **UUID rules.** Version (the examples look like v7), canonical lowercase
  hyphenated form, uniqueness scope (all documents reachable from a root),
  and whether a modified copy of an image must mint a new UUID. Sharing a
  UUID across trees for the same bytes is desirable.
- **Names.** Optional and free-form is fine, but `name` SHOULD be unique
  among siblings. Otherwise there is no human-readable addressing and UUID
  path segments are unusable in a UI or CLI.
- **Path format.** `relative`, `absolute` and `http` are not one axis, an
  `http` URL is absolute. Suggest `relative | absolute | url`, and state that
  a disagreement between `format` and `href` is an error. Only `zarr` paths
  appear; say whether the `json` document type survives.
- **Scale self-reference.** On slide 7 each scale's transform has
  `input: {type: scale, ref: <itself>}`. A scale is not a coordinate system
  and the input is always the scale's own array space. Make it implicit.
- **Inline collections.** Slide 5 forbids inline multiscales, slide 6 lets
  a declaration hold "child nodes". Make the rule explicit.
