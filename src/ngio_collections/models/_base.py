"""Frozen node models, references, and the functional edit engine.

Pure Pydantic layer: no IO. Nodes are **frozen** (immutable) with `tuple`
children, so a parsed tree is a value that resolution and editing never mutate
— they return new trees. The one piece of provenance that survives is
`_document` (a `PrivateAttr` pointing at the node's on-disk document, if any);
it never serializes and rides along through `model_copy`. The single invariant
every rebuild honors: **edit through `model_copy`, never `model_validate`**, so
`_document` survives untouched.

There are two parallel node hierarchies:

* the **editable** tree (`Node` / `RefNode` and subtypes), returned by
  `Resolver.open`; cross-document children stay unresolved `RefNode` stubs and
  the tree is writable single-document (`create` / `save`);
* the **inlined** tree (`InlinedNode` and subtypes), returned by
  `Resolver.open_inlined`; cross-document stubs are resolved in place. It is
  read-only with respect to its origins (only `save_inlined` snapshots it), but
  still supports the same functional in-memory edits.

A `ReferenceObj` is the portable `{id, type?, path?}` pointer `node.ref()` returns;
`add_ref` turns one into an in-tree stub. The write verbs (`create` / `save` /
`save_inlined`) return the richer typed `RefNode` stub (via `stub_to`) so a
reference can be decorated before it is attached.
"""

from __future__ import annotations

import posixpath
from enum import StrEnum
from collections.abc import Sequence
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    ClassVar,
    Generator,
    Literal,
    Self,
    TypeVar,
    cast,
)
from urllib.parse import urljoin

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainValidator,
    PrivateAttr,
    RootModel,
    SerializeAsAny,
)
from pydantic.alias_generators import to_camel

from ngio_collections.models._registry import NodeRegistry, NodeTypes

if TYPE_CHECKING:
    from ngio_collections._document import MetadataDocument


class BaseObj(BaseModel):
    """Frozen, camelCase-aliased base for non-node OME objects (paths, refs).

    `extra="allow"` round-trips unknown / custom keys. Nodes do *not* use this
    base — see `NodeObj`.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
        frozen=True,
    )


class NodeObj(BaseModel):
    """Frozen, camelCase-aliased base for the node hierarchy and node mixins.

    Identical to `BaseObj` except `extra="forbid"`: a node's structural fields
    are a closed set, so unknown node-level keys are rejected rather than
    silently kept. Arbitrary / custom metadata belongs in a node's `attributes`
    dict (which stays open). Consumers declaring a custom node type build their
    field mixin on this base so the derived variants stay strict.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class NodeStateError(ValueError):
    """A node is in the wrong state for the requested operation.

    Subclasses `ValueError` so callers can keep catching `ValueError`. The
    message points to the API that fits the node's actual state.
    """


class NodeState(StrEnum):
    """How a node relates to on-disk storage (see :attr:`BaseNode.state`)."""

    DETACHED = "detached"  # in memory only, no backing document
    DOCUMENT = "document"  # backed by a document (root or descendant)


# --- paths -----------------------------------------------------------------


def _path_resolve(path: str, document: MetadataDocument | None) -> str:
    """Resolve a stored `path` to an absolute URL for IO.

    The stored value is never rewritten — relative stays relative, absolute stays
    absolute — so a tree can be re-rooted later without rewriting references.

    Args:
        path: The raw path string as stored in the node (relative or absolute).
        document: The owning document, required to resolve relative paths.

    Returns:
        An absolute URL suitable for use with a store.

    Raises:
        ValueError: If `path` is relative but `document` is `None`, or if
            the path format is not recognised.
    """
    if path.startswith("/"):
        return path
    if path.startswith("./"):
        if document is None:
            raise ValueError("Relative paths require a document URL.")
        # urljoin treats the document's last segment as a file and replaces it,
        # so "./A/well.json" resolves against the document's directory.
        return urljoin(document.url, path)
    if path.startswith("http"):
        return path
    raise ValueError(f"Unsupported path: {path}")


