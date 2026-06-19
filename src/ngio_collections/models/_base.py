"""Frozen node models, the pure merge/split rule, and the functional edit engine.

Pure Pydantic layer: no IO. Nodes are **frozen** (immutable) with ``tuple``
children, so the parsed tree is a value that resolution and editing never mutate
— they return new trees. Provenance lives in ``PrivateAttr`` (``_document`` /
``_origin``); it never serializes and, because nodes are frozen and never
re-validated, it can only travel via ``model_copy`` (which carries private
state). The single invariant every rebuild honors: **edit through ``model_copy``,
never ``model_validate``**, so provenance rides along untouched.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    Generator,
    Literal,
    Self,
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
    SerializeAsAny,
)
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from ngio_collections._document import MetadataDocument


class BaseObj(BaseModel):
    # frozen → immutable value; extra="allow" round-trips unknown / custom keys.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
        frozen=True,
    )


class NodeStateError(ValueError):
    """A node is in the wrong state for the requested operation.

    Subclasses ``ValueError`` so callers can keep catching ``ValueError``. The
    message points to the API that fits the node's actual state."""


class NodeState(StrEnum):
    """How a node relates to on-disk storage (see :attr:`BaseNode.state`)."""

    DETACHED = "detached"  # in memory only, no backing document
    DOCUMENT = "document"  # materialized in a document (root or embedded child)
    BOUNDARY = "boundary"  # an inlined stub that roots its own external document


# --- paths -----------------------------------------------------------------


