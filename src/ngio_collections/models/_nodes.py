"""Frozen node models, references, and the functional edit engine.

No IO. Nodes are hand-rolled **frozen** (immutable) `__slots__` classes with
`tuple` children, so a parsed tree is a value that resolution and editing never
mutate — they return new trees. The node spine is deliberately *not* Pydantic:
its fields are a closed, trivial schema (`type/name/id/path/nodes/attributes`)
and per-node Pydantic construction dominated read cost; a `__slots__` node is
~5-15x cheaper to build (see `benchmarks/README.md`). The genuinely complex,
validation-heavy models stay Pydantic — a node's `attributes` are a raw
`dict[str, JsonValue]` validated lazily on access (`__getitem__`/`get_attr`), and
paths/references are Pydantic value types (`models/_paths`, `models/_references`).

The two private fields that survive a copy are `_document` (the node's on-disk
document, if any) and `_origin_id` (an inlined node's pre-namespacing id). The
single invariant every rebuild honors: **edit through `model_copy`, never reparse**,
so `_document` survives untouched. For API compatibility the lite nodes keep
`model_copy(update=...)` / `model_dump(...)` / `model_validate(...)` method shims.

There are two parallel node hierarchies:

* the **editable** tree (`Node` / `RefNode` and subtypes), returned by
  `Resolver.open`; cross-document children stay unresolved `RefNode` stubs and
  the tree is writable single-document (`create` / `save`);
* the **inlined** tree (`InlinedNode` and subtypes), returned by
  `Resolver.open_inlined`; cross-document stubs are resolved in place. It is
  read-only with respect to its origins (only `save_inlined` snapshots it), but
  still supports the same functional in-memory edits.

A `ReferenceObj` is the portable `{id, path?}` pointer `node.ref()` returns;
`add_ref` turns one into an in-tree stub. The write verbs (`create` / `save` /
`save_inlined`) return the richer typed `RefNode` stub (via `stub_to`) so a
reference can be decorated before it is attached.

This module is the cohesive node core: the classes carry their immutable edit
API, the spine-rebuild helpers they call, and the registry-driven construction
factories. The higher-order tree algorithms (inlining, namespacing,
attribute-ref rewriting) live in the `treeops` layer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generator,
    Self,
    Union,
    cast,
)

from pydantic import JsonValue

from ngio_collections.models._config import NodeObj, NodeState, NodeStateError
from ngio_collections.models._paths import DocPath, JsonPath, PathObj, ZarrPath
from ngio_collections.models._references import ID_PATTERN, ReferenceObj
from ngio_collections.models._registry import NodeRegistry, NodeTypes
from ngio_collections.models.attributes._base import (
    AnyAttribute,
    AttributeType,
    _AttributeKey,
)

if TYPE_CHECKING:
    from ngio_collections.io._document import MetadataDocument

_ID_RE = re.compile(ID_PATTERN)


class NodeValidationError(ValueError):
    """A node's structural fields are invalid (bad id, unknown key, bad path).

    Subclasses `ValueError` so callers can keep catching `ValueError`; replaces
    Pydantic's `ValidationError` for the hand-rolled node spine.
    """


# --- references ------------------------------------------------------------

# `ReferenceObj` and the id primitives are pure value types (see `_references`).
# The functions that mint references from a document need the node registry, so
# they live here, next to the node classes.


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

    Per RFC-8 the stub is path-based: it carries the node's type (so `add_ref`
    keeps the type) and name, an absolute `PathObj` of the document's form, and
    empty overlay attributes ready to decorate — but no `id`, since it resolves
    to the root of the document at its path. Mirrors :func:`reference_to` but
    returns the richer stub the write verbs hand back.

    Args:
        node: The node that was written (provides type and name).
        document: The document it now lives in (provides the path).

    Returns:
        A typed `RefNode` (e.g. `RefMultiscaleNode`) with an absolute path.
    """
    path_cls = ZarrPath if document.kind == "zarr" else JsonPath
    ref_cls = DEFAULT_REGISTRY.get_ref(node.type)
    return ref_cls(
        type=node.type, name=node.name, path=path_cls(path=document.ref_url)
    )


