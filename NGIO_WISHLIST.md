# ngio-collections wishlist (from the Fractal v3 POC)

Input to the upcoming ngio-collections refactor, collected while building this
POC (see `ARCHITECTURE.md` for the fractal-side design that motivates most
items).

**Scoping rule:** ngio-collections is a generic RFC-8 collections library and
must not know about Fractal. Every item below is generic collection
functionality; all Fractal semantics — provenance, tags, derive, task
changesets, filters, contexts — stay downstream in `fractal-collections-tools`.

**Already addressed** by the in-flight refactor (working tree /
`feat/improve-write-api`), not re-requested here: `new_node(children=...)`,
variadic `add(*children)` / `add_ref(*stubs)`, `Node.ref_stub()`,
`Node.require_id()` / `require_document_url()`, `Node.ref_path`. See also
`ngio_collections_migration_friction.md` — the companion ergonomics report;
this document supersedes it where they overlap.

Items are tiered: Tier 1 = small unblocking fixes, Tier 2 = ergonomics,
Tier 3 = subsystem proposals that deserve their own design conversation.

---

## Tier 1 — small unblocking fixes

### 1.1 `origin_url` on node construction

**Motivation.** A process sometimes needs to graft a node into an in-memory
tree while recording that the node lives in a document the process never read.
Fractal's server is the concrete case: it folds task-reported updates into its
copy of the collection without any access to the data store, and each grafted
node must still report the on-disk `document_url` so later consumers can
locate it. Today `new_node` always produces a detached node (`origin_url` is
set only by the read path), so this requires bypassing the facade and
hand-building `NodeRecord` / `NodeTree` / `wrap_node` from the private `graph`
layer (`fractal-collections-tools/src/fractal_collections_tools/_updates.py:34-56`,
with an apologetic comment).

**Sketch.**

```python
new_node(node_type, *, id=None, name=None, attributes=None,
         children=None, ref=None, origin_url: str | None = None) -> Node
# or, keeping the constructor pure:
Node.with_origin(url: str) -> Node
```

Generic story: reconstructing trees from serialized descriptions of documents
without IO (caches, mirrors, transport).

**Unblocks.** Deleting fractal's `NodeRecord` workaround and every
`ngio_collections.graph` import in fractal code.

### 1.2 Built-in `MemoryStore`

**Motivation.** The store protocol (`io/store/_protocols.py`) is already
minimal and byte-level — `get(url) -> bytes`, `put(url, bytes)`,
`delete(url)` — so an in-memory implementation is trivial, but everyone has to
write their own. Fractal's POC server holds the collection as
`{url: document}` (an honest stand-in for a DB table of documents); tests
everywhere want the same thing.

**Sketch.**

```python
class MemoryStore:  # satisfies WritableStore
    def __init__(self, initial: Mapping[str, bytes] | None = None,
                 *, read_only: bool = False): ...
    async def get(self, url: str) -> bytes: ...
    async def put(self, url: str, data: bytes) -> None: ...
    async def delete(self, url: str) -> None: ...
    def items(self) -> Iterator[tuple[str, bytes]]: ...   # inspection/snapshot
```

**Unblocks.** Fractal's server document-DB becomes
`open_inlined(url, store=MemoryStore(...))` with no shim; cheap hermetic tests
for everyone.

### 1.3 Stub-id contract (findability of cross-document children)

**Motivation.** Exploration shows reference stubs read by `open` carry the
child's local id when the on-disk stub has one (`resolve/_build.py:218-228`),
so `doc.find(id)` can locate a cross-document child in a single-document open.
But this is undocumented, doc-root stubs may legally omit `id`, and downstream
code has already guessed wrong: fractal removes cross-doc children
*positionally* on the assumption stubs are unfindable by id
(`fractal-collections-tools/src/fractal_collections_tools/_ops.py:132-150`).

**Ask.** Document the guarantee: stubs written by `create` / `ref_stub` carry
the child's id; `find(id)` resolves them in single-document opens; and
`remove()` works uniformly on reference stubs. If a stub can lack an id
(doc-root references), state exactly when.

**Unblocks.** Deleting fractal's positional-removal workaround; downstream
code that can rely on id-addressing across document boundaries.

### 1.4 Facade completeness after the refactor

**Motivation.** Fractal currently imports from two non-facade paths:
`ngio_collections.models` (`BaseAttribute`, `ReferenceObj`, `BaseObj`) and
`ngio_collections.graph` (`ROOT`, `NodeRecord`, `NodeTree`). The `models`
names are in fact already re-exported at top level — that one is fractal-side
homework, not an ngio ask. The `graph` imports become unnecessary once 1.1
lands.

**Ask.** After the refactor: everything a downstream library legitimately
needs is importable from `ngio_collections` top level, and `graph` / `resolve`
are explicitly documented as private (e.g. a line in the README and/or
`_`-prefixed subpackages).

---

## Tier 2 — ergonomics

### 2.1 Combined merge+drop, and/or a batch-edit session

**Motivation.** Every edit is tree-in/tree-out and returns a new *root*
handle, so any pre-existing handle goes stale. A merge-then-drop of attributes
therefore needs a re-`find` between the two calls
(`_updates.py:107-115`, `_ops.py:154-185` in fractal-collections-tools), and N
consecutive edits pay N full node-map copies.

**Sketch — smallest form** (covers most real cases):

```python
node.set_attrs(attrs, *, drop: Sequence[str] = ()) -> Node
```

**Sketch — fuller form**, a batch session backed by the internal `Evolver`
(`graph/_pmap.py:97`) that already exists as a build accelerator:

