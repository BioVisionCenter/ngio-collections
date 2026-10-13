"""The public `Node` handle: a positioned, typed view over a `NodeTree`.

A `Node` pairs a `NodeTree` with a `NodeId` — "which graph" and "which node in
it" — and carries all the behaviour users reach for: navigation (`walk` / `find`
/ `children` / `parent`), capability lenses (`node[WellAttribute]`), validation,
`ref`, state, and the functional edits. Edits return a *new* `Node` over a *new*
`NodeTree`; the handle itself is immutable by convention. The underlying record
is inert data — the handle is exactly the v5 "node you hold and call methods on".

Construction is handle-rooted and fluent: `new_node(...)` seeds a detached root,
`add` grafts a child subtree, and positioned edits return the updated handle.
Typed subclasses (`CollectionNode` / `MultiscaleNode` plus a generic `Node`
fallback) come from the registry by `record.type`.
"""

from __future__ import annotations

import builtins
from dataclasses import replace
from typing import Iterator, Mapping, Sequence, TypeVar

from ngio_collections._types import JSONValue
from ngio_collections.graph import (
    ROOT,
    NodeTree,
    NodeId,
    NodeRecord,
    Reference,
    TreeBuilder,
    is_ancestor,
)
from ngio_collections.models._config import NodeStateError
from ngio_collections.models._paths import (
    DocPath,
    JsonPath,
    ZarrPath,
    format_for,
    meta_url,
)
from ngio_collections.models._paths import ZARR_METADATA_FILE
from ngio_collections.models._references import ReferenceObj, new_id
from ngio_collections.models.attributes import AnyAttribute
from ngio_collections.validate import (
    ValidationError,
    ValidatorType,
    get_attribute,
    has_attribute,
    read_attribute,
    validate,
)

A = TypeVar("A", bound=AnyAttribute)