class ZarrPath(BaseObj):
    """A `zarr`-typed path reference to an external document."""

    type: Literal["zarr"] = "zarr"
    path: str

    def resolve(self, document: MetadataDocument | None) -> str:
        """Return the absolute URL for this path.

        Args:
            document: Owning document, required for relative paths.

        Returns:
            Absolute URL string.
        """
        return _path_resolve(self.path, document)


class JsonPath(BaseObj):
    """A `json`-typed path reference to an external document."""

    type: Literal["json"] = "json"
    path: str

    def resolve(self, document: MetadataDocument | None) -> str:
        """Return the absolute URL for this path.

        Args:
            document: Owning document, required for relative paths.

        Returns:
            Absolute URL string.
        """
        return _path_resolve(self.path, document)


PathObj = Annotated[ZarrPath | JsonPath, Field(discriminator="type")]


# --- references ------------------------------------------------------------

ID_PATTERN = r"^[a-zA-Z0-9\-_.]+$"

IdStr = Annotated[str, Field(pattern=ID_PATTERN)]


class ReferenceObj(BaseObj):
    """A portable pointer to a node that exists on disk.

    Not a node itself: it carries no attributes and no type — locating the node
    is its whole job. Resolved by loading the document at `path` and finding the
    node whose `id` matches inside it (the resolved node carries the type). A
    `None` path means a reference within the *same* document (resolve `id`
    locally).
    """

    id: IdStr
    path: PathObj | None = None


def reference_to(id: str, document: MetadataDocument) -> ReferenceObj:
    """Build a `ReferenceObj` locating node `id` inside `document`.

    Args:
        id: The id of the node being referenced.
        document: The document that contains the node.

    Returns:
        A `ReferenceObj` with an absolute path of the document's form.
    """
    path_cls = ZarrPath if document.kind == "zarr" else JsonPath
    return ReferenceObj(id=id, path=path_cls(path=document.ref_url))


def stub_to(node: BaseNode, document: MetadataDocument) -> RefNode:
    """Build a typed `RefNode` stub locating `node` inside `document`.

    The stub takes the node's id and type (so `add_ref` keeps the type) with an
    absolute `PathObj` of the document's form and empty overlay attributes ready
    to decorate. Mirrors :func:`reference_to` but returns the richer stub the
    write verbs hand back.

    Args:
        node: The node that was written (provides id and type).
        document: The document it now lives in (provides the path).

    Returns:
        A typed `RefNode` (e.g. `RefMultiscaleNode`) with an absolute path.
    """
    path_cls = ZarrPath if document.kind == "zarr" else JsonPath
    ref_cls = DEFAULT_REGISTRY.get_ref(node.type)
    return ref_cls(id=node.id, type=node.type, path=path_cls(path=document.ref_url))


# --- attributes ------------------------------------------------------------


class _AttributeKey:
    """Mixin declaring the `attributes` dict key an attribute model maps to."""

    key: ClassVar[str]

    @classmethod
    def name_space(cls) -> str | None:
        """Return the `key`'s namespace prefix (before `:`), or `None`."""
        if ":" in cls.key:
            return cls.key.split(":")[0]
        return None


class BaseAttribute(_AttributeKey, BaseObj):
    """Attribute whose value is a JSON object (e.g. `plate`, `well`)."""


ItemType = TypeVar("ItemType")


class BaseListAttribute(_AttributeKey, RootModel[list[ItemType]]):
    """Attribute whose value is a JSON array (e.g. `coordinateSystems`)."""


AnyAttribute = BaseAttribute | BaseListAttribute
AttributeType = TypeVar("AttributeType", bound=AnyAttribute)


# --- nodes -----------------------------------------------------------------


def _set_private(node: BaseNode, name: str, value: Any) -> None:
    """Set a private attr on a frozen node (provenance plumbing only).

    Args:
        node: The frozen node whose private attribute should be mutated.
        name: The `PrivateAttr` field name (e.g. `"_document"`).
        value: The value to assign.
    """
    private = node.__pydantic_private__
    assert private is not None
    private[name] = value


