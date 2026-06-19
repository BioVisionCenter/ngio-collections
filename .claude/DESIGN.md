# ngio-collections-py — Preliminary Design

**Status:** draft · 2026-06-11 · **partly superseded by the functional rewrite
(see banner)**
**Context:** Greenfield successor to the `fractal-collections-tools` 
(/Users/locerr/Projects/Fractal/fractal-v3-prototyping/fractal-collections-tools)
prototype (an implementation of the OME-NGFF RFC-8 *Collections* draft). This document
records what the prototype got right, what it got wrong, and the architecture
this package starts from. 

---

## Implementation note — functional rewrite (2026-06-19)

The shipped package took a **functional / immutable** direction that supersedes
several specifics below. The **rationale still holds** (RFC-8 round-trip
fidelity, lazy resolution, document-granular saves, async-native core,
URL-addressed stores, mixed-store as the eventual goal, graceful degradation of
unknown types/attributes). What changed in the implementation:

- **Single frozen node layer, not a Stored/Resolved split (§11).** Nodes are
  frozen Pydantic values (`Node` / `RefNode` and the `Collection*`/`Multiscale*`
  subtypes); editing returns a NEW tree and never mutates the source. There is
  no `StoredNode`/`ResolvedNode` pair and no `models/nodes.py` / `resolved.py`.
- **Provenance is `PrivateAttr` on the node** (`_document`, and `_origin` on a
  collapsed boundary — an `Origin`/`NodeMetaInfos` snapshot), carried only via
  `model_copy`. The §5 merge rule lives in one place — `merge` / `split` in
  `models._base` — and `split` inverts the merge by origin (§9.4).
- **No registry.** Node type is chosen by the `type` discriminator with a
  graceful fallback to generic `Node`/`RefNode` (`build_node` / `build_ref_node`
  / `build_any_node`). `NodeRegistry` / `DEFAULT_REGISTRY` / validation-context
  registration (§2.6, §3.4) are not implemented.
- **No typed `attrs` view and no attribute model classes** (§3.5, §7).
  `attributes` stays a raw `dict[str, JsonValue]` for round-trip fidelity;
  `PlateAttribute` / `LabelObj` / `SinglescaleNode` etc. do not exist.
- **No sync facade / `ngio_collections.api`** (§5). The Resolver is async; use
  `asyncio.run(...)`.
- **Resolver surface is `inline` / `create` / `save` / `delete_subtree`** (not
  `open` / `children` / `resolve_tree` / `save_tree`). `MetadataDocument` is a
  Protocol over one file (`content` / `store` / `url` + `deserialize_payload` /
  `serialize_payload`), not a root-bearing object with `form`/`version`/`stub_path`.

The authoritative module map is **§8 (Module layout)** and the architecture
overview is **§4**, both updated to the rewrite. Sections §2–§3, §5 (API
sketch / sync API), §7, and §11 are kept as historical design narrative; read
them through this banner.

---

## 1. Goals

- A faithful, round-trip-safe implementation of RFC-8 collection metadata:
  parse, validate, navigate, edit, and write back.
- **Large remote collections are the primary eventual use case.** The design
  is async-first for that reason — even though the current scope is
  local-only (see the scope note below).
- **Mixed-store collections** are a first-class scenario in the design: e.g.
  raw images on HTTP (read-only), derived segmentations on the local
  filesystem (writable), referenced from one collection tree.
- Extensible by third-party packages: new node types can be registered
  without forking.
- Graceful degradation: unknown node types, unknown attributes, and
  custom-prefixed fields survive a read–modify–write cycle untouched.

### Current scope (revised 2026-06-11: simplicity over completeness)

The first iteration implements the full local story only: parse, validate,
navigate, edit, and save collections on the local filesystem. Remote
(`FsspecStore`) and mixed-store (`RouterStore`) support are deferred — the
`FsspecStore` interface exists as a skeleton so the design stays honest;
`RouterStore` is design-only (§6), with no code yet. Nothing remote
is implemented. The Store/Resolver core stays `async def` regardless, because
retrofitting async later is the hard direction (§3.2). Everything deferred is
listed in §10 and in ROADMAP.md's future-work section.

### Non-goals (for the first iteration)

