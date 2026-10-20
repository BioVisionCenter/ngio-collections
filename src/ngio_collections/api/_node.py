"""The public `Node` handle: a positioned, typed view over a `NodeTree`.

A `Node` pairs a `NodeTree` with a `NodeId` ("which graph" and "which node in
it") and carries all the behaviour users reach for: navigation (`walk` / `find`
/ `children` / `parent`), trait lenses (`node[WellTrait]`), node fields,
validation, `ref`, state, and the functional edits. Edits return a *new* `Node`
over a *new* `NodeTree`; the handle itself is immutable by convention. The
underlying record is inert data.

Construction is handle-rooted and fluent: `new_node(...)` / `new_collection` /
`new_multiscale` seed a detached root, `add` grafts a child subtree,
`add_external` attaches the declaring entry of a node that lives in its own
document, and positioned edits return the updated handle. Typed subclasses
(`CollectionNode` / `MultiscaleNode` plus a generic `Node` fallback) come from
the registry by `record.type`.

RFC-8 revision 1 never embeds a multiscale in a collection (§8.1): `add`
rejects a multiscale child that carries no `path`. Create the image document
first (`create`), then attach the returned stub.
"""

from __future__ import annotations

import builtins
from dataclasses import replace
from typing import Iterator, Mapping, Sequence, cast

from ngio_collections._types import JSONValue
from ngio_collections.graph import (
    ROOT,
    Fields,
    NodeId,
    NodeRecord,
    NodeTree,
    Traits,
    TreeBuilder,
    is_ancestor,
)
from ngio_collections.models._config import NodeStateError
from ngio_collections.models._ids import is_uuid, new_id
from ngio_collections.models._manifest import is_extension_type
from ngio_collections.models._multiscale import (
    CoordinateSystem,
    MultiscaleFields,
    Scale,
)
from ngio_collections.models._paths import DocPath, meta_url
from ngio_collections.models._references import ReferenceObj
from ngio_collections.models.traits import BaseTrait, TraitType
from ngio_collections.validate import (
    ValidationError,
    ValidatorType,
    get_trait,
    has_trait,
    read_trait,
    trait_key,
    validate,
)

BUILTIN_NODE_TYPES = frozenset({"collection", "multiscale"})
"""Keyword node types; anything else must be an extension URI."""


