# ngio_collections reimplementation — friction points & verdict

Notes on the port of `fractal-collections-tools` + `scripts/` from the old
`ngio_collections` (typed node classes, mutable trees, type-specific `write_*`/`open_*`)
onto the reimplemented library (a single opaque `Node` handle over an immutable record,
unified `open`/`create`/`save`).

This document focuses on **what became more cumbersome**. See the end for an overall verdict.

## What became more cumbersome

### 1. Constructor-with-children → fold-and-reassign
Nodes are now immutable, and `.add()` / `.add_ref()` return a *new* node. A concise child
literal becomes a reassignment loop.

```python
# before
scene_node = ngc.CollectionNode(
    id=..., name=..., attributes=...,
    nodes=[*image_refs, *build_scene_tables(row, col, field)],
)

# after
scene_node = ngc.new_node("collection", id=..., name=..., attributes=...)
for stub in image_stubs:
    scene_node = scene_node.add_ref(stub)
for table in build_scene_tables(row, col, field):
    scene_node = scene_node.add(table)
```

More lines, and a real footgun: forgetting to capture the return value silently drops the
child instead of erroring. Same pattern spread across `write_well` / `write_plate` in both
build scripts.

### 2. Inline-vs-reference is now a manual, per-call decision
Previously any stub dropped into `nodes=[...]` was linked as an external document
automatically. Now every attach site must choose `.add()` (embed inline) vs `.add_ref()`
(link a separate document). In `_ops.add_node` this means hand-building the stub:

```python
if child.is_detached:
    edited = target.add(child)
else:
    locator = child.ref()
    if locator.path is None:
        raise ValueError(...)
    stub = ngc.new_node(child.type, id=child_id,
                        ref=ngc.Reference(path=locator.path, id=locator.id))
    edited = target.add_ref(stub)
```

~15 lines that the old single `rewrite_tree` seam handled implicitly.

### 3. Reference-path access got deeper and needs helpers
`node.path` (one attribute) became `node.record.ref.path` with a `None` guard. This forced
new helpers:
- `_visualize._node_path(node)` — `node.record.ref.path.path or None`
- `task_type1._first_array_url(node)` — `open(doc).children()[0].record.ref.path.path`

A one-hop read is now a two/three-hop reach through `record`.

### 4. `id` / `name` / `document_url` are now Optional → guards everywhere
The opaque handle no longer guarantees these, so None-checks moved into user code:
- `_ops.py` grew three narrowing helpers: `_require`, `_nid`, `_doc_url` (each raises `ValueError`).
- `_derive.py` added an explicit "requires every node to carry an id" check.
- `_context_filters.py` widened its index dicts/sets to `str | None` keys.
- `_visualize.py` filters `n.id is not None` when building id sets.

The old typed classes made id/name non-optional; the new model pushes validation onto callers.

### 5. Lost affordances the old code relied on
- **`add_sibling` can no longer insert immediately after a node** — `.add()` only appends as
  the last child, and the new code carries a comment documenting the behavior change.
- **`open_multiscale(...).nodes[0].path`** (resolving a scene's first array in `task_type1.py`)
  had to be rebuilt as a helper going through `open(doc).children()[0].record.ref`.

### 6. Attribute-object construction is stricter
Axes must now be `ngc.Axis(name=..., type=...)` objects; the old code accepted plain
`{"name": ..., "type": ...}` dicts. Regenerated fixtures also now emit explicit
`unit/discrete/longName: null` on every axis, producing large but cosmetic JSON churn.

## Overall verdict — is this a step in the right direction?

**Yes, on balance — with one caveat.**

The reimplementation trades *construction ergonomics* for *model coherence*, and that is
the right trade for a library that will be extended and maintained:

- **The read/query/edit surface got genuinely cleaner.** Uniform `node.children()`,
  `node[T]` / `node.get_attr(T)`, type-agnostic `create`/`save`, declarative
  `register_node_type`, and a public `document_url` (no more private `_source_path`) all
  remove special-casing. `_ops` edits are now honestly local — one document opened, edited,
  saved — instead of a whole-tree rewrite for every add/remove.
- **Immutability is a deliberate, defensible choice.** It eliminates a class of
  aliasing/mutation bugs and makes `derive`/`rewrite` reason about fresh trees. The verbosity
  it introduces (fold loops, explicit `.add` vs `.add_ref`) is *ceremony, not accidental
  complexity* — it makes the inline-vs-reference decision explicit where it was previously
  hidden.

**The caveat:** most of the cumbersome-ness is builder ergonomics, and it is fixable in a thin
layer rather than a reason to reject the design. The friction points cluster into things a
small convenience API could absorb:
- a builder that takes children up front (`new_node(..., children=[...])`) to kill the fold loops,
- a single `attach(child)` that auto-decides embed vs reference (folding case #2 back into the library),
- a `node.ref_path` accessor to hide the `record.ref.path` chain,
- keeping `id` required at the handle level (or a `require_id()` accessor) to remove the scattered None-guards.

So: the *foundation* moved in the right direction (opaque handle + immutable record + unified
verbs is a cleaner core than typed subclasses + mutable trees + type-specific writers). The
current rough edges are almost entirely missing ergonomic sugar on top of a better base — which
is exactly the kind of debt worth taking on early and paying down later, rather than the reverse.