class BaseNode(NodeObj):
    """Common fields, navigation, and functional edits for every node.

    The node protocol every node carries: a required `type`, a required `id`, an
    optional `name`, and an `attributes` dict. `nodes` / `path` are added by the
    concrete hierarchies — embedded (`Node` / `InlinedNode`) carry `nodes`, a
    reference (`RefNode`) carries `path`. Both the editable (`Node` / `RefNode`)
    and inlined (`InlinedNode`) hierarchies derive from this. Every edit method
    returns a new tree built via `model_copy` and never mutates `self`.
    """

    type: str
    id: IdStr
    name: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    # Closest owning document (set after parse / create). None on a detached
    # node, which inherits its parent's document on write-back.
    _document: "MetadataDocument | None" = PrivateAttr(default=None)

    # --- navigation ------------------------------------------------------

    def walk(self) -> Generator[BaseNode, None, None]:
        """Yield this node and every descendant, depth-first in order.

        Yields:
            Each node in the subtree, starting with `self`.
        """
        yield self
        children: tuple[BaseNode, ...] = getattr(self, "nodes", None) or ()
        for child in children:
            yield from child.walk()

    def find(self, *, id: str) -> BaseNode | None:
        """Return the first node in `walk()` order whose `id` matches.

        Args:
            id: The node id to search for.

        Returns:
            The matching node, or `None` if not found.
        """
        return next((n for n in self.walk() if n.id == id), None)

    # --- typed attribute reads -------------------------------------------

    def __contains__(self, attr_type: type[AnyAttribute]) -> bool:
        """True iff this node carries the attribute `attr_type` maps to.

        Args:
            attr_type: An attribute model class (e.g. `PlateAttribute`).

        Returns:
            Whether `attr_type.key` is present in `attributes`.
        """
        return attr_type.key in self.attributes

    def __getitem__(self, attr_type: type[AttributeType]) -> AttributeType:
        """Validate and return this node's value for `attr_type`.

        The raw `attributes` dict stays the source of truth; the requested
        model validates a fresh view of the stored JSON on every read.

        Args:
            attr_type: An attribute model class (e.g. `PlateAttribute`).

        Returns:
            The validated attribute model.

        Raises:
            KeyError: If the node carries no such attribute.
        """
        if attr_type not in self:
            raise KeyError(attr_type.key)
        return attr_type.model_validate(self.attributes[attr_type.key])

    def get_attr(
        self,
        attr_type: type[AttributeType],
        default: AttributeType | None = None,
    ) -> AttributeType | None:
        """Return the validated `attr_type` value, or `default` if absent.

        Args:
            attr_type: An attribute model class (e.g. `PlateAttribute`).
            default: Value to return when the attribute is missing.

        Returns:
            The validated attribute model, or `default`.
        """
        return self[attr_type] if attr_type in self else default

    @property
    def state(self) -> NodeState:
        """How this node relates to storage.

        `DETACHED` = in memory only; `DOCUMENT` = backed by a document.
        """
        return NodeState.DETACHED if self._document is None else NodeState.DOCUMENT

    @property
    def is_detached(self) -> bool:
        """True iff this node has no backing document."""
        return self._document is None

    @property
    def document_url(self) -> str | None:
        """URL of the closest document that owns this node (its 'context')."""
        return self._document.url if self._document is not None else None

    def ref(self) -> ReferenceObj:
        """Return a `ReferenceObj` locating this node on disk.

        The `id` disambiguates the node within its document, so this works for
        any document-backed node (a root or a descendant). The result is a
        portable locator, not an embeddable stub — to attach a reference with
        `add_ref`, use the typed `RefNode` a write verb hands back.

        Returns:
            A portable `{id, path}` pointer to this node.

        Raises:
            NodeStateError: If the node is detached (has no document yet).
        """
        if self._document is None:
            raise NodeStateError(
                f"node {self.id!r} is detached; persist it with create()/save() "
                "before taking a reference"
            )
        return reference_to(self.id, self._document)

    # --- functional edits (return a new root; self is untouched) ----------

    def update(self, *, id: str, fn: Callable[[BaseNode], BaseNode]) -> Self:
        """Replace the node with `id` by `fn(node)`, returning a new tree.

        The only spine-rebuild engine: it rebuilds the path from the root to the
        target via `model_copy` (carrying `_document`), leaving every other
        branch shared with the original. `fn` must itself return a node built
        with `model_copy` so its `_document` survives.

        Args:
            id: The id of the node to replace.
            fn: Callable that receives the current node and returns the replacement.

        Returns:
            A new root with the targeted node replaced; `self` is untouched.

        Raises:
            KeyError: If no node with `id` exists in the tree.
        """
        new, found = _rebuild(self, id, fn)
        if not found:
            raise KeyError(f"no node with id {id!r} in this tree")
        return cast("Self", new)

    def set_attrs(self, *, id: str, values: dict[str, JsonValue]) -> Self:
        """Merge `values` into the `attributes` of node `id`.

        Args:
            id: The id of the node whose attributes should be updated.
            values: Key-value pairs to merge in (existing keys are overwritten).

        Returns:
            A new root with the node's attributes updated.
        """
        return self.update(
            id=id,
            fn=lambda n: n.model_copy(
                update={"attributes": {**n.attributes, **values}}
            ),
        )

    def drop_attrs(self, *, id: str, keys: Sequence[str]) -> Self:
        """Remove `keys` from the `attributes` of node `id`.

        Args:
            id: The id of the node whose attributes should be modified.
            keys: Attribute keys to remove (unknown keys are silently ignored).

        Returns:
            A new root with the specified attribute keys removed.
        """
        return self.update(
            id=id,
            fn=lambda n: n.model_copy(
                update={
                    "attributes": {
                        k: v for k, v in n.attributes.items() if k not in keys
                    }
                }
            ),
        )

    def set_attr(
        self,
        *,
        id: str,
        value: AnyAttribute | JsonValue,
        attr: type[AttributeType] | None = None,
    ) -> Self:
        """Write a typed attribute into node `id`, returning a new tree.

        `value` may be a typed attribute instance (its type supplies the key)
        or a raw JSON value (then `attr` must be given to validate it and locate
        the `attributes` key). The value is validated and dumped spec-shaped
        (`by_alias`, `exclude_none`); the raw dict stays the source of truth, so
        unknown attributes round-trip untouched.

        Args:
            id: The id of the node whose attribute should be set.
            value: A typed attribute instance or its raw JSON form.
            attr: The attribute model class; required when `value` is raw,
                optional (inferred from `value`) when it is a model instance.

        Returns:
            A new root with the node's attribute written.

        Raises:
            TypeError: If `value` is raw and `attr` is not supplied.
        """
        if attr is None:
            if not isinstance(value, _AttributeKey):
                raise TypeError(
                    "set_attr requires `attr` when `value` is not an "
                    "attribute model instance"
                )
            attr = cast("type[AttributeType]", type(value))
        # ty can't match RootModel.model_dump's Self bound through the
        # BaseAttribute | BaseListAttribute typevar bound.
        payload = attr.model_validate(value).model_dump(  # ty: ignore[invalid-argument-type]
            mode="json", by_alias=True, exclude_none=True
        )
        return self.update(
            id=id,
            fn=lambda n: n.model_copy(
                update={"attributes": {**n.attributes, attr.key: payload}}
            ),
        )

    def drop_attr(self, *, id: str, attr: type[AnyAttribute]) -> Self:
        """Remove the attribute `attr` maps to from node `id`.

        Args:
            id: The id of the node whose attribute should be removed.
            attr: The attribute model class whose `key` to drop.

        Returns:
            A new root with the attribute removed (a no-op if absent).
        """
        return self.drop_attrs(id=id, keys=(attr.key,))

    def rename(self, *, id: str, name: str | None) -> Self:
        """Set the `name` of node `id`.

        Args:
            id: The id of the node to rename.
            name: The new name, or `None` to clear it.

        Returns:
            A new root with the node's name updated.
        """
        return self.update(id=id, fn=lambda n: n.model_copy(update={"name": name}))

    def add(self, *, parent_id: str, child: BaseNode) -> Self:
        """Append `child` to node `parent_id`'s children (embedded, same document).

        A freshly built `child` (DETACHED) embeds into the parent's document on
        write-back — no new file. Raises if `parent_id` is a reference stub or if
        `child.id` already exists in the tree (ids must be unique).

        Args:
            parent_id: The id of the node that will receive the new child.
            child: The node to embed; must have a unique id within this tree.

        Returns:
            A new root with `child` appended to the parent's `nodes`.

        Raises:
            NodeStateError: If `child.id` already exists, or the parent is a
                `RefNode` stub (resolve it first).
        """
        if self.find(id=child.id) is not None:
            raise NodeStateError(
                f"duplicate node id {child.id!r}; ids must be unique within a "
                "collection"
            )

        def _append(n: BaseNode) -> BaseNode:
            if isinstance(n, RefNode):
                raise NodeStateError(
                    f"cannot add children to reference stub {n.id!r}; resolve it "
                    "with open_inlined first, or add to an embedded node"
                )
            children = getattr(n, "nodes", ()) or ()
            return n.model_copy(update={"nodes": (*children, child)})

        return self.update(id=parent_id, fn=_append)

    def add_ref(self, *, parent_id: str, ref: "RefNode") -> Self:
        """Attach a `RefNode` stub to node `parent_id`.

        `ref` is a typed `RefNode` stub (kept verbatim with its type/attributes),
        as handed back by the write verbs (`create` / `save` / `save_inlined`).
        The stored path is relativized later, at write time, against the document
        being written (so this works even while the parent is still detached).

        Args:
            parent_id: The id of the node that will receive the reference.
            ref: The `RefNode` stub to attach.

        Returns:
            A new root with the reference stub appended to the parent's `nodes`.

        Raises:
            NodeStateError: If the ref's id already exists, or the parent is
                itself a `RefNode` stub.
        """
        ref_id = ref.id
        if self.find(id=ref_id) is not None:
            raise NodeStateError(
                f"duplicate node id {ref_id!r}; ids must be unique within a collection"
            )

        def _attach(n: BaseNode) -> BaseNode:
            if isinstance(n, RefNode):
                raise NodeStateError(
                    f"cannot add children to reference stub {n.id!r}; resolve it "
                    "with open_inlined first, or add to an embedded node"
                )
            children = getattr(n, "nodes", ()) or ()
            return n.model_copy(update={"nodes": (*children, ref)})

        return self.update(id=parent_id, fn=_attach)

    def remove(self, *, id: str) -> Self:
        """Remove the node with `id` from the tree (an in-memory unlink).

        Any external document the node referenced stays on disk; use
        `delete` to remove a node from its document on disk.

        Args:
            id: The id of the node to remove.

        Returns:
            A new root with the node removed from its parent's `nodes`.

        Raises:
            KeyError: If no node with `id` exists in the tree.
        """
        new, found = _remove(self, id)
        if not found:
            raise KeyError(f"no node with id {id!r} in this tree")
        return cast("Self", new)