class Node:
    """A positioned, typed handle over one node of a `NodeTree`."""

    __slots__ = ("_tree", "_id")

    def __init__(self, tree: NodeTree, node_id: NodeId) -> None:
        """Bind this handle to `node_id` within `tree`."""
        self._tree = tree
        self._id = node_id

    # -- identity & state ---------------------------------------------------

    @property
    def tree(self) -> NodeTree:
        """The node tree this handle views."""
        return self._tree

    @property
    def node_id(self) -> NodeId:
        """This node's structural key within the tree."""
        return self._id

    @property
    def record(self) -> NodeRecord:
        """The inert record this handle points at."""
        return self._tree.record(self._id)

    @property
    def type(self) -> str:
        """The structural type (`collection` / `multiscale` / an extension URI)."""
        return self.record.type

    @property
    def name(self) -> str | None:
        """The optional, free-form display name."""
        return self.record.name

    @property
    def id(self) -> str:
        """The node's UUID."""
        return self.record.id

    @property
    def traits(self) -> Traits:
        """The raw traits, indexed by trait type (validate one via `node[Trait]`)."""
        return self.record.traits

    @property
    def fields(self) -> Fields:
        """The raw node-type fields (`coordinate_systems`, `scales`, …)."""
        return self.record.fields

    @property
    def path(self) -> DocPath | None:
        """The path object of an external node, or `None` if embedded."""
        return self.record.path

    @property
    def ref_path(self) -> str | None:
        """The `href` of an external node's path, or `None` if embedded."""
        path = self.record.path
        return None if path is None else path.href

    @property
    def is_external(self) -> bool:
        """Whether this node carries a `path` rather than embedded children.

        True for a declaring entry whose document was not resolved, and for a
        node whose `path` locates plain data.
        """
        return self.record.is_external

    @property
    def is_detached(self) -> bool:
        """Whether this node is in memory only (no backing document)."""
        return self.record.origin_url is None

    @property
    def document_url(self) -> str | None:
        """The URL of the document backing this node, or `None` if detached."""
        return self.record.origin_url

    @property
    def extension_manifest(self) -> tuple[dict, ...]:
        """The `extension_manifest` of this node's document (empty if detached)."""
        url = self.record.origin_url
        return () if url is None else self._tree.manifests.get(url, ())

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
        """Return a portable typed reference to this node in its document.

        Raises:
            NodeStateError: If the node is detached.
        """
        return ReferenceObj(
            type=self.type,
            ref=self.id,
            path=DocPath.for_url(self.require_document_url()),
        )

    def ref_local(self) -> ReferenceObj:
        """Return a same-document typed reference (`{type, ref}`) to this node."""
        return ReferenceObj(type=self.type, ref=self.id)

    def stub(self) -> Node:
        """Return a detached declaring entry (`{type, id, name, path}`) for this node.

        The stub is the same shape `create` / `save` return: attach it under a
        parent with `add_external` to link this node's document rather than
        embed its subtree. It carries this node's UUID, as the revision requires
        the entry and the document root to share one id.

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
        """Return the first node in this subtree whose UUID is `id`.

        This covers external nodes too: a declaring entry carries the UUID of
        the document it points at, so a cross-document child is findable by id
        in a single-document `open`.
        """
        for key in self._tree.find(id):
            if key == self._id or is_ancestor(self._id, key):
                return wrap_node(self._tree, key)
        return None

    def find_by_name(self, name: str) -> tuple[Node, ...]:
        """Return every node in this subtree named `name` (names are not unique)."""
        return tuple(n for n in self.walk() if n.name == name)

    def subtree(self) -> Node:
        """Return this node's subtree re-rooted into its own detached tree.

        A located handle (`walk`/`find`) is already scoped to its subtree but
        stays part of the whole tree (its edits return the whole-tree root, and
        `parent()` climbs out). `subtree()` instead extracts an *independent*,
        detached `NodeTree` whose root is this node, so it can be edited in
        isolation or written as a new document with `create()`.
        """
        src = self._tree
        root = src.record(self._id)
        builder = TreeBuilder(
            replace(
                root,
                origin_url=None,
                edge=None,
                children=() if root.children is not None else None,
            )
        )
        remap: dict[NodeId, NodeId] = {self._id: ROOT}
        for node_id in src.walk(self._id):
            if node_id == self._id:
                continue
            record = src.record(node_id)
            remap[node_id] = builder.add_child(
                remap[node_id[:-1]], replace(record, origin_url=None, edge=None)
            )
        return wrap_node(builder.finish(), ROOT)

    # -- trait and field lenses ---------------------------------------------

    # `type` is a property on this class, so it shadows the builtin in these
    # annotations; spell it `builtins.type` to subscript the real type.
    def __getitem__(self, trait_type: builtins.type[TraitType]) -> TraitType:
        """Validate and return this node's trait of `trait_type`.

        Raises:
            KeyError: If the trait is absent.
        """
        return read_trait(self.record, trait_type)

    def get_trait(self, trait_type: builtins.type[TraitType]) -> TraitType | None:
        """Return this node's validated trait of `trait_type`, or `None` if absent."""
        return get_trait(self.record, trait_type)

    def has_trait(self, trait: builtins.type[BaseTrait] | str) -> bool:
        """Return whether this node carries `trait` (a model class or type string)."""
        return has_trait(self.record, trait)

    def __contains__(self, trait: object) -> bool:
        """Support `WellTrait in node` and `"well" in node` membership tests."""
        if isinstance(trait, str):
            return trait in self.record.traits
        if isinstance(trait, builtins.type) and issubclass(trait, BaseTrait):
            return has_trait(self.record, trait)
        return False

    def get_field(self, key: str) -> JSONValue | None:
        """Return the node-type field `key`, or `None` if absent."""
        return self.record.fields.get(key)

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
    # the new tree (tree-in, tree-out): `root.find(uuid).set_trait(x)` yields
    # the whole updated tree, so it round-trips through `create`/`save`. Reads
    # (walk/find/children/parent) return located handles instead.

    def _root(self, tree: NodeTree) -> Node:
        """Wrap the root of `tree` (the tree-out of every edit)."""
        return wrap_node(tree, ROOT)

    def set_trait(self, trait: BaseTrait | Mapping[str, JSONValue]) -> Node:
        """Upsert one trait (a model or a mapping carrying `type`)."""
        return self._root(self._tree.set_trait(self._id, _trait_dict(trait)))

    def set_traits(self, *traits: BaseTrait | Mapping[str, JSONValue]) -> Node:
        """Upsert several traits in one edit, keyed by their `type`."""
        merged = dict(self.record.traits)
        for trait in traits:
            data = _trait_dict(trait)
            merged[str(data["type"])] = data
        return self._root(self._tree.set_traits(self._id, merged))

    def drop_traits(self, *traits: str | builtins.type[BaseTrait]) -> Node:
        """Remove the given traits (type strings or model classes)."""
        return self._root(
            self._tree.drop_traits(self._id, tuple(trait_key(t) for t in traits))
        )

    def set_fields(self, fields: Mapping[str, JSONValue]) -> Node:
        """Replace this node's node-type fields."""
        return self._root(self._tree.set_fields(self._id, fields))

    def set_field(self, key: str, value: JSONValue) -> Node:
        """Set one node-type field."""
        return self._root(
            self._tree.set_fields(self._id, {**self.record.fields, key: value})
        )

    def set_path(self, path: DocPath | None) -> Node:
        """Make this node external (point it at `path`) or embedded again (`None`).

        Raises:
            NodeStateError: If the node has children; an external node is a leaf.
        """
        record = self.record
        if record.children:
            raise NodeStateError(
                f"node {record.id!r} has children; externalize() it instead"
            )
        updated = replace(record, path=path, children=None if path is not None else ())
        return self._root(self._tree.replace(self._id, updated))

    def rename(self, name: str | None) -> Node:
        """Set this node's display name."""
        return self._root(self._tree.rename(self._id, name))

    def add(self, *children: Node) -> Node:
        """Graft each child's subtree under this node, in order; return the tree root.

        Raises:
            NodeStateError: If a child is a multiscale with no `path`: the
                revision never embeds a multiscale. `create()` its document
                first and attach the returned stub with `add_external`.
        """
        tree = self._tree
        for child in children:
            if child.type == "multiscale" and not child.is_external:
                raise NodeStateError(
                    f"multiscale {child.id!r} has no path; a multiscale is always its "
                    "own document: create() it, then add_external() the stub"
                )
            tree = _graft(tree, self._id, child._tree, child._id)
        return self._root(tree)

    def add_external(self, *stubs: Node) -> Node:
        """Attach declaring entries (from `create` / `save` / `stub`) under this node."""
        for stub in stubs:
            if not stub.is_external:
                raise ValueError(
                    "add_external expects external nodes (e.g. from create)"
                )
        return self.add(*stubs)

    def remove(self) -> Node:
        """Remove this node from its parent; return the tree root."""
        if not self._id:
            raise ValueError("cannot remove the root node")
        return self._root(self._tree.remove(self._id))