# --- nodes -----------------------------------------------------------------


def set_private(node: BaseNode, name: str, value: Any) -> None:
    """Set a private attr on a frozen node (provenance plumbing only).

    Args:
        node: The frozen node whose private attribute should be mutated.
        name: The private slot name (e.g. `"_document"`).
        value: The value to assign.
    """
    object.__setattr__(node, name, value)


def _valid_id(id: Any) -> str:
    """Validate a node id against `ID_PATTERN`, returning it unchanged."""
    if not (isinstance(id, str) and _ID_RE.match(id)):
        raise NodeValidationError(f"invalid node id {id!r}; must match {ID_PATTERN}")
    return id


def _coerce_path(path: Any) -> PathObj:
    """Coerce a `DocPath` instance or `{type, path}` dict to a validated `PathObj`."""
    if isinstance(path, DocPath):
        return path
    if isinstance(path, dict):
        return DocPath.model_validate(path)
    raise NodeValidationError(f"invalid reference path {path!r}")


class BaseNode(NodeObj):
    """Common fields, navigation, and functional edits for every node.

    The node protocol every node carries: a required `type`, an optional `name`,
    and an `attributes` dict. `id` / `nodes` / `path` are added by the concrete
    hierarchies — materialized nodes (`Node` / `InlinedNode`) carry `id` and
    `nodes`, a path-based reference (`RefNode`) carries `path` and (per RFC-8)
    has no `id`. Both the editable (`Node` / `RefNode`) and inlined
    (`InlinedNode`) hierarchies derive from this. Every edit method returns a new
    tree built via `model_copy` and never mutates `self`.
    """

    __slots__ = ("type", "name", "attributes", "_document", "_origin_id")

    # The complete, ordered set of public (serializable) fields a concrete node
    # declares; drives `model_copy` / `model_dump`. Overridden per hierarchy.
    _DATA_FIELDS: tuple[str, ...] = ("type", "name", "attributes")
    # Type key for a family marker (e.g. "collection"); None on the generic base.
    node_type: str | None = None

    type: str
    name: str | None
    attributes: dict[str, JsonValue]
    _document: MetadataDocument | None
    _origin_id: str | None

    def __setattr__(self, name: str, value: Any) -> None:
        """Block mutation: nodes are frozen (provenance uses `set_private`)."""
        raise AttributeError(f"{type(self).__name__} is frozen; use model_copy()")

    def _init_base(
        self, type: str | None, name: str | None, attributes: Any
    ) -> None:
        """Set the shared fields (`type`/`name`/`attributes` + private defaults)."""
        sa = object.__setattr__
        resolved = type if type is not None else self.node_type
        if resolved is None:
            raise NodeValidationError(f"{type!r} node requires a 'type'")
        sa(self, "type", resolved)
        sa(self, "name", name)
        sa(self, "attributes", dict(attributes) if attributes else {})
        sa(self, "_document", None)
        sa(self, "_origin_id", None)

    # --- compatibility shims (lite stand-ins for the Pydantic API) --------

    def model_copy(
        self, *, update: dict[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Return a copy with `update` overrides applied (shallow, like Pydantic).

        Carries `_document` / `_origin_id` across, and never validates — the
        spine-rebuild engine relies on this. `deep` is accepted for signature
        compatibility but ignored (children tuples / attribute dicts are shared,
        matching Pydantic's shallow default).

        Args:
            update: Field values to override on the copy.
            deep: Ignored (accepted for API parity).

        Returns:
            A new node of the same class.
        """
        upd = update or {}
        cls = type(self)
        obj = cls.__new__(cls)
        sa = object.__setattr__
        for field in cls._DATA_FIELDS:
            sa(obj, field, upd[field] if field in upd else getattr(self, field))
        sa(obj, "_document", upd.get("_document", self._document))
        sa(obj, "_origin_id", upd.get("_origin_id", self._origin_id))
        return obj

    def model_dump(
        self,
        *,
        mode: str = "python",
        by_alias: bool = False,
        exclude_none: bool = False,
        exclude: set[str] | frozenset[str] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Serialize the node's fields to a dict (lite `BaseModel.model_dump`).

        Node fields are single-word, so `by_alias` is a no-op for the spine; it is
        forwarded only to the nested `path` value type. `nodes` recurses unless
        excluded. Matches the flag subset the codebase uses.

        Args:
            mode: `"python"` or `"json"` (forwarded to the `path` value type).
            by_alias: Forwarded to the `path` value type.
            exclude_none: Drop fields whose value is `None`.
            exclude: Field names to omit (e.g. `{"nodes"}`).

        Returns:
            A JSON-serializable dict of the node's fields.
        """
        skip = exclude or frozenset()
        out: dict[str, Any] = {}
        for field in type(self)._DATA_FIELDS:
            if field in skip:
                continue
            value = getattr(self, field)
            if exclude_none and value is None:
                continue
            if field == "path" and value is not None:
                value = value.model_dump(mode=mode, by_alias=by_alias)
            elif field == "nodes" and value is not None:
                value = [
                    child.model_dump(
                        mode=mode, by_alias=by_alias, exclude_none=exclude_none
                    )
                    for child in value
                ]
            out[field] = value
        return out

    @classmethod
    def model_validate(cls, obj: Any) -> BaseNode:
        """Build a node tree from a dict / node (lite `BaseModel.model_validate`).

        Dispatches by `type` / `path` through the registry, like a parse; the
        returned class may be a more specific registered subtype than `cls`.

        Args:
            obj: A payload dict or an existing node instance.

        Returns:
            The constructed node tree.
        """
        return build_any_node(obj)

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
        return next(
            (n for n in self.walk() if getattr(n, "id", None) == id), None
        )

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
            NodeStateError: If the node is detached (has no document yet), or is
                a path-based stub (which carries no id).
        """
        # An inlined node's id may have been namespaced; `_origin_id` holds its
        # real id within the origin document, so `ref()` stays correct.
        target_id = self._origin_id or getattr(self, "id", None)
        if target_id is None:
            raise NodeStateError(
                "reference stub carries no id; it is itself a pointer"
            )
        if self._document is None:
            raise NodeStateError(
                f"node {target_id!r} is detached; persist it with create()/"
                "save() before taking a reference"
            )
        return reference_to(target_id, self._document)

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
        new, found = rebuild(self, id, fn)
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

    def drop_attrs(
        self, *, id: str, keys: Sequence[str | type[AnyAttribute]]
    ) -> Self:
        """Remove `keys` from the `attributes` of node `id`.

        Args:
            id: The id of the node whose attributes should be modified.
            keys: Attribute keys to remove, each either a raw string key or an
                attribute model class (whose `key` supplies the string). Unknown
                keys are silently ignored.

        Returns:
            A new root with the specified attribute keys removed.
        """
        names = {k if isinstance(k, str) else k.key for k in keys}
        return self.update(
            id=id,
            fn=lambda n: n.model_copy(
                update={
                    "attributes": {
                        k: v for k, v in n.attributes.items() if k not in names
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
        child_id = getattr(child, "id", None)
        if child_id is not None and self.find(id=child_id) is not None:
            raise NodeStateError(
                f"duplicate node id {child_id!r}; ids must be unique within a "
                "collection"
            )

        def _append(n: BaseNode) -> BaseNode:
            if isinstance(n, RefNode):
                raise NodeStateError(
                    f"cannot add children to reference stub {parent_id!r}; "
                    "resolve it with open_inlined first, or add to an embedded "
                    "node"
                )
            children = getattr(n, "nodes", ()) or ()
            return n.model_copy(update={"nodes": (*children, child)})

        return self.update(id=parent_id, fn=_append)

    def add_ref(self, *, parent_id: str, ref: "RefNode") -> Self:
        """Attach a `RefNode` stub to node `parent_id`.

        `ref` is a typed `RefNode` stub (kept verbatim with its type/name/
        attributes), as handed back by the write verbs (`create` / `save` /
        `save_inlined`). Per RFC-8 a stub is path-based and carries no `id` — it
        resolves to the root of the document at its path. The stored path is
        relativized later, at write time, against the document being written (so
        this works even while the parent is still detached).

        Args:
            parent_id: The id of the node that will receive the reference.
            ref: The `RefNode` stub to attach.

        Returns:
            A new root with the reference stub appended to the parent's `nodes`.

        Raises:
            NodeStateError: If the parent is itself a `RefNode` stub.
        """

        def _attach(n: BaseNode) -> BaseNode:
            if isinstance(n, RefNode):
                raise NodeStateError(
                    f"cannot add children to reference stub {parent_id!r}; "
                    "resolve it with open_inlined first, or add to an embedded "
                    "node"
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
        new, found = remove(self, id)
        if not found:
            raise KeyError(f"no node with id {id!r} in this tree")
        return cast("Self", new)


# --- editable hierarchy ----------------------------------------------------


class Node(BaseNode):
    """An embedded (inline) editable node: children in `nodes`; no path."""

    __slots__ = ("id", "path", "nodes")
    _DATA_FIELDS = ("type", "name", "attributes", "id", "path", "nodes")

    id: str
    path: None
    nodes: tuple[AnyNode, ...]

    def __init__(
        self,
        *,
        id: str,
        type: str | None = None,
        name: str | None = None,
        attributes: dict[str, JsonValue] | None = None,
        path: None = None,
        nodes: Sequence[Any] = (),
        **extra: Any,
    ) -> None:
        """Build an embedded editable node (children coerced from dicts if needed)."""
        if extra:
            raise NodeValidationError(f"unexpected node field(s): {sorted(extra)}")
        if path is not None:
            raise NodeValidationError("an embedded node must not have a 'path'")
        self._init_base(type, name, attributes)
        sa = object.__setattr__
        sa(self, "id", _valid_id(id))
        sa(self, "path", None)
        sa(self, "nodes", tuple(_coerce_editable(c) for c in nodes))


class RefNode(BaseNode):
    """A reference stub: `path` points elsewhere; `nodes` is None.

    Per RFC-8 the `id` is optional. A stub that references another OME *document*
    omits it and resolves to that document's root (see `Resolver._resolve_ref`);
    a stub that references a data array (e.g. a singlescale `./0`) may carry an
    `id` and inline `attributes`, and stays a leaf when its target is not an OME
    document.
    """

    __slots__ = ("id", "path", "nodes")
    _DATA_FIELDS = ("type", "name", "attributes", "id", "path", "nodes")

    id: str | None
    path: PathObj
    nodes: None

    def __init__(
        self,
        *,
        path: Any,
        type: str | None = None,
        id: str | None = None,
        name: str | None = None,
        attributes: dict[str, JsonValue] | None = None,
        nodes: None = None,
        **extra: Any,
    ) -> None:
        """Build a path-based reference stub (no children)."""
        if extra:
            raise NodeValidationError(f"unexpected node field(s): {sorted(extra)}")
        if nodes is not None:
            raise NodeValidationError("a reference node has no 'nodes'")
        self._init_base(type, name, attributes)
        sa = object.__setattr__
        sa(self, "id", _valid_id(id) if id is not None else None)
        sa(self, "path", _coerce_path(path))
        sa(self, "nodes", None)

    def resolve_path(self) -> str:
        """Return the absolute URL this stub references.

        Returns:
            Absolute URL string resolved against the owning document.
        """
        base_url = self._document.url if self._document is not None else None
        return self.path.resolve(base_url)


# Concrete built-in families (collection / multiscale / singlescale) live in
# their own modules (`_collection`, `_multiscale`, `_singlescale`) and are wired
# into `DEFAULT_REGISTRY` by `_builtins`. This module keeps only the
# generic bases and the registry-driven factories below.


# --- inlined (read-only) hierarchy -----------------------------------------


class InlinedNode(BaseNode):
    """A fully-resolved, read-only node produced by `open_inlined`.

    Children are other `InlinedNode`s (resolved) or `RefNode` stubs left
    un-inlined by depth limit, cycle, or open error. Inlined nodes carry the
    `_document` they were resolved from, so `ref()` works. Functional edits
    return new inlined trees but cannot round-trip to origins — use
    `save_inlined` to snapshot the whole tree to one document.
    """

    __slots__ = ("id", "nodes")
    _DATA_FIELDS = ("type", "name", "attributes", "id", "nodes")

    id: str
    nodes: tuple[AnyInlinedNode, ...]

    def __init__(
        self,
        *,
        id: str,
        type: str | None = None,
        name: str | None = None,
        attributes: dict[str, JsonValue] | None = None,
        nodes: Sequence[Any] = (),
        **extra: Any,
    ) -> None:
        """Build a resolved inlined node (children coerced from dicts if needed)."""
        if extra:
            raise NodeValidationError(f"unexpected node field(s): {sorted(extra)}")
        self._init_base(type, name, attributes)
        sa = object.__setattr__
        sa(self, "id", _valid_id(id))
        sa(self, "nodes", tuple(_coerce_inlined(c) for c in nodes))


# --- spine-rebuild helpers (functional) ------------------------------------


def rebuild(
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
    if getattr(node, "id", None) == id:
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
        rebuilt, hit = rebuild(child, id, fn)
        found = found or hit
        new_children.append(rebuilt)
    if not found:
        return node, False
    return node.model_copy(update={"nodes": tuple(new_children)}), True


def remove(node: BaseNode, id: str) -> tuple[BaseNode, bool]:
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
    if any(getattr(c, "id", None) == id for c in children):
        kept = tuple(c for c in children if getattr(c, "id", None) != id)
        return node.model_copy(update={"nodes": kept}), True
    new_children: list[BaseNode] = []
    found = False
    for child in children:
        if found:
            new_children.append(child)
            continue
        rebuilt, hit = remove(child, id)
        found = found or hit
        new_children.append(rebuilt)
    if not found:
        return node, False
    return node.model_copy(update={"nodes": tuple(new_children)}), True


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


def _coerce_editable(value: Any) -> Node | RefNode:
    """Coerce a child of an editable node: pass nodes through, build from dicts."""
    if isinstance(value, BaseNode):
        return cast("Node | RefNode", value)
    return build_any_node(value)


def _coerce_inlined(value: Any) -> InlinedNode | RefNode:
    """Coerce a child of an inlined node: pass nodes through, build from dicts."""
    if isinstance(value, BaseNode):
        return cast("InlinedNode | RefNode", value)
    return _build_inlined_child(value)


# The default registry starts empty; `_builtins.register_builtins` wires in the
# collection / multiscale / singlescale families (called once from the package
# composition root). Third-party types register through `register_family`.
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


def _payload_kwargs(value: Any) -> dict[str, Any]:
    """Return the field kwargs for a constructor from a dict or node instance."""
    return dict(value) if isinstance(value, dict) else value.model_dump()


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
    return DEFAULT_REGISTRY.get_node(node_type or "")(**_payload_kwargs(value))


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
    return DEFAULT_REGISTRY.get_ref(node_type or "")(**_payload_kwargs(value))


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
    """Build an inlined-tree child: pass nodes through, build inlined from dicts.

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
    return DEFAULT_REGISTRY.get_inlined(node_type or "")(**_payload_kwargs(value))


# Back-compat aliases (were Pydantic `Annotated` field types; now plain unions,
# since the node spine is hand-rolled). Exported for typing / downstream use.
AnyNode = Union[Node, RefNode]
AnyInlinedNode = Union[InlinedNode, RefNode]