# --- editable hierarchy ----------------------------------------------------


class Node(BaseNode):
    """An embedded (inline) editable node: children in `nodes`; no path."""

    path: Literal[None] = None
    nodes: tuple[AnyNode, ...] = ()


class RefNode(BaseNode):
    """A reference stub: `path` points to an external document; `nodes` is None."""

    path: PathObj
    nodes: Literal[None] = None

    def resolve_path(self) -> str:
        """Return the absolute URL this stub references.

        Returns:
            Absolute URL string resolved against the owning document.
        """
        return self.path.resolve(self._document)


# Concrete built-in families (collection / multiscale / singlescale) live in
# their own modules (`_collection`, `_multiscale`, `_singlescale`) and are wired
# into `DEFAULT_REGISTRY` by `_builtins`. This module keeps only the generic
# bases and the registry-driven factories below.


# --- inlined (read-only) hierarchy -----------------------------------------


class InlinedNode(BaseNode):
    """A fully-resolved, read-only node produced by `open_inlined`.

    Children are other `InlinedNode`s (resolved) or `RefNode` stubs left
    un-inlined by depth limit, cycle, or open error. Inlined nodes carry the
    `_document` they were resolved from, so `ref()` works. Functional edits
    return new inlined trees but cannot round-trip to origins — use
    `save_inlined` to snapshot the whole tree to one document.
    """

    nodes: tuple[AnyInlinedNode, ...] = ()