- Reading or writing array data. This package handles *metadata documents
  only*; the Store moves bytes of JSON, nothing else.
- A fully typed RFC-5 coordinate-transformation union. Coordinate models stay
  minimal and permissive while the spec is moving.
- Whole-tree dirty tracking / `save_tree()`. Saves are explicit and
  document-granular (see §4).

---

## 2. Decisions carried over from the prototype

These were deliberate in the prototype and remain in force:

1. **`id` is required on nodes** — a deliberate deviation from the RFC draft,
   where `id` is optional. `name` is optional (`str | None`).
2. **Resolution is lazy.** Opening a collection reads exactly one metadata
   document; path-bearing stubs are only fetched on demand.
3. **Saves are document-granular.** Editing a node rewrites only its owning
   document, never the whole tree. Externalized children are re-emitted as
   path stubs.
4. **All byte IO goes through the Store boundary.** Models, parsing, and
   serialization are pure; the Store is the only IO surface.
5. **Stores are URL-addressed, not rooted.** `get(url)` over full URLs (unlike
   Zarr's rooted store abstraction). This is what makes mixed-store routing
   pure composition (§6) and lets the document cache be globally coherent.
6. **Registry fallback to a generic node.** An unregistered `type` parses as
   an opaque `BaseNode` rather than failing, per the RFC's
   graceful-degradation rules.
7. **`extra="allow"` everywhere** so unknown/custom-prefixed fields round-trip.

---

## 3. What the prototype got wrong (and the corrections)

### 3.1 Provenance lived in `id()`-keyed side tables → first-class `MetadataDocument`

The prototype's `Resolver` tracked which metadata document each node came
from, its stub path, and its parent in dicts keyed by Python `id(node)`.
Two failure modes:

- `id()` is only unique among *live* objects: after GC, a new node can reuse
  an address and silently inherit another node's provenance.
- Any ordinary Pydantic operation (`model_copy()`, re-validation,
  dump/re-parse) creates a new object and silently severs provenance;
  `save()` then fails with an unhelpful error.

A secondary symptom: "document" never existed as a type. `version` sat on
`BaseNode` with a comment apologizing that it only means anything on document
roots, and provenance was a bare `Origin` record.

**Correction:** a first-class `MetadataDocument` type is the unit of provenance,
serialization, and saving:

```python
class MetadataDocument:
    root: BaseNode
    url: str                        # full URL of the metadata document
    form: Literal["json", "zarr"]   # standalone *.json vs zarr.json envelope
    version: str                    # the `ome` version; OFF the node model
    stub_path: Path | None          # how the parent document references this
                                    # one; None for a top-level document

    def serialize(self) -> dict     # pure; emits stubs for externalized children
    def serialize_bytes(self) -> bytes
```

Node-level provenance is a **`PrivateAttr` back-reference** on the node:
`_document: MetadataDocument | None` (and `_parent: BaseNode | None`), set during
parsing. Private attrs don't serialize, so the models stay spec-pure on the
wire, but provenance survives ordinary object references and GC — no identity
maps.

Defined semantics for copies: `model_copy()` and re-validation produce a
*detached* node (`_document is None`). Detachment is explicit and predictable
instead of a silent latent bug.

### 3.2 Sync-first with "async later" → async-native, sync facade

The prototype knew remote collections were the point and even shaped
`resolve_tree` breadth-first "so a future async variant can fetch a frontier
concurrently" — paying the design cost without the benefit. Retrofitting
async onto a sync core is the hard direction.

**Correction:** `Store` and `Resolver` are `async def` native. A thin sync
facade (`ngio_collections.sync`, a loop-runner wrapper for scripts and
REPL use) is deferred to future work (§10); until it exists, scripts use
`asyncio.run()`.

### 3.3 In-place stub swapping → non-mutating resolution

The prototype's `resolve(stub)` mutated the parent's `nodes` list to swap the
stub for the resolved subtree. Convenient, but it bypassed the parent's
validators, surprised anyone still holding the stub reference, and made
concurrent frontier resolution racy.

**Correction:** resolution never mutates the parsed tree. The tree stays
exactly as parsed (stubs in place); resolution state lives in the Resolver's
URL-keyed `MetadataDocument` cache. Navigation goes through the resolver:

- `resolver.resolve(stub) -> MetadataDocument` — fetch (or hit cache) and return the
  target document.
- `resolver.children(node) -> list[BaseNode]` — the node's children with
  stubs transparently replaced by their resolved document roots.
- `resolver.resolve_tree(doc) -> list[MetadataDocument]` — breadth-first
  cache warming: every reachable document fetched (each frontier
  concurrently), trees untouched, stubs in place.
- `resolver.inline(doc) -> MetadataDocument` — the one exception, and an
  explicit copy-building one (never the default behavior of resolving): a
  NEW document in which every metadata stub is collapsed into a copy of its
  resolved subtree, applying the §5 attribute merge. The input tree, the
  cached documents, and the cache itself stay untouched.

### 3.4 Singleton registries → registries via validation context

Global mutable singletons meant tests could leak registrations into each
other and two registry configurations (e.g. two spec versions) couldn't
coexist in one process. The `model_fields["type"].default` introspection for
registration keys was also fragile.

**Correction:** registries are plain objects. A module-level
`DEFAULT_REGISTRY` keeps ergonomics; the node `PlainValidator` reads the
registry from Pydantic's validation context
(`model_validate(..., context={"registry": ...})`), falling back to the
default. Registration takes an explicit type key:

```python
registry.register("multiscale", MultiscaleNode)
```

Each `Resolver` is constructed with (or defaults to) a registry and threads
it through every parse.

### 3.5 Detached attribute copies → attribute view with write-back

`get_attribute()` returned a freshly validated copy; mutating it and
forgetting `set_attribute()` silently did nothing. The raw
`attributes: dict[str, JsonValue]` stays (round-trip fidelity for unknown
attributes), but access goes through a small view that validates on read and
writes back on assignment:

```python
plate = node.attrs[PlateAttribute]        # typed, validated view
node.attrs[PlateAttribute] = plate        # explicit write-back
PlateAttribute in node.attrs              # membership
```

### 3.6 One serialization path

The prototype emitted spec JSON in two places (`to_spec_dict` on the base
model and `_dump_node` in the document codec) and rebuilt the json/zarr
envelope a third time inside `save()`. Here, `MetadataDocument.serialize()` is the
single emission path; everything else delegates to it.

Stub emission needs no callback plumbing: while dumping, a child whose
`_document` is set (and differs from the document being dumped) is emitted as
a stub using that document's `stub_path`.

---

## 4. Architecture overview

```
┌──────────────────────────────────────────────────────────┐
│  models/_base.py   pure Pydantic: frozen Node / RefNode  │
│                    (+ Collection/Multiscale subtypes),   │
│                    PathObj, the §5 merge/split rule, and  │
│                    the functional edit engine. No IO.    │
├──────────────────────────────────────────────────────────┤
│  _document.py      MetadataDocument Protocol + Json/Zarr  │
│                    impls: pure (de)serialize of ONE       │
│                    metadata file's `ome` payload.         │
├──────────────────────────────────────────────────────────┤
│  _resolver.py      async Resolver: inline / create /      │
│                    save / delete_subtree. URL-keyed       │
│                    document cache. The only Store caller. │
├──────────────────────────────────────────────────────────┤
│  store/            ReadableStore / WritableStore protocols│
│                    (_protocols), zero-dep LocalStore      │
│                    (_local), FsspecStore skeleton (_fsspec)│
└──────────────────────────────────────────────────────────┘
```

Dependency rule: each layer imports only downward. Models never import the
document layer; the document layer never imports the store. Editing is
functional — every edit returns a new frozen tree; the parsed source is never
mutated.

---

## 5. API sketch

```python
import ngio_collections as ngc

resolver = ngc.Resolver(ngc.LocalStore())

doc = await resolver.open("/data/segmentations/experiment-1/collection.json")
root = doc.root                                  # CollectionNode

for child in await resolver.children(root):      # stubs resolved on demand
    print(child.type, child.name)

seg = root.nodes[1]
seg.attrs[LabelsAttribute] = labels              # typed write-back
await resolver.save(seg._document or doc)        # rewrites ONE document
```

Once remote/mixed-store support lands (§10), the only change is the store
passed to the Resolver:

```python
store = ngc.RouterStore(
    routes={
        "https://idr.example.org/": ngc.FsspecStore("https"),   # read-only
        "/data/segmentations/":     ngc.LocalStore(),           # writable
    },
)
```

### Resolver surface

```python
class Resolver:
    def __init__(self, store: ReadableStore, *,
                 registry: NodeRegistry = DEFAULT_REGISTRY): ...

    async def open(self, url: str) -> MetadataDocument
    async def resolve(self, stub: BaseNode) -> MetadataDocument
    async def children(self, node: BaseNode) -> list[BaseNode]
    async def resolve_tree(self, doc: MetadataDocument, *,
                           max_depth: int | None = None,
                           on_error: Literal["skip", "raise"] = "skip",
                           ) -> list[MetadataDocument]
    async def inline(self, doc: MetadataDocument, *,
                     max_depth: int | None = None,
                     on_error: Literal["skip", "raise"] = "skip",
                     ) -> MetadataDocument
    async def save(self, doc: MetadataDocument) -> None
```

### Attribute merge across resolution edges

A path-bearing stub may carry its own `attributes` (e.g. annotating a
multiscale that lives on a read-only store). `inline()` is where the merge
is materialized: when a stub is collapsed into its resolved subtree, the
collapsed node carries the target root's attributes overlaid by the stub's
own — **shallow, key-level, stub wins** (the stub annotates the reference;
the nearer scope overrides) — and the stub's `id`/`name`. The rule has a single
home in `models._base`: `merged_attributes(stub, target)` computes the overlay,
`merge(stub, target)` materializes the collapsed boundary node (recording an
`Origin` so the merge is invertible), and `split(node)` inverts it by origin on
write-back (§9.4).

`inline()` is copy-building end to end: the input tree, the cached
documents, and the resolver cache are never touched, and the result is a
derived artifact (not cached; the top document wins on
`url`/`form`/`version`). Surviving data paths declared in non-top documents
are rebased to absolute URLs so the inlined document stays navigable — the
trade-off being that it is not relocatable. Writes stay explicit and
document-granular: assign into `stub.attributes` (parent document) or the
resolved root's `attributes` (target document) and `save()` the owning
document — the stub side is exactly how to annotate read-only data. A stub
pointing at plain data (a data leaf, as in `resolve_tree`) has no target to
merge; under the default `on_error="skip"` it survives as a stub.

`max_depth` bounds the collapse, counting resolution hops from the top
document exactly like `resolve_tree` (`0` collapses nothing — a pure copy;
`1` only the top document's own stubs; `None`, the default, everything). A
stub at the depth boundary is never fetched: it survives as a stub with its
attributes verbatim — the §5 merge happens only at collapse — and its path
rebased like any surviving path, so the partially inlined tree stays
navigable (and a cycle past the boundary is simply never reached).

`resolve_tree()` returns every document reached (the input first) and warms
the cache; `max_depth` counts resolution hops. A stub whose path points at
plain data (a singlescale's Zarr array) is a *data leaf*: its
`FileNotFoundError` / `NotOmeDocumentError` is skipped under the default
`on_error="skip"`; any other error always raises.

Deferred surface (§10): `write()` (externalizing a node into a new
document), and the sync facade.

`save()` keeps the prototype's zarr behavior: read–modify–write of
`zarr.json`, touching only the `attributes.ome` key.

### Sync convenience API (`ngio_collections.api`)

Four functions over the async core, for scripts and notebooks —
deliberately not a mirrored facade (that stays deferred, §10):

```python
open_collection(url, resolver=None, *,
                max_depth=None, on_error="skip") -> CollectionNode
open_multiscale(url, resolver=None, *,                # direct URL only
                max_depth=None, on_error="skip") -> MultiscaleNode
write_collection(collection, url, resolver=None, *,
                 relativize=True) -> CollectionRef
write_multiscale(multiscale, url, resolver=None, *,
                 relativize=True) -> MultiscaleRef
```

Single-document semantics on both sides: the readers return the `inline()`d
tree as one node (§5 merge applied, data leaves kept with absolute paths),
forwarding `max_depth` / `on_error` to both the `resolve_tree()` warming
pass and `inline()` — `max_depth` yields a partially inlined tree whose
boundary stubs survive with rebased paths, and `on_error="raise"` makes the
open strict (note it also trips on ordinary data paths, so it suits
metadata-only trees);
the writers deep-copy the input (detaching any foreign provenance so
children embed rather than re-emit as stubs) and `save()` ONE document,
with the json/zarr form inferred from the URL.

The writers return a detached *reference form* node (`CollectionRef` /
`MultiscaleRef`, §7) — `{type, id, name, path}` for the document just
written (`ZarrPath` to the group directory for the zarr form, `JsonPath`
for the json form). Grafting the stub into a parent's
`nodes` composes collections bottom-up by reference instead of embedding;
parent-edge attributes go on the stub and win on inlined reads (§5 merge).
With `relativize` (the default) absolute node paths are rewritten relative
to the destination URL on write where scheme and host match (the textual
inverse of the resolution `urljoin`, so resolution is unchanged and the
document becomes relocatable); already-relative paths are kept verbatim and
cross-store references stay absolute (§6). `relativize=False` writes paths
verbatim, for deliberately pinned same-store absolute references.

Each call submits to a
persistent event loop on a daemon background thread
(`run_coroutine_threadsafe`), so the functions work inside an already
running loop (Jupyter) where `asyncio.run()` would fail. A shared
`resolver` argument reuses the document cache across calls; the same
`Resolver` instance must not also be driven directly from a user loop.

---

## 6. Store layer

### Protocols

```python
class ReadableStore(Protocol):
    async def get(self, url: str) -> bytes:
        """MUST raise FileNotFoundError if absent."""

class WritableStore(ReadableStore, Protocol):
    async def put(self, url: str, data: bytes) -> None: ...

class StoreReadOnlyError(PermissionError):
    """Raised by put() on a read-only backend. Part of the contract."""
```

Read-only is a first-class concept because the mixed-store scenario demands
it: `save()` on a node whose document lives on the HTTP side must fail
*early* with a clear error, not arbitrarily deep in a backend.

### RouterStore (design only — implementation deferred)

Implements the store protocol; dispatches by **longest URL-prefix match**
(not scheme — two S3 buckets with different credentials, or one read-only
HTTPS host, are realistic routes). Because stores are URL-addressed, the
Resolver is entirely unaware of routing, and its document cache stays
coherent across backends.

### Implementations

- `LocalStore` — zero-dependency filesystem store (plain paths and
  `file://`). The only implemented store in the current scope.
- `FsspecStore` *(skeleton — implementation deferred)* — default for
  anything remote; wraps `fsspec` `AsyncFileSystem`, which brings
  http/s3/gcs/local and protocol dispatch in one dependency.

### Cross-store references

Mechanically, resolution joins a stub's relative path against the URL of the
*declaring document* (`urljoin`), and an absolute URL in `path` passes
through untouched — so a local document can reference `https://…/raw.zarr`
with no special machinery. Portability asymmetry, to be documented for
users: local→remote absolute references are fine; remote→local
(`file:///…`) references make a collection machine-specific. The natural
mixed layout is a **local collection root** referencing remote raw data
absolutely and local derived data relatively.

---

## 7. Models layer (mostly unchanged from the prototype)

- `BaseObj`: camelCase aliasing, `populate_by_name`, `extra="allow"`.
- `BaseNode`: `type`, `id` (pattern-validated, required), `name`
  (`str | None`, optional), `path: ZarrPath | JsonPath | None`, raw `attributes` dict,
  `attrs` typed view (§3.5). **No `version` field** — that lives on
  `MetadataDocument`.
- Built-in node types with their structural validators:
  - `CollectionNode` — exactly one of `nodes`/`path`.
  - `MultiscaleNode` — exactly one of `nodes`/`path`; full (inlined) form
    requires `coordinateSystems` in attributes; path-stub form carries none.
  - `SinglescaleNode` — requires `coordinateTransformations` in attributes
    when no `path` is set (the externalized form may defer them).
- Reference forms (added 2026-06-12): `CollectionRef(CollectionNode)` /
  `MultiscaleRef(MultiscaleNode)` narrow the stub form into its own type —
  `path` required, `nodes` forbidden — so stub-ness is visible in signatures
  and `isinstance`, while a ref still IS-A its full class (the spec has one
  `type` for both forms; serialization is identical). `validate_node` routes
  path-bearing dicts to the type's `ref_form` (a `ClassVar` hook on
  `BaseNode`, available to custom registered types); the full classes stay
  permissive for hand-built path-bearing instances. `SinglescaleNode` has no
  ref form: its `path` doubles as the inlined form's data pointer.
- MetadataDocument-level invariant, checked at parse and serialize time: node ids
  unique within a single document.
- Attributes: `plate`, `well`, `acquisition`, `labels`, `scene`,
  `coordinateSystems`, `coordinateTransformations` — same shapes as the
  prototype; coordinate models stay loose (RFC-5 axes/transform details
  untyped via `extra="allow"`).

---

## 8. Module layout

```
src/ngio_collections/
    __init__.py          # the public surface (19 names): Resolver, stores +
                         # protocols, node/path model types
    _document.py         # MetadataDocument Protocol + Json/Zarr impls
    _resolver.py         # async Resolver (inline / create / save / delete_subtree)
    models/
        __init__.py      # re-exports the model public subset
        _base.py         # BaseObj; frozen Node / RefNode (+ Collection/Multiscale
                         # subtypes); ZarrPath / JsonPath / PathObj; NodeState;
                         # the §5 merge/split rule; build_* constructors;
                         # the functional edit engine (update/add/remove/…)
    store/
        __init__.py      # re-exports the store public subset
        _protocols.py    # ReadableStore, WritableStore, StoreReadOnlyError
        _local.py        # LocalStore (zero-dep)
        _fsspec.py       # FsspecStore skeleton (optional dependency)
```

Every module under `models/` and `store/` is private (`_*.py`); the public
names are re-exported from each subpackage's `__init__` and from the top-level
`ngio_collections`. The merge engine, node constructors, provenance dataclasses
(`Origin` / `NodeMetaInfos`), and the document layer are intentionally NOT part
of the public surface.

---

## 9. Open spec questions (RFC-8)

Tracked here because the implementation takes a position on each:

1. **Absolute URIs in `path`.** Mixed-store collections depend on a document
   referencing another document by absolute URL. Does the spec's `path`
   definition permit absolute URIs, or only relative paths? Worth a sentence
   in the RFC blessing or forbidding it. (Implementation currently allows it.)
2. **`id` optionality.** The spec makes `id` optional; this package requires
   it (carried-over deviation). If the spec keeps `id` optional, decide
   whether to soften this to "generated on read".
3. **Conditional attribute requirements.** The prototype's reading: the
   `coordinateSystems` MUST on multiscale applies to the full inlined form
   only, and a path-bearing singlescale may defer `coordinateTransformations`
   to its target document. Confirm against the final wording.
4. **`attributes` on a path-bearing node.** The spec is silent on what
   `attributes` declared on a stub mean when the target document's root also
   carries attributes. Position taken here (§5): they merge — shallow,
   key-level, stub wins — because the stub annotates the reference and must
   be able to override metadata on read-only targets; the merged view's
   `id`/`name` are likewise the stub's. Worth an RFC clarification,
   including whether a stub may satisfy an attribute MUST (e.g.
   `coordinateSystems`) on the parent side. **Write-back position (§11):** the
   merge is invertible — *by origin, edge keeps overrides*. An edited key that
   originated on the stub is written back to the parent edge (the target keeps
   its original, shadowed value); every other current key — including
   brand-new ones — is written to the home (target) document; a removed key
   drops from both layers.

---

## 10. Out of scope, revisit later

Deferred 2026-06-11 (simplicity over completeness; mirrors ROADMAP.md's
future-work section):

- `FsspecStore` implementation — remote collections over http/s3/gcs; the
  interface skeleton is in place.
- `RouterStore` implementation / mixed-store collections, including
  documenting the cross-store portability asymmetry (§6).
- The full sync facade (`ngio_collections.sync`), a loop-runner wrapper
  mirroring the whole Resolver surface. Partially superseded 2026-06-12 by
  the four-function `ngio_collections.api` module (§5); for everything
  else, `asyncio.run()`.
- `Resolver.write(node, url, stub_path=...)` — externalizing a node into a
  new document (collection restructuring). The *composition* direction —
  building documents bottom-up by reference — is covered 2026-06-12 by the
  sync writers returning reference stubs (§5); restructuring an opened,
  provenance-bearing tree stays deferred.
- `_stub_for` limitation: a *grafted* externalized child (a resolved root
  placed into another document's `nodes`) re-emits only
  `type`/`id`/`name`/`path`, so parent-side attributes of grafted children
  are not captured (per-edge data cannot live on the shared
  `MetadataDocument`). Stubs kept in the parsed tree — the normal case —
  round-trip their attributes untouched, as do the *detached* stubs returned
  by the sync writers (which sidestep, not fix, this limitation). Revisit
  alongside `write()`.
- Attribute-registry extensibility — removed as dead code (the `attrs` view
  takes attribute classes directly, §3.5); re-add only if a use case appears.
- Conformance test suite against the RFC examples (the prototype's test
  fixtures are a starting point); revisit the §9 open questions then.
- Docs, `py.typed`, and a PyPI release — releasing waits until remote
  support exists, since remote is the primary use case.
- Concurrency limits / request batching in `FsspecStore` (semaphore around
  `gather` when frontier sizes get large).
- Optional dirty tracking on top of document-granular saves.
- A typed RFC-5 transformation union once that spec settles.

---

## 11. Stored/Resolved node split (2026-06-18)

The headline use case — open an inlined collection, edit it in memory, write it
back keeping the file structure and attributes correct — was blocked by
`BaseNode` wearing three hats: the on-disk wire model, the parsed/provenance
node, and (post-`inline`) the merged editing surface. The merge was lossy (a
key present on both stub and target lost the target's value) and the inlined
tree was one synthetic document, so saving it flattened the whole collection
into one file. The fix splits the node into two layers.

- **`StoredNode`** (`models/base.py`, `models/nodes.py`) — the faithful
  Pydantic mirror of one document's node (`extra="allow"`, structural
  validators, `path`/ref forms, `_document`/`_parent` provenance). The
  pre-split names (`BaseNode`, `CollectionNode`, …) stay as back-compat
  aliases. Each stored type gets a `resolved_form` ClassVar (mirroring
  `ref_form`); `None` ⇒ the generic fallback.
- **`ResolvedNode`** (`models/resolved.py`) — produced ONLY by `inline()`: a
  plain (non-Pydantic) mutable working model holding private references back
  into the stored layer (`_home` document, `_stored` node, `_edge` →
  `EdgeRef`), with the ergonomic edit API (`attrs`, `add`, `pop`, `walk`,
  `find`, `target_path`). Typed twins exist for the built-ins; custom types
  fall back to the generic `ResolvedNode` (or opt into a twin via
  `resolved_form`). No on-mutation validation — invariants re-apply once, at
  `to_stored_root()`.

Resolution vocabulary, made consistent: `inline()` (verb) → `ResolvedNode`
(fully-resolved result); `resolve()` / `resolve_tree()` are the lazy partial
steps that leave stubs in place (§3.3). So `inline()` reframes as
**StoredNode-tree → ResolvedNode-tree**, and write-back as
**ResolvedNode-tree → StoredNode-documents**.

**`Resolver.save_tree(root)`** is the inverse of `inline()`: it partitions the
resolved tree by home document (each boundary node — `_edge` set — roots its
own document and is re-emitted as a path stub in its parent), rebuilds each
document via `to_stored_root` (attributes un-merged by origin per §9.4; added
nodes embedded in their parent's document; unknown `extra` keys carried through
from the cached original `StoredNode` by `model_copy`), and saves only the
documents whose serialized payload changed. A tree saved with no edits writes
nothing. **`Resolver.delete_subtree(node)`** (with a new `WritableStore.delete`)
is the destructive companion to `pop()`'s in-memory unlink: deletes the
external file(s) of the boundary nodes in a subtree (call before popping).

Sync API: `open_collection` / `open_multiscale` now return the `ResolvedNode`
root; `write_collection_back` / `write_multiscale_back` wrap `save_tree`. The
compose-by-reference writers (`write_collection` / `write_multiscale`) keep
taking `StoredNode`s — the document-granular `save()` editing path is
unchanged.

Partly retires §10's `write()` item: bottom-up composition (writers) and
write-back of an opened tree (`save_tree`) are now covered; restructuring by
*externalizing* an added node into its own new document stays deferred (added
nodes embed in their parent's document).