def _path_resolve(path: str, document: MetadataDocument | None) -> str:
    """Resolve a stored ``path`` to an absolute URL for IO.

    The stored value is never rewritten — relative stays relative, absolute stays
    absolute — so a tree can be re-rooted later without rewriting references.
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
    type: Literal["zarr"] = "zarr"
    path: str

    def resolve(self, document: MetadataDocument | None) -> str:
        return _path_resolve(self.path, document)


class JsonPath(BaseObj):
    type: Literal["json"] = "json"
    path: str

    def resolve(self, document: MetadataDocument | None) -> str:
        return _path_resolve(self.path, document)


PathObj = Annotated[ZarrPath | JsonPath, Field(discriminator="type")]


# --- provenance (never serialized) -----------------------------------------


@dataclass(frozen=True)
class NodeMetaInfos:
    """Pre-merge identity snapshot of one side of a boundary."""

    id: str
    name: str | None
    attributes: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Origin:
    """A boundary node's merge provenance: the pre-merge stub and target
    identities plus the full original stub (kept so :func:`split` can re-emit the
    parent reference with its path / type / unknown extra keys intact)."""

    ref: NodeMetaInfos  # pre-merge stub (edge layer)
    node: NodeMetaInfos  # pre-merge target (home layer)
    ref_node: "RefNode"


# --- nodes -----------------------------------------------------------------


def _set_private(node: BaseNode, name: str, value: Any) -> None:
    """Set a private attr on a frozen node (provenance plumbing only)."""
    private = node.__pydantic_private__
    assert private is not None
    private[name] = value


class BaseNode(BaseObj):
    type: str
    id: str
    name: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    # Closest owning document (set after parse). None on a freshly added node,
    # which inherits its parent's document on write-back (embed, no new file).
    _document: "MetadataDocument | None" = PrivateAttr(default=None)
    # Merge snapshot; set iff this node is a collapsed document boundary.
    _origin: Origin | None = PrivateAttr(default=None)

    # --- navigation ------------------------------------------------------

    def walk(self) -> Generator[AnyNode, None, None]:
        """Yield this node and every descendant, depth-first in order."""
        yield cast("AnyNode", self)
        children: tuple[AnyNode, ...] = getattr(self, "nodes", None) or ()
        for child in children:
            yield from child.walk()

    def find(self, id: str) -> AnyNode | None:
        """First node in ``walk()`` order whose ``id`` matches, or ``None``."""
        return next((n for n in self.walk() if n.id == id), None)

    @property
    def state(self) -> NodeState:
        """How this node relates to storage: ``DETACHED`` (in memory only),
        ``DOCUMENT`` (lives in a document), or ``BOUNDARY`` (an inlined stub that
        roots its own external document)."""
        if self._document is None:
            return NodeState.DETACHED
        return NodeState.BOUNDARY if self._origin is not None else NodeState.DOCUMENT

    @property
    def is_detached(self) -> bool:
        """True iff this node is fully in memory — built from scratch and not yet
        written (use ``Resolver.create``), or a just-added child not yet saved."""
        return self._document is None

    @property
    def is_boundary(self) -> bool:
        """True iff this node was an inlined stub — i.e. it roots its own
        external document."""
        return self._origin is not None

    @property
    def document_url(self) -> str | None:
        """URL of the closest document that owns this node (its 'context')."""
        return self._document.url if self._document is not None else None

    # --- functional edits (return a new root; self is untouched) ----------

    def update(self, id: str, fn: Callable[[AnyNode], AnyNode]) -> Self:
        """Replace the node with ``id`` by ``fn(node)``, returning a new tree.

        The only spine-rebuild engine: it rebuilds the path from the root to the
        target via ``model_copy`` (carrying provenance), leaving every other
        branch shared with the original. ``fn`` must itself return a node built
        with ``model_copy`` so its provenance survives."""
        new, found = _rebuild(cast("AnyNode", self), id, fn)
        if not found:
            raise KeyError(f"no node with id {id!r} in this tree")
        return cast("Self", new)

    def set_attrs(self, id: str, values: dict[str, JsonValue]) -> Self:
        """Merge ``values`` into the ``attributes`` of node ``id``."""
        return self.update(
            id,
            lambda n: n.model_copy(update={"attributes": {**n.attributes, **values}}),
        )

    def drop_attrs(self, id: str, *keys: str) -> Self:
        """Remove ``keys`` from the ``attributes`` of node ``id``."""
        return self.update(
            id,
            lambda n: n.model_copy(
                update={
                    "attributes": {
                        k: v for k, v in n.attributes.items() if k not in keys
                    }
                }
            ),
        )

    def rename(self, id: str, name: str | None) -> Self:
        """Set the ``name`` of node ``id``."""
        return self.update(id, lambda n: n.model_copy(update={"name": name}))

    def add(self, parent_id: str, child: AnyNode) -> Self:
        """Append ``child`` to node ``parent_id``'s children.

        A freshly built ``child`` (DETACHED) embeds into the parent's document on
        write-back — no new file. Raises if ``parent_id`` is a reference stub
        (resolve it with ``Resolver.inline`` first) or if ``child.id`` already
        exists in the tree (ids must be unique within a collection)."""
        if self.find(child.id) is not None:
            raise NodeStateError(
                f"duplicate node id {child.id!r}; ids must be unique within a "
                "collection"
            )

        def _append(n: AnyNode) -> AnyNode:
            if isinstance(n, RefNode):
                raise NodeStateError(
                    f"cannot add children to reference stub {n.id!r}; resolve it "
                    "with Resolver.inline first, or add to an embedded node"
                )
            return n.model_copy(update={"nodes": (*n.nodes, child)})

        return self.update(parent_id, _append)

    def remove(self, id: str) -> Self:
        """Remove the node with ``id`` from the tree (an in-memory unlink).

        Any external document the node rooted stays on disk; use
        ``Resolver.delete_subtree`` (before removing) to delete its file(s)."""
        new, found = _remove(cast("AnyNode", self), id)
        if not found:
            raise KeyError(f"no node with id {id!r} in this tree")
        return cast("Self", new)


class Node(BaseNode):
    path: Literal[None] = None
    nodes: tuple[AnyNode, ...] = ()


class RefNode(BaseNode):
    path: PathObj
    nodes: Literal[None] = None

    def resolve_path(self) -> str:
        return self.path.resolve(self._document)


class CollectionNode(Node):
    type: Literal["collection"] = "collection"


class MultiscaleNode(Node):
    type: Literal["multiscale"] = "multiscale"


class RefCollectionNode(RefNode):
    type: Literal["collection"] = "collection"


class RefMultiscaleNode(RefNode):
    type: Literal["multiscale"] = "multiscale"


class RefSinglescaleNode(RefNode):
    type: Literal["singlescale"] = "singlescale"


# --- spine-rebuild helpers (functional) ------------------------------------


def _rebuild(
    node: AnyNode, id: str, fn: Callable[[AnyNode], AnyNode]
) -> tuple[AnyNode, bool]:
    if node.id == id:
        return fn(node), True
    children: tuple[AnyNode, ...] | None = getattr(node, "nodes", None)
    if children is None:
        return node, False
    new_children: list[AnyNode] = []
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


def _remove(node: AnyNode, id: str) -> tuple[AnyNode, bool]:
    children: tuple[AnyNode, ...] | None = getattr(node, "nodes", None)
    if children is None:
        return node, False
    if any(c.id == id for c in children):
        kept = tuple(c for c in children if c.id != id)
        return node.model_copy(update={"nodes": kept}), True
    new_children: list[AnyNode] = []
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


# --- construction (graceful fallback to a generic Node/RefNode) ------------


def _find_type_path(value: Any) -> tuple[str | None, bool]:
    if isinstance(value, dict):
        return value.get("type"), "path" in value
    if isinstance(value, (Node, RefNode)):
        return value.type, isinstance(value, RefNode)
    raise ValueError(f"Invalid node value {type(value)}")


_NODE_TYPES: dict[str, type[Node]] = {
    "collection": CollectionNode,
    "multiscale": MultiscaleNode,
}
_REF_TYPES: dict[str, type[RefNode]] = {
    "collection": RefCollectionNode,
    "multiscale": RefMultiscaleNode,
    "singlescale": RefSinglescaleNode,
}


def build_node(value: Any) -> Node:
    node_type, has_path = _find_type_path(value)
    if has_path:
        raise ValueError("An embedded node must not have a path")
    data = value if isinstance(value, dict) else value.model_dump()
    return _NODE_TYPES.get(node_type or "", Node)(**data)


def build_ref_node(value: Any) -> RefNode:
    node_type, has_path = _find_type_path(value)
    if not has_path:
        raise ValueError("A reference node must have a path")
    data = value if isinstance(value, dict) else value.model_dump()
    return _REF_TYPES.get(node_type or "", RefNode)(**data)


def build_any_node(value: Any) -> AnyNode:
    _, has_path = _find_type_path(value)
    return build_ref_node(value) if has_path else build_node(value)


# --- the §5 merge rule (single home) + its inverse -------------------------


def merged_attributes(stub: BaseNode, target: BaseNode) -> dict[str, JsonValue]:
    """Effective attributes of a resolved stub: the target's overlaid by the
    stub's own — shallow, key-level, stub wins."""
    return {**target.attributes, **stub.attributes}