# --- spine-rebuild helpers (functional) ------------------------------------


def _rebuild(
    node: BaseNode, id: str, fn: Callable[[BaseNode], BaseNode]
) -> tuple[BaseNode, bool]:
    """Apply `fn` to the node with `id`, rebuilding the spine bottom-up.

    Args:
        node: Current node (root of the subtree being searched).
        id: Target node id.
        fn: Transformation to apply to the matched node.

    Returns:
        A `(new_root, found)` pair; `found` is `False` if `id` is absent.
    """
    if node.id == id:
        return fn(node), True
    children: tuple[BaseNode, ...] | None = getattr(node, "nodes", None)
    if children is None:
        return node, False
    new_children: list[BaseNode] = []
    found = False
    for child in children:
        if found:
            new_children.append(child)
            continue
        rebuilt, hit = _rebuild(child, id, fn)
        found = found or hit
        new_children.append(rebuilt)
    if not found:
        return node, False
    return node.model_copy(update={"nodes": tuple(new_children)}), True


def _remove(node: BaseNode, id: str) -> tuple[BaseNode, bool]:
    """Remove the node with `id` from `node`'s children.

    Args:
        node: Current node (root of the subtree being searched).
        id: Id of the node to remove.

    Returns:
        A `(new_root, found)` pair; `found` is `False` if `id` is absent.
    """
    children: tuple[BaseNode, ...] | None = getattr(node, "nodes", None)
    if children is None:
        return node, False
    if any(c.id == id for c in children):
        kept = tuple(c for c in children if c.id != id)
        return node.model_copy(update={"nodes": kept}), True
    new_children: list[BaseNode] = []
    found = False
    for child in children:
        if found:
            new_children.append(child)
            continue
        rebuilt, hit = _remove(child, id)
        found = found or hit
        new_children.append(rebuilt)
    if not found:
        return node, False
    return node.model_copy(update={"nodes": tuple(new_children)}), True