class Node:
    """A positioned, typed handle over one node of a `NodeTree`."""

    __slots__ = ("_tree", "_id")

    def __init__(self, collection: NodeTree, node_id: NodeId) -> None:
        """Bind this handle to `node_id` within `collection`."""
        self._tree = collection
        self._id = node_id

    # -- identity & state ---------------------------------------------------

    @property
    def tree(self) -> NodeTree:
        """The node-tree this handle views."""
        return self._tree

    @property
    def node_id(self) -> NodeId:
        """This node's structural key within the collection."""
        return self._id

    @property
    def record(self) -> NodeRecord:
        """The inert record this handle points at."""
        return self._tree.record(self._id)

    @property
    def type(self) -> str:
        """The structural type tag (`collection` / `multiscale` / …)."""
        return self.record.type

    @property
    def name(self) -> str | None:
        """The optional display name."""
        return self.record.name

    @property
    def id(self) -> str | None:
        """The declared id (a UUID), or `None` for a reference node."""
        return self.record.id

    @property
    def attributes(self) -> Mapping[str, JSONValue]:
        """The raw body (every non-structural key; validate via `node[Attr]`)."""
        return self.record.attributes

    @property
    def is_reference(self) -> bool:
        """Whether this node is a `{type, ref, path?}` pointer, not a declaration.

        A reference has no id, name or body of its own; the node it points at
        (inside the document at `ref_path`, or this document for a bare ref)
        brings those. `open_inlined` replaces resolvable references in place.
        """
        return self.record.is_reference

    @property
    def is_detached(self) -> bool:
        """Whether this node is in memory only (no backing document)."""
        return self.record.origin_url is None

    @property
    def document_url(self) -> str | None:
        """The URL of the document backing this node, or `None` if detached."""
        return self.record.origin_url

    @property
    def ref_path(self) -> str | None:
        """The `href` this reference stores, or `None` (not a reference / bare ref)."""
        ref = self.record.ref
        return None if ref is None or ref.path is None else ref.path.href

    def require_id(self) -> str:
        """Return this node's declared id, narrowing it to `str`.

        Raises:
            NodeStateError: If the node is a reference (it declares no id).
        """
        record = self.record
        if record.id is None:
            target = None if record.ref is None else record.ref.ref
            raise NodeStateError(
                f"node is a reference and declares no id; it points at {target!r}"
            )
        return record.id

    def _require_declaration(self, what: str) -> None:
        """Reject `what` on a reference node (it has no name or body to edit)."""
        if self.record.ref is not None:
            raise NodeStateError(
                f"cannot {what} a reference node: it carries only type, ref and "
                "path; edit the referenced node in its own document instead"
            )

    def require_document_url(self) -> str:
        """Return the URL of this node's backing document, narrowing it to `str`.

        Raises:
            NodeStateError: If the node is detached (no backing document).
        """
        url = self.record.origin_url
        if url is None:
            raise NodeStateError(
                f"node {self.record.id!r} is detached; persist it first"
            )
        return url

    def ref(self) -> ReferenceObj:
        """Return a portable `{type, ref, path}` locator for this node on disk.

        For a declaration this points at the node inside its origin document.
        For a reference node it is the pointer the node already carries (its
        `path`, if any, is as stored — relative to `document_url`).

        Raises:
            NodeStateError: If a declaration is detached (no backing document).
        """
        record = self.record
        if record.ref is not None:
            return ReferenceObj(type=record.type, ref=record.ref.ref, path=record.ref.path)
        return ReferenceObj(
            type=record.type,
            ref=self.require_id(),
            path=reference_path(self.require_document_url()),
        )

    def ref_stub(self) -> Node:
        """Return a detached reference stub locating this node in its origin document.

        The stub is the same shape `create`/`save` return: attach it under a
        parent with `add_ref` to link this node's document rather than embed its
        subtree. It carries only `type`, `ref` (this node's id) and `path`; it
        declares no id of its own, so reach it structurally (`children()`,
        `walk()`) rather than by `find`.

        Raises:
            NodeStateError: If the node is detached or is itself a reference.
        """
        return _reference_stub(self, self.require_document_url())

    # -- navigation ---------------------------------------------------------

    def walk(self) -> Iterator[Node]:
        """Yield this node and every descendant, depth-first in order."""
        for node_id in self._tree.walk(self._id):
            yield wrap_node(self._tree, node_id)

    def children(self) -> tuple[Node, ...]:
        """Return this node's direct children."""
        return tuple(
            wrap_node(self._tree, child) for child in self._tree.children_ids(self._id)
        )

    def parent(self) -> Node | None:
        """Return the parent handle, or `None` at the root."""
        if not self._id:
            return None
        return wrap_node(self._tree, self._id[:-1])

    def ancestors(self) -> Iterator[Node]:
        """Yield the parent, grandparent, … up to and including the root."""
        node_id = self._id
        while node_id:
            node_id = node_id[:-1]
            yield wrap_node(self._tree, node_id)

    def find(self, id: str) -> Node | None:
        """Return the first node in this subtree that *declares* `id`.

        Reference nodes declare nothing, so a cross-document child left in
        place by `open` is not found here even though it points at `id`; reach
        it structurally via `children()` / `walk()` (or `tree.referrers(id)`).
        After `open_inlined` the declaration it pointed at is in its place and
        findable.
        """
        for key in self._tree.find(id):
            if key == self._id or is_ancestor(self._id, key):
                return wrap_node(self._tree, key)
        return None

    def subtree(self) -> Node:
        """Return this node's subtree re-rooted into its own detached tree.

        A located handle (`walk`/`find`) is already scoped to its subtree but
        stays part of the whole tree (its edits return the whole-tree root, and
        `parent()` climbs out). `subtree()` instead extracts an *independent*,
        detached `NodeTree` whose root is this node — so it can be edited in
        isolation (edits return the subtree root) or written as a new document
        with `create()`. The source tree is untouched.
        """
        src = self._tree
        root = src.record(self._id)
        builder = TreeBuilder(
            replace(
                root,
                origin_url=None,
                children=() if root.children is not None else None,
            )
        )
        remap: dict[NodeId, NodeId] = {self._id: ROOT}
        for node_id in src.walk(self._id):
            if node_id == self._id:
                continue
            record = src.record(node_id)
            remap[node_id] = builder.add_child(
                remap[node_id[:-1]], replace(record, origin_url=None)
            )
        return wrap_node(builder.finish(), ROOT)

    # -- capability lenses --------------------------------------------------

    # `type` is a property on this class, so it shadows the builtin in these
    # annotations — spell it `builtins.type` to subscript the real type.
    def __getitem__(self, attr_type: builtins.type[A]) -> A:
        """Validate and return this node's value for `attr_type`."""
        return read_attribute(self.record, attr_type)

    def get_attr(self, attr_type: builtins.type[A]) -> A | None:
        """Return this node's `attr_type` value, or `None` if absent."""
        return get_attribute(self.record, attr_type)

    def has(self, attr_type: builtins.type[A]) -> bool:
        """Return whether this node carries `attr_type`'s capability."""
        return has_attribute(self.record, attr_type)

    def __contains__(self, attr_type: object) -> bool:
        """Support `SomeAttribute in node` membership tests."""
        key = getattr(attr_type, "key", None)
        return isinstance(key, str) and key in self.record.attributes

    # -- validation ---------------------------------------------------------

    def validate(
        self,
        validators: Sequence[ValidatorType],
        *,
        raise_on_error: bool = False,
    ) -> list[ValidationError]:
        """Run `validators` over this node and its descendants; return failures."""
        return validate(self, validators, raise_on_error=raise_on_error)

    # -- functional edits ---------------------------------------------------
    #
    # Edits are positioned on the located node but return the *root* handle of
    # the new collection (tree-in, tree-out): `root.find("img").set_attr(x)`
    # yields the whole updated tree, so it round-trips through `create`/`save`.
    # Reads (walk/find/children/parent) return located handles instead.

    def _root(self, collection: NodeTree) -> Node:
        """Wrap the root of `collection` (the tree-out of every edit)."""
        return wrap_node(collection, ROOT)

    def set_attr(self, value: AnyAttribute) -> Node:
        """Set the typed attribute `value` (keyed by its model's `key`)."""
        self._require_declaration("set attributes on")
        dumped = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        return self._root(self._tree.set_attrs(self._id, {value.key: dumped}))

    def set_attrs(
        self,
        values: Mapping[str, JSONValue],
        *,
        drop: Sequence[str | builtins.type[AnyAttribute]] = (),
    ) -> Node:
        """Merge raw `values` into this node's attribute bag, removing `drop`.

        `drop` (str keys or attribute classes) is applied after the merge, in
        one edit — so a merge-then-drop needs no re-`find` between two calls.
        """
        self._require_declaration("set attributes on")
        return self._root(self._tree.set_attrs(self._id, values, drop=_attr_keys(drop)))

    def drop_attrs(self, *keys: str | builtins.type[AnyAttribute]) -> Node:
        """Remove `keys` from this node's bag (str keys or attribute classes)."""
        self._require_declaration("drop attributes from")
        return self._root(self._tree.drop_attrs(self._id, _attr_keys(keys)))

    def rename(self, name: str | None) -> Node:
        """Set this node's display name."""
        self._require_declaration("rename")
        return self._root(self._tree.rename(self._id, name))

    def add(self, *children: Node) -> Node:
        """Graft each child's subtree under this node, in order; return the tree root."""
        tree = self._tree
        for child in children:
            tree = _graft(tree, self._id, child._tree, child._id)
        return self._root(tree)

    def add_ref(self, *stubs: Node) -> Node:
        """Attach reference stubs (from `create`/`save`/`ref_stub`) under this node."""
        for stub in stubs:
            if not stub.is_reference:
                raise ValueError("add_ref expects reference nodes (e.g. from create)")
        return self.add(*stubs)

    def remove(self) -> Node:
        """Remove this node from its parent; return the tree root."""
        if not self._id:
            raise ValueError("cannot remove the root node")
        return self._root(self._tree.remove(self._id))