```python
with tree.edit() as tx:            # handles inside tx stay valid
    tx[node_id].set_attrs({...})
    tx[other_id].add(child)
new_root = tx.result               # one new tree, one map rebuild
```

**Unblocks.** Downstream appliers (fractal's update appliers being one) stop
carrying handle-invalidation bookkeeping; multi-edit operations get O(n)
instead of O(k·n).

### 2.2 `attach(child)` — auto-deciding embed vs reference

**Motivation.** Callers currently branch on whether the child is detached
(→ `add`, embed inline) or document-backed (→ `ref_stub` + `add_ref`), e.g.
fractal's `_ops.add_node`. The decision is fully determined by the child's
state; the library can make it. (Also proposed in
`ngio_collections_migration_friction.md`; re-endorsed here.)

**Sketch.**

```python
node.attach(*children: Node) -> Node   # embed if detached, link if document-backed
```

### 2.3 Externalize-and-link as one verb

**Motivation.** "Write this node as its own document and link a reference
stub into its parent's document" is the fundamental operation for growing a
multi-document collection, and today it is a hand-rolled sequence: `create` →
`open` → build stub → `open` parent doc → `add_ref` → `save` — roughly six IO
calls and three failure points (fractal's `write_and_link`,
`scripts/workflow1/workflow.py:72-85`). ngio's own ROADMAP already names this
`Resolver.write`.

**Sketch.**

```python
async def externalize(parent: Node, child: Node, destination: str,
                      store=None, *, overwrite: bool = False) -> Node
# writes child as its own document at destination, links a stub into
# parent's document, saves the parent document, returns the updated parent root
```

**Unblocks.** Fractal's store applier handles an add-node update in one call;
fewer partially-applied failure states for everyone.

---

## Tier 3 — subsystem proposals (design conversations, not demands)

### 3.1 Per-document write-back of resolved trees (`save_tree`)

**Motivation.** This is ngio's own design (DESIGN.md §11, ROADMAP M5 future
work), currently unimplemented: `open_inlined` trees are `mode="resolved"` and
rejected by `save` (`api/_api.py:190`), so the only persistence path for a
resolved view is the whole-snapshot `save_inlined`. The natural workflow —
edit an inlined multi-document view, then persist *only the documents that
changed* — has no direct support. Fractal's store applier is exactly this
consumer, and the workflow1 rewrite is a ready-made test bed.

**Ask.** Prioritize it in the refactor.

**Sketch.**

```python
save_tree(view: Node, store=None) -> list[str]   # URLs of documents rewritten
```

Requires tracking dirtiness by home document (which document each edited node
came from) — pairs with 3.2.

### 3.2 Document fingerprints / cheap change detection

**Motivation.** Any consumer that mirrors a collection (cache, index, DB)
needs to detect that a document changed without re-reading everything. Today
the store protocol has no `stat` / `head` / `exists`, no etag, no content
hash, and no mtime exposure; change detection is full re-read plus content
compare (fractal currently pays an O(dataset) canonical comparison per task
for this). ngio's ROADMAP already lists "optional dirty tracking".

**Sketch.** An optional protocol extension plus a content-hash fallback:

```python
@runtime_checkable
class StatStore(ReadableStore, Protocol):
    async def stat(self, url: str) -> StoreStat

@dataclass(frozen=True)
class StoreStat:
    etag: str | None
    mtime: float | None
    size: int | None

def fingerprint(doc_bytes: bytes) -> str   # canonical content hash, resolve layer
```

(The canonical-content point matters: raw bytes are not stable across JSON
serializers, as ngio's own `io/_json` docstring notes — the fingerprint should
hash parsed-canonical content, not bytes.)

**Unblocks.** Per-document drift detection and conditional re-ingest for any
mirroring consumer.

### 3.3 Generic serializable tree-patch language

**Motivation.** Fractal's core mechanism (see `ARCHITECTURE.md`) is "one
mutation language, two appliers": a JSON-serializable changeset applied
identically to an in-memory tree and to a document store, so two copies of a
collection agree by construction. The Fractal-specific verbs (derive,
provenance, tags) stay downstream — but the substrate is as generic as JSON
Patch: add node, remove node, set/drop attributes, add reference. It pairs
naturally with 3.1 (the store applier is `save_tree`-shaped) and 3.2. Today
ngio has no patch/diff/changeset machinery of any kind; edits exist only as
Python method calls.

**Sketch.**

```python
Patch = AddNode | RemoveNode | SetAttributes | AddReference   # pydantic, discriminated

apply(tree: Node, patches: Sequence[Patch]) -> Node            # in-memory
apply_to_store(store, patches: Sequence[Patch]) -> list[str]   # document-granular
```

**Framing.** Lowest-pressure ask of the list: Fractal will build this
downstream first (per `ARCHITECTURE.md`) and offer it for upstreaming once
proven in practice. Flagging it now only so the refactor doesn't make it
harder (e.g. keep node construction, attribute edit, and reference-linking
primitives reachable enough that a patch applier can be written against the
public surface).

---

## Explicit non-asks

Fractal deliberately does **not** ask ngio to know about: provenance and tag
semantics, derive-with-provenance, task/changeset/workflow concepts, or the
filter/context selection language. All of that stays in
`fractal-collections-tools`.

## Fractal-side homework (independent of ngio)

- Switch `BaseAttribute` / `ReferenceObj` / `BaseObj` imports from
  `ngio_collections.models` to the top-level facade (already public).
- Delete all `ngio_collections.graph` imports once 1.1 lands.
- Retire the positional-removal workaround in `_ops.py` once 1.3 is
  documented (stubs are id-findable today; the workaround's assumption is
  stale).
