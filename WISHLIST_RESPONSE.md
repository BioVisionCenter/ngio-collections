# Response to the Fractal v3 POC wishlist

**2026-07-02 · ngio-collections side · implemented on the `ergonomic-apis` branch**

The Fractal v3 POC filed an upstream wishlist (kept in the Fractal repo)
collected while porting `fractal-collections-tools` onto this library. Every
item was reviewed on its own merits — would a maintainer with no knowledge of
Fractal want it? — and the accepted set is implemented and tested here. This
file is the self-contained record of the outcomes; each item is restated
briefly so it reads without the original document.

## Shipped

### 1.1 — `origin_url` on node construction
*Asked:* construct a node that records the document it lives in without
reading it (server folding task-reported updates; caches, mirrors, transport),
instead of hand-building `NodeRecord`/`NodeTree` from the private `graph`
layer.

*Shipped* as a constructor knob, `new_node(..., origin_url=...)` — no separate
`with_origin()` method, one construction path. The URL is normalized exactly
like the read path, so `document_url` matches what `open()` would stamp; the
node is document-backed (`is_detached` false, `ref()`/`ref_stub()` work
IO-free). The caller asserts the document exists; `create()` keeps rejecting
document-backed trees (they route to `save`). All downstream
`ngio_collections.graph` imports can now be deleted.

### 1.2 — Built-in `MemoryStore`
*Asked:* the trivial in-memory store everyone writes themselves.

*Shipped* as sketched: `MemoryStore(initial: Mapping[str, bytes] | None = None,
*, read_only: bool = False)` with the full store contract
(`FileNotFoundError` on missing `get`, `StoreReadOnlyError` on read-only
writes, idempotent `delete`) plus `items()` / `in` / `len()` for inspection.
Exported at top level; ngio's own API tests now run on it.

### 1.3 — Stub-id contract
*Asked:* document that stubs written by `create`/`ref_stub` carry the child's
id and are findable via `find(id)`.

*Shipped — but the premise was wrong.* Written stubs did **not** carry an id:
it lived only on the internal `Reference.id`, which the serializer ignores, so
library-minted stubs were unfindable both in memory and after a round-trip.
This was a fix, not documentation: minted stubs (from `create` / `save` /
`save_inlined` / `ref_stub`) now set the record id too, serialize with an
`id`, are findable by `find(id)`, and `remove()` works on them uniformly. The
contract is documented on `Node.find` and `Node.ref_stub`; an id-less stub
remains a legal doc-root reference, addressable only structurally
(`children()` / `walk()`).

**Corollary for Fractal:** the positional-removal workaround in `_ops.py` was
*correct*, not stale — retire it only against ngio at this branch or later.

### 1.4 — Facade completeness
*Asked:* everything a downstream library needs importable from the top level;
`graph`/`resolve` explicitly private.

*Shipped as docs.* README and the package docstring now state that the
top-level re-exports are the public surface and the subpackages are internal
layout; a test pins `__all__` resolution and the downstream-essential names.
Underscore-renaming the subpackages was rejected as churn. With 1.1 shipped,
nothing forces a deep import anymore — a missing top-level name is a bug to
report, not a reason to deep-import.

### 2.1 — Combined merge+drop (small form)
*Asked:* edits return a new root, so merge-then-drop needs a re-`find` between
two calls; smallest fix `set_attrs(attrs, drop=...)`, fuller fix a batch-edit
session.

*Small form shipped:* `set_attrs(values, *, drop=())` merges then removes in
one edit (drop applied after the merge, so a key in both ends up absent);
`drop` takes str keys or attribute classes, like `drop_attrs`. The batch
session is **deferred**: it would be a second, mutable editing surface against
the one-way functional model, for a cost that is negligible at metadata-tree
sizes. Revisit with profiling evidence or alongside a patch applier (3.3).

### 2.3 — Externalize-and-link
*Asked:* one verb for "write this node as its own document and link a stub
into its parent's document".

*Shipped in a different shape.* The verb the library actually lacked is
*restructuring*: `externalize(node, destination)` splits a node already inside
an opened tree out into its own document, replaces it with a reference stub at
the **same sibling position**, and saves the home document — orphan-safe
ordering (new document written before the home document is rewritten), not
atomic (documented). The wishlist's detached-child form is deliberately left
as the 3-line composition of existing verbs: `create` → `add_ref` → `save`.
Fractal's add-node flow becomes: attach the child, then `externalize` it.

## Groundwork shipped, verb deferred

### 3.1 — Per-document write-back of resolved trees (`save_tree`)
*Asked:* prioritize persisting an edited inlined view document-granularly.

The hard blocker is removed: inlining previously *flattened* the
stub-over-target attribute merge and dropped the stub's ref, making write-back
unrecoverable. Inlined boundary records now retain the collapsed edge
(`EdgeInfo`: the stub's ref, its pre-merge attributes/name, the declaring
document's URL), so the merge is invertible by origin. `save_tree` itself is a
subsystem (un-merge semantics, dirty detection, document partitioning) and
gets its own design round.

### 3.2 — Document fingerprints / `StatStore`
*Asked:* cheap change detection — a `stat()` store extension plus a canonical
content hash.

*Split.* `fingerprint(data)` shipped: sha256 over a canonical re-encoding of
the parsed JSON, stable across serializer backends and formatting — the
change-detection primitive `save_tree` will also use. `StatStore` is
**deferred** until `FsspecStore` exists: no protocol extension with zero
implementations behind it (etags/mtimes only mean something remotely).

## Rejected / deferred

### 2.2 — `attach()` auto-deciding embed vs reference: **rejected**
The premise ("the decision is fully determined by the child's state") doesn't
hold: for a document-backed child, embedding a copy and linking a reference
are *both* valid operations, so a state-dispatching verb removes a real
choice. With `ref_stub()`, the explicit form is one line:
`parent.add(child)` vs `parent.add_ref(child.ref_stub())`. The migration
report itself called this explicitness "ceremony, not accidental complexity".

### 3.3 — Generic serializable tree-patch language: **deferred, as proposed**
Downstream-first, per the wishlist's own framing: build it in
`fractal-collections-tools`, offer it for upstreaming once proven. The only
upstream obligation — keeping construction, attribute-edit, and
reference-linking primitives public enough to write an applier against — is
satisfied (1.1 closed the last gap).

## Fractal-side homework (updated)

- Switch `BaseAttribute` / `ReferenceObj` / `BaseObj` imports to the top-level
  facade (already public).
- Delete all `ngio_collections.graph` imports (1.1 shipped).
- Retire the positional-removal workaround in `_ops.py` — only against ngio ≥
  `ergonomic-apis` (see 1.3's corollary).
- `write_and_link` collapses to `create` → `add_ref` → `save`, or
  `externalize` when the child is already attached.