def _attr_keys(keys: Sequence[str | builtins.type[AnyAttribute]]) -> tuple[str, ...]:
    """Resolve attribute classes to their `key`, passing str keys through."""
    return tuple(k if isinstance(k, str) else k.key for k in keys)


def reference_path(url: str) -> DocPath:
    """Return the `DocPath` a reference stores to point at the document at `url`.

    JSON points at the document URL; Zarr points at the group directory (the URL
    without the trailing `zarr.json`).
    """
    url = meta_url(url)
    suffix = "/" + ZARR_METADATA_FILE
    if url.endswith(suffix):
        href = url[: -len(suffix)]
        return ZarrPath(format=format_for(href), href=href)
    if url.endswith(".json"):
        return JsonPath(format=format_for(url), href=url)
    return ZarrPath(format=format_for(url), href=url)


def _graft(
    collection: NodeTree, parent_key: NodeId, other: NodeTree, other_node: NodeId
) -> NodeTree:
    """Copy `other`'s subtree at `other_node` under `parent_key`, recursively."""
    record = other.record(other_node)
    seed = replace(record, children=() if record.children is not None else None)
    collection, key = collection.add_child(parent_key, seed)
    for child in other.children_ids(other_node):
        collection = _graft(collection, key, other, child)
    return collection