def _trait_dict(trait: BaseTrait | Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Return the wire dict for a trait model or mapping (must carry `type`)."""
    if isinstance(trait, BaseTrait):
        return trait.model_dump(mode="json", exclude_none=True)
    data = dict(trait)
    if not isinstance(data.get("type"), str):
        raise ValueError(f"a trait must carry a string `type`: {data!r}")
    return data


def _graft(
    tree: NodeTree, parent_key: NodeId, other: NodeTree, other_node: NodeId
) -> NodeTree:
    """Copy `other`'s subtree at `other_node` under `parent_key`, recursively."""
    record = other.record(other_node)
    seed = replace(record, children=() if record.children is not None else None)
    tree, key = tree.add_child(parent_key, seed)
    for child in other.children_ids(other_node):
        tree = _graft(tree, key, other, child)
    return tree


def _traits_from(traits: Sequence[BaseTrait | Mapping[str, JSONValue]]) -> dict:
    """Index constructor `traits` by type."""
    out: dict[str, JSONValue] = {}
    for trait in traits:
        data = _trait_dict(trait)
        out[str(data["type"])] = data
    return out


def new_node(
    node_type: str,
    *,
    id: str | None = None,
    name: str | None = None,
    traits: Sequence[BaseTrait | Mapping[str, JSONValue]] = (),
    fields: Mapping[str, JSONValue] | None = None,
    children: Sequence[Node] | None = None,
    path: DocPath | None = None,
    origin_url: str | None = None,
) -> Node:
    """Create a detached tree rooted at a new node and return its handle.

    A node with a `path` is an external leaf (a declaring entry); otherwise it is
    a branch whose `children` subtrees are grafted in order (and can keep growing
    via `add`). `id` defaults to a freshly minted UUIDv7.

    `origin_url` is provenance: pass it to reconstruct a node known to live in
    the document at that URL without reading it. It makes the node
    document-backed rather than detached (`is_detached`, `document_url`,
    `ref()` / `stub()`, and `create()` rejecting it) and the caller asserts the
    document actually exists.

    Raises:
        ValueError: If `id` is not a UUID, or `children` are given with `path`.
    """
    if children and path is not None:
        raise ValueError("an external node is a leaf; it cannot take children")
    node_id = new_id() if id is None else id
    if not is_uuid(node_id):
        raise ValueError(f"node id must be a UUID (see new_id()), got {node_id!r}")
    record = NodeRecord(
        type=node_type,
        id=node_id,
        name=name,
        traits=_traits_from(traits),
        fields=dict(fields) if fields else {},
        children=None if path is not None else (),
        path=path,
        origin_url=None if origin_url is None else meta_url(origin_url),
    )
    node = wrap_node(NodeTree.of(record), ROOT)
    return node.add(*children) if children else node


def new_collection(
    *,
    id: str | None = None,
    name: str | None = None,
    traits: Sequence[BaseTrait | Mapping[str, JSONValue]] = (),
    children: Sequence[Node] = (),
) -> Node:
    """Create a detached `collection` node (see `new_node`)."""
    return new_node("collection", id=id, name=name, traits=traits, children=children)


def new_multiscale(
    *,
    coordinate_systems: Sequence[CoordinateSystem | Mapping[str, JSONValue]],
    scales: Sequence[Scale | Mapping[str, JSONValue]],
    id: str | None = None,
    name: str | None = None,
    traits: Sequence[BaseTrait | Mapping[str, JSONValue]] = (),
    path: DocPath | None = None,
) -> Node:
    """Create a detached `multiscale` node with its `coordinate_systems` and `scales`.

    The result is the root of an image document: `create()` it, then attach the
    returned stub to a collection with `add_external`.
    """
    fields = MultiscaleFields(
        coordinate_systems=[
            c if isinstance(c, CoordinateSystem) else CoordinateSystem.model_validate(c)
            for c in coordinate_systems
        ],
        scales=[s if isinstance(s, Scale) else Scale.model_validate(s) for s in scales],
    )
    return new_node(
        "multiscale",
        id=id,
        name=name,
        traits=traits,
        fields=fields.model_dump(mode="json", exclude_none=True),
        path=path,
    )


def _reference_stub(node: Node, url: str) -> Node:
    """Build a detached declaring entry locating `node`'s document at `url`."""
    return new_node(node.type, id=node.id, name=node.name, path=DocPath.for_url(url))


# -- typed-subclass registry (populated by the composition root) ------------


class CollectionNode(Node):
    """Handle for a `collection` node."""


class MultiscaleNode(Node):
    """Handle for a `multiscale` node, with typed access to its fields."""

    @property
    def coordinate_systems(self) -> tuple[CoordinateSystem, ...]:
        """The multiscale's coordinate systems (validated)."""
        raw = self.record.fields.get("coordinate_systems")
        items = raw if isinstance(raw, list) else []
        return tuple(CoordinateSystem.model_validate(c) for c in items)

    @property
    def scales(self) -> tuple[Scale, ...]:
        """The multiscale's scales (validated), coarsest last as written."""
        raw = self.record.fields.get("scales")
        items = raw if isinstance(raw, list) else []
        return tuple(Scale.model_validate(s) for s in items)

    def scale(self, id: str) -> Scale | None:
        """Return the scale declared with UUID `id`, or `None`."""
        return next((s for s in self.scales if s.id == id), None)

    def coordinate_system(self, id: str) -> CoordinateSystem | None:
        """Return the coordinate system declared with UUID `id`, or `None`."""
        return next((c for c in self.coordinate_systems if c.id == id), None)

    def set_scales(self, scales: Sequence[Scale | Mapping[str, JSONValue]]) -> Node:
        """Replace the `scales` field; return the tree root."""
        dumped = [
            (s if isinstance(s, Scale) else Scale.model_validate(s)).model_dump(
                mode="json", exclude_none=True
            )
            for s in scales
        ]
        return self.set_field("scales", cast(JSONValue, dumped))

    def set_coordinate_systems(
        self, systems: Sequence[CoordinateSystem | Mapping[str, JSONValue]]
    ) -> Node:
        """Replace the `coordinate_systems` field; return the tree root."""
        dumped = [
            (
                c
                if isinstance(c, CoordinateSystem)
                else CoordinateSystem.model_validate(c)
            ).model_dump(mode="json", exclude_none=True)
            for c in systems
        ]
        return self.set_field("coordinate_systems", cast(JSONValue, dumped))


class NodeTypeRegistry:
    """Maps a structural `type` to the `Node` subclass that wraps it."""

    def __init__(self) -> None:
        """Start an empty registry (generic `Node` is the fallback)."""
        self._by_type: dict[str, type[Node]] = {}

    def register(self, node_type: str, cls: type[Node]) -> None:
        """Bind `node_type` to handle class `cls`."""
        self._by_type[node_type] = cls

    def wrap(self, tree: NodeTree, node_id: NodeId) -> Node:
        """Wrap `node_id` in its registered handle class, or generic `Node`."""
        cls = self._by_type.get(tree.record(node_id).type, Node)
        return cls(tree, node_id)


NODE_TYPES = NodeTypeRegistry()


def wrap_node(tree: NodeTree, node_id: NodeId) -> Node:
    """Wrap `node_id` in its typed handle (generic `Node` if unregistered).

    This is the seam `register_node_type` consumers go through; its `NodeTree` /
    `NodeId` parameters come from an existing handle (`node.tree`, `node.node_id`)
    rather than from the internal `graph` package.
    """
    return NODE_TYPES.wrap(tree, node_id)


def register_node_types(registry: NodeTypeRegistry = NODE_TYPES) -> NodeTypeRegistry:
    """Register the built-in typed handles on `registry` (the default registry)."""
    registry.register("collection", CollectionNode)
    registry.register("multiscale", MultiscaleNode)
    return registry


def register_node_type(
    node_type: str, cls: type[Node], *, registry: NodeTypeRegistry = NODE_TYPES
) -> type[Node]:
    """Register an extension `node_type` (a URI) → handle `cls`.

    Lets nodes of `node_type` wrap as `cls` (e.g. for `isinstance` / type-specific
    helpers) instead of the generic `Node`; unregistered types degrade to `Node`.

    Raises:
        ValueError: If `node_type` is neither a built-in keyword nor a URI;
            prefixed names such as `myorg:table` are not valid in revision 1.
    """
    if node_type not in BUILTIN_NODE_TYPES and not is_extension_type(node_type):
        raise ValueError(
            f"extension node types are URIs (e.g. 'https://myorg.org/ngff/table'); "
            f"{node_type!r} is neither a built-in type nor a URI"
        )
    registry.register(node_type, cls)
    return cls