def merge(stub: RefNode, target: Node) -> Node:
    """Materialize the stub-wins merge of ``stub`` onto resolved ``target``.

    Returns a NEW frozen node that keeps the target's document ownership and
    children, takes the stub's id/name and the merged attributes, and records an
    :class:`Origin` so :func:`split` can invert it. ``_origin`` set marks a
    document boundary."""
    origin = Origin(
        ref=NodeMetaInfos(stub.id, stub.name, deepcopy(stub.attributes)),
        node=NodeMetaInfos(target.id, target.name, deepcopy(target.attributes)),
        ref_node=stub,
    )
    merged = target.model_copy(
        update={
            "id": stub.id,
            "name": stub.name,
            "attributes": merged_attributes(stub, target),
        }
    )
    _set_private(merged, "_origin", origin)
    return merged


def split(node: Node) -> tuple[RefNode, Node]:
    """Invert :func:`merge`: reconstruct the (parent stub, target root) pair.

    Reconciles the live (possibly edited) id/name/attributes against the two
    pre-merge snapshots — id/name and any stub-origin key route to the stub;
    target-origin and brand-new keys route to the target; a key deleted from the
    live node drops from both. Valid only on a boundary node."""
    origin = node._origin
    if origin is None:
        raise ValueError("split() is valid only on a boundary node")
    ref0, node0 = origin.ref, origin.node
    edge_layer: dict[str, JsonValue] = {}
    home_layer: dict[str, JsonValue] = {}
    for key, value in node.attributes.items():
        if key in ref0.attributes:
            edge_layer[key] = value
            if key in node0.attributes:
                home_layer[key] = node0.attributes[key]
        else:
            home_layer[key] = value
    stub = origin.ref_node.model_copy(
        update={"id": node.id, "name": node.name, "attributes": edge_layer}
    )
    home = node.model_copy(
        update={"id": node0.id, "name": node0.name, "attributes": home_layer}
    )
    _set_private(home, "_origin", None)  # the home side is a plain doc root
    return stub, home


def assert_unique_ids(root: AnyNode) -> None:
    """Node ids MUST be unique across the inlined (single-document) tree.

    Inlining merges several source documents into one, where ids are only unique
    per source — so collisions surface here."""
    seen: set[str] = set()
    for node in root.walk():
        if node.id in seen:
            raise ValueError(f"duplicate node id {node.id!r} in document")
        seen.add(node.id)


RefNodeType = Annotated[SerializeAsAny[RefNode], PlainValidator(build_ref_node)]
NodeType = Annotated[SerializeAsAny[Node], PlainValidator(build_node)]
AnyNode = Annotated[SerializeAsAny[Node | RefNode], PlainValidator(build_any_node)]