def new_node(
    node_type: str,
    *,
    id: str | None = None,
    name: str | None = None,
    attributes: Mapping[str, JSONValue] | None = None,
    children: Sequence[Node] | None = None,
    ref: Reference | None = None,
    origin_url: str | None = None,
) -> Node:
    """Create a detached collection rooted at a new node and return its handle.

    A node with a `ref` is a reference stub (`type` + `ref` + `path` only: no
    `id`, `name` or `attributes`). Otherwise it is a declaration — a branch
    whose `children` subtrees are grafted in order (and can keep growing via
    `add`) — whose `id` is minted with `new_id()` when not given.

    `origin_url` is provenance: pass it to reconstruct a node known to live in
    the document at that URL without reading it (a cache, a mirror, a serialized
    description). It makes the node document-backed rather than detached — it
    drives `is_detached`, `document_url`, `ref()` / `ref_stub()`, and `save`
    routing (`create()` rejects document-backed trees) — and the caller asserts
    the document actually exists. Grafted `children` keep their own origins.
    """
    if children is not None and ref is not None:
        raise ValueError("a reference stub is a leaf; it cannot take children")
    if ref is None and id is None:
        id = new_id()
    record = NodeRecord(
        type=node_type,
        id=id,
        name=name,
        attributes=dict(attributes) if attributes else {},
        children=None if ref is not None else (),
        ref=ref,
        origin_url=None if origin_url is None else meta_url(origin_url),
    )
    node = wrap_node(NodeTree.of(record), ROOT)
    return node.add(*children) if children else node


def _reference_stub(node: Node, url: str) -> Node:
    """Build a detached reference stub locating `node` in the document at `url`.

    The stub is `{type, ref, path}`: `node`'s type, its declared id as `ref`,
    and the path to `url`. It declares nothing of its own.
    """
    return new_node(
        node.type, ref=Reference(ref=node.require_id(), path=reference_path(url))
    )


# -- typed-subclass registry (populated by the composition root) ------------


class CollectionNode(Node):
    """Handle for a `collection` node."""


class MultiscaleNode(Node):
    """Handle for a `multiscale` node (a leaf: `scales` live in its body)."""


class NodeTypeRegistry:
    """Maps a structural `type` tag to the `Node` subclass that wraps it."""

    def __init__(self) -> None:
        """Start an empty registry (generic `Node` is the fallback)."""
        self._by_type: dict[str, type[Node]] = {}

    def register(self, node_type: str, cls: type[Node]) -> None:
        """Bind `node_type` to handle class `cls`."""
        self._by_type[node_type] = cls

    def wrap(self, collection: NodeTree, node_id: NodeId) -> Node:
        """Wrap `node_id` in its registered handle class, or generic `Node`."""
        cls = self._by_type.get(collection.record(node_id).type, Node)
        return cls(collection, node_id)


NODE_TYPES = NodeTypeRegistry()


def wrap_node(collection: NodeTree, node_id: NodeId) -> Node:
    """Wrap `node_id` in its typed handle (generic `Node` if unregistered).

    This is the seam `register_node_type` consumers go through; its `NodeTree` /
    `NodeId` parameters come from an existing handle (`node.tree`, `node.node_id`)
    rather than from the internal `graph` package.
    """
    return NODE_TYPES.wrap(collection, node_id)


def register_node_types(registry: NodeTypeRegistry = NODE_TYPES) -> NodeTypeRegistry:
    """Register the built-in typed handles on `registry` (the default registry)."""
    registry.register("collection", CollectionNode)
    registry.register("multiscale", MultiscaleNode)
    return registry


def register_node_type(
    node_type: str, cls: type[Node], *, registry: NodeTypeRegistry = NODE_TYPES
) -> type[Node]:
    """Register a custom `node_type` → handle `cls` (data still lives in attributes).

    Lets nodes of `node_type` wrap as `cls` (e.g. for `isinstance` / type-specific
    helpers) instead of the generic `Node`; unregistered types degrade to `Node`.
    """
    registry.register(node_type, cls)
    return cls