# --- references -> stubs ---------------------------------------------------


def _relativize_path(path: PathObj, document: MetadataDocument | None) -> PathObj:
    """Rewrite an absolute `path` relative to `document`'s directory when local.

    Same directory → `./name`; otherwise (different dir, remote, already
    relative, or no parent document) the path is kept verbatim. The path's form
    (zarr/json) is preserved.

    Args:
        path: The reference path to rewrite.
        document: The parent document the stub will live in, if known.

    Returns:
        A possibly-relativized `PathObj` of the same form.
    """
    if document is None or path.path.startswith(("http", "./")):
        return path
    base = posixpath.dirname(document.url)
    if posixpath.dirname(path.path) == base:
        rel = "./" + posixpath.basename(path.path)
        return path.model_copy(update={"path": rel})
    return path


# --- construction (graceful fallback to a generic node) --------------------


def _find_type_path(value: Any) -> tuple[str | None, bool]:
    """Extract `(type_str, has_path)` from a raw dict or node instance.

    Args:
        value: A `dict` payload or a node instance.

    Returns:
        A `(type, has_path)` tuple where `has_path` is `True` when the
        value carries a non-`None` `path` field.

    Raises:
        ValueError: If `value` is neither a dict nor a node instance.
    """
    if isinstance(value, dict):
        # A path key serialized as None (an embedded Node round-tripped through
        # model_dump) is not a reference; only a non-None path makes a RefNode.
        return value.get("type"), value.get("path") is not None
    if isinstance(value, BaseNode):
        return value.type, isinstance(value, RefNode)
    raise ValueError(f"Invalid node value {type(value)}")


# The default registry starts empty; `_builtins.register_builtins` wires in the
# collection / multiscale / singlescale families (called once from the package
# `__init__`). Third-party types register through `register_family` below.
DEFAULT_REGISTRY = NodeRegistry(Node, RefNode, InlinedNode)


def register_family(
    *variants: type[Node] | type[RefNode] | type[InlinedNode],
    registry: NodeRegistry = DEFAULT_REGISTRY,
    key: str | None = None,
) -> NodeTypes:
    """Register a node-type family on a registry (defaults to `DEFAULT_REGISTRY`).

    Thin wrapper over `NodeRegistry.register_family`: pass the variant classes
    (editable / ref / inlined) and the slot and `type` key are inferred.

    Args:
        *variants: One or more variant classes, all for the same type.
        registry: Registry to register into; the module default if omitted.
        key: Explicit type key; inferred from the variants when omitted.

    Returns:
        The registered `NodeTypes` family.
    """
    return registry.register_family(*variants, key=key)


