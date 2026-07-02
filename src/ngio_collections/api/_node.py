"""The public `Node` handle: a positioned, typed view over a `NodeTree`.

A `Node` pairs a `NodeTree` with a `NodeId` — "which graph" and "which node in
it" — and carries all the behaviour users reach for: navigation (`walk` / `find`
/ `children` / `parent`), capability lenses (`node[WellAttribute]`), validation,
`ref`, state, and the functional edits. Edits return a *new* `Node` over a *new*
`NodeTree`; the handle itself is immutable by convention. The underlying record
is inert data — the handle is exactly the v5 "node you hold and call methods on".

Construction is handle-rooted and fluent: `new_node(...)` seeds a detached root,
`add` grafts a child subtree, and positioned edits return the updated handle.
Typed subclasses (`CollectionNode` / `MultiscaleNode` / `SinglescaleNode` plus a
generic `Node` fallback) come from the registry by `record.type`.
"""

from __future__ import annotations

import builtins
from dataclasses import replace
from typing import Iterator, Mapping, Sequence, TypeVar

from pydantic import JsonValue

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
from ngio_collections.models._paths import DocPath, JsonPath, ZarrPath, meta_url
from ngio_collections.models._paths import ZARR_METADATA_FILE
from ngio_collections.models._references import ReferenceObj
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
        """The pristine local id."""
        return self.record.id

    @property
    def attributes(self) -> Mapping[str, JsonValue]:
        """The raw attribute bag (validate a capability via `node[Attr]`)."""
        return self.record.attributes

    @property
    def is_reference(self) -> bool:
        """Whether this node is an unresolved cross-document reference."""
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
        """The document path this reference stores, or `None` if not a reference."""
        ref = self.record.ref
        return None if ref is None else ref.path.path

    def require_id(self) -> str:
        """Return this node's local id, narrowing it to `str`.

        Raises:
            NodeStateError: If the node carries no id.
        """
        id = self.record.id
        if id is None:
            raise NodeStateError("node has no id; it cannot be referenced")
        return id

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
        """Return a portable `{id, path}` locator for this node on disk.

        Raises:
            NodeStateError: If the node is detached or carries no id.
        """
        return ReferenceObj(
            id=self.require_id(), path=reference_path(self.require_document_url())
        )

    def ref_stub(self) -> Node:
        """Return a detached reference stub locating this node in its origin document.

        The stub is the same shape `create`/`save` return: attach it under a
        parent with `add_ref` to link this node's document rather than embed its
        subtree. It carries this node's local id, so it serializes with an `id`
        and stays findable by `find(id)` wherever it lands. Unlike `ref()`, no
        local id is required — a stub whose `id` is `None` points at the
        document root (and is only structurally addressable).

        Raises:
            NodeStateError: If the node is detached (no backing document).
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
        """Return the first node in this subtree whose local id is `id`.

        This covers unresolved reference stubs too: a stub minted by `create` /
        `save` / `ref_stub` carries its target root's local id, so a
        cross-document child is findable by id in a single-document `open` and
        can be handled uniformly (e.g. `remove()`d). The exception is an
        id-less stub — a plain doc-root reference, legal on disk — which is not
        id-addressable; reach it structurally via `children()` / `walk()`.
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
        dumped = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        return self._root(self._tree.set_attrs(self._id, {value.key: dumped}))

    def set_attrs(self, values: Mapping[str, JsonValue]) -> Node:
        """Merge raw `values` into this node's attribute bag."""
        return self._root(self._tree.set_attrs(self._id, values))

    def drop_attrs(self, *keys: str | builtins.type[AnyAttribute]) -> Node:
        """Remove `keys` from this node's bag (str keys or attribute classes)."""
        resolved = tuple(k if isinstance(k, str) else k.key for k in keys)
        return self._root(self._tree.drop_attrs(self._id, resolved))

    def rename(self, name: str | None) -> Node:
        """Set this node's display name."""
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


def reference_path(url: str) -> DocPath:
    """Return the `DocPath` a reference stores to point at the document at `url`.

    JSON points at the document URL; Zarr points at the group directory (the URL
    without the trailing `zarr.json`).
    """
    url = meta_url(url)
    suffix = "/" + ZARR_METADATA_FILE
    if url.endswith(suffix):
        return ZarrPath(path=url[: -len(suffix)])
    if url.endswith(".json"):
        return JsonPath(path=url)
    return ZarrPath(path=url)


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
    attributes: Mapping[str, JsonValue] | None = None,
    children: Sequence[Node] | None = None,
    ref: Reference | None = None,
) -> Node:
    """Create a detached collection rooted at a new node and return its handle.

    A node with a `ref` is a leaf reference stub; otherwise it is a branch whose
    `children` subtrees are grafted in order (and can keep growing via `add`).
    """
    if children is not None and ref is not None:
        raise ValueError("a reference stub is a leaf; it cannot take children")
    record = NodeRecord(
        type=node_type,
        id=id,
        name=name,
        attributes=dict(attributes) if attributes else {},
        children=None if ref is not None else (),
        ref=ref,
    )
    node = wrap_node(NodeTree.of(record), ROOT)
    return node.add(*children) if children else node


def _reference_stub(node: Node, url: str) -> Node:
    """Build a detached reference stub locating `node` in the document at `url`.

    The stub carries `node`'s local id both as its own `id` (so it serializes
    with one and stays addressable via `find` wherever it is grafted) and as the
    `Reference.id` to locate inside the target document. A node without an id
    yields an id-less doc-root stub.
    """
    return new_node(
        node.type,
        id=node.id,
        name=node.name,
        ref=Reference(path=reference_path(url), id=node.id),
    )


# -- typed-subclass registry (populated by the composition root) ------------


class CollectionNode(Node):
    """Handle for a `collection` node."""


class MultiscaleNode(Node):
    """Handle for a `multiscale` node."""


class SinglescaleNode(Node):
    """Handle for a `singlescale` node."""


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
    """Wrap `node_id` in its typed handle (generic `Node` if unregistered)."""
    return NODE_TYPES.wrap(collection, node_id)


def register_node_types(registry: NodeTypeRegistry = NODE_TYPES) -> NodeTypeRegistry:
    """Register the built-in typed handles on `registry` (the default registry)."""
    registry.register("collection", CollectionNode)
    registry.register("multiscale", MultiscaleNode)
    registry.register("singlescale", SinglescaleNode)
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