def build_node(value: Any) -> Node:
    """Build a concrete editable `Node` subtype from a dict or node instance.

    Args:
        value: A `dict` payload or an existing node instance.

    Returns:
        A typed `Node` subclass, or a plain `Node` when `type` is unknown.

    Raises:
        ValueError: If `value` carries a `path` field (use
            :func:`build_ref_node`).
    """
    node_type, has_path = _find_type_path(value)
    if has_path:
        raise ValueError("An embedded node must not have a path")
    data = value if isinstance(value, dict) else value.model_dump()
    return DEFAULT_REGISTRY.get_node(node_type or "")(**data)


def build_ref_node(value: Any) -> RefNode:
    """Build a concrete `RefNode` subtype from a dict or node instance.

    Args:
        value: A `dict` payload or an existing node instance.

    Returns:
        A typed `RefNode` subclass, or a plain `RefNode` when `type` is unknown.

    Raises:
        ValueError: If `value` has no `path` field (use :func:`build_node`).
    """
    node_type, has_path = _find_type_path(value)
    if not has_path:
        raise ValueError("A reference node must have a path")
    data = value if isinstance(value, dict) else value.model_dump()
    return DEFAULT_REGISTRY.get_ref(node_type or "")(**data)


def build_any_node(value: Any) -> Node | RefNode:
    """Dispatch to :func:`build_ref_node` or :func:`build_node` based on `path`.

    Args:
        value: A `dict` payload or an existing node instance.

    Returns:
        A `RefNode` if `value` has a path, otherwise a `Node`.
    """
    _, has_path = _find_type_path(value)
    return build_ref_node(value) if has_path else build_node(value)


def _build_inlined_child(value: Any) -> InlinedNode | RefNode:
    """Validator: pass inlined/ref instances through, build inlined from dicts.

    Args:
        value: An `InlinedNode`/`RefNode` instance or a dict payload.

    Returns:
        The node instance for `nodes` membership.
    """
    if isinstance(value, (InlinedNode, RefNode)):
        return value
    node_type, has_path = _find_type_path(value)
    if has_path:
        return build_ref_node(value)
    data = value if isinstance(value, dict) else value.model_dump()
    return DEFAULT_REGISTRY.get_inlined(node_type or "")(**data)


def build_inlined(
    source: BaseNode, children: tuple[InlinedNode | RefNode, ...]
) -> InlinedNode:
    """Build the `InlinedNode` mirror of an editable `source` node.

    Copies `source`'s identity and attributes, attaches the already-resolved
    `children`, and stamps the source's `_document` so `ref()` works on the
    result.

    Args:
        source: The editable `Node` being inlined.
        children: The resolved children (inlined nodes and/or leftover stubs).

    Returns:
        A typed `InlinedNode` mirroring `source`.
    """
    data = source.model_dump(exclude={"nodes", "path"})
    cls = DEFAULT_REGISTRY.get_inlined(source.type or "")
    inlined = cls(**data, nodes=children)
    _set_private(inlined, "_document", source._document)
    return inlined


def assert_unique_ids(root: BaseNode) -> None:
    """Assert that every node id in the tree is unique.

    Node ids MUST be unique across the inlined (single-document) tree.
    Inlining merges several source documents into one, where ids are only unique
    per source — so collisions surface here. Unresolved `RefNode` stubs are
    pointers, not materialized nodes (a stub left at a cycle necessarily shares
    an ancestor's id), so they are not counted.

    Args:
        root: The root of the tree to validate.

    Raises:
        ValueError: If any materialized node id appears more than once.
    """
    seen: set[str] = set()
    for node in root.walk():
        if isinstance(node, RefNode):
            continue
        if node.id in seen:
            raise ValueError(f"duplicate node id {node.id!r} in document")
        seen.add(node.id)


AnyNode = Annotated[SerializeAsAny[Node | RefNode], PlainValidator(build_any_node)]
AnyInlinedNode = Annotated[
    SerializeAsAny[InlinedNode | RefNode], PlainValidator(_build_inlined_child)
]

Node.model_rebuild()
InlinedNode.model_rebuild()
