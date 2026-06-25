"""Node-type registry: maps a node `type` key to its model classes.

This branch has three parallel node hierarchies (`Node`, `RefNode`,
`InlinedNode`), so a registration binds a *family* of up to three variant
classes under one `type` key. Unregistered keys — and registered keys missing a
given variant — fall back to the generic base passed at construction, per the
RFC's graceful-degradation rules.

The registry is a plain object, not a singleton. `models._nodes` builds the
module-level `DEFAULT_REGISTRY` with the built-in types; the node factories read
it directly, so registering a new type makes it parse everywhere with no further
wiring. The fallback base classes are injected at construction, so this module
needs no runtime imports from `_nodes` (avoiding a circular import).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    from ngio_collections.models._nodes import InlinedNode, Node, RefNode


class NodeTypes(NamedTuple):
    """A registered family of variant classes for one node `type` key.

    Any member may be `None` when that type has no dedicated subclass for the
    variant; lookups fall back to the registry's generic base in that case.
    """

    node: type[Node] | None = None
    ref: type[RefNode] | None = None
    inlined: type[InlinedNode] | None = None


class NodeRegistry:
    """Maps a node `type` key to its `Node` / `RefNode` / `InlinedNode` family.

    Unregistered keys, and registered keys whose family omits a variant, resolve
    to the generic base class supplied at construction.
    """

    def __init__(
        self,
        node_base: type[Node],
        ref_base: type[RefNode],
        inlined_base: type[InlinedNode],
    ) -> None:
        """Build a registry whose lookups fall back to the given base classes.

        Args:
            node_base: Generic editable node returned when no `node` variant is
                registered for a key.
            ref_base: Generic reference stub returned when no `ref` variant is
                registered for a key.
            inlined_base: Generic inlined node returned when no `inlined` variant
                is registered for a key.
        """
        self._node_base = node_base
        self._ref_base = ref_base
        self._inlined_base = inlined_base
        self._types: dict[str, NodeTypes] = {}

    def register(
        self,
        key: str,
        *,
        node: type[Node] | None = None,
        ref: type[RefNode] | None = None,
        inlined: type[InlinedNode] | None = None,
    ) -> None:
        """Register a family of variant classes under the type `key`.

        Args:
            key: The non-empty `type` string the classes are bound to.
            node: Editable node subclass for this type, if any.
            ref: Reference-stub subclass for this type, if any.
            inlined: Inlined node subclass for this type, if any.

        Raises:
            ValueError: If `key` is empty, or no variant is provided.
            TypeError: If a provided class is not a subclass of the matching
                base (`node`/`ref`/`inlined`).
        """
        if not (isinstance(key, str) and key):
            raise ValueError("registration key must be a non-empty string")
        if node is None and ref is None and inlined is None:
            raise ValueError("at least one of node, ref, inlined must be provided")
        self._check(node, self._node_base, "node")
        self._check(ref, self._ref_base, "ref")
        self._check(inlined, self._inlined_base, "inlined")
        self._types[key] = NodeTypes(node=node, ref=ref, inlined=inlined)

    @staticmethod
    def _check(cls: type | None, base: type, label: str) -> None:
        if cls is not None and not (isinstance(cls, type) and issubclass(cls, base)):
            raise TypeError(f"{label} {cls!r} is not a {base.__name__} subclass")

    def register_family(
        self,
        *variants: type[Node] | type[RefNode] | type[InlinedNode],
        key: str | None = None,
    ) -> NodeTypes:
        """Register a family from its variant classes, inferring slot and key.

        Each variant is classified by which generic base it subclasses
        (`node` / `ref` / `inlined`); the `type` key is read from the variants'
        shared `type` literal unless `key` is given. Sugar over `register` for
        the mixin pattern, where the variants are written by inheritance.

        Args:
            *variants: One or more variant classes, all for the same type.
            key: Explicit type key; inferred from the variants when omitted.

        Returns:
            The registered `NodeTypes` family.

        Raises:
            ValueError: If no variants are given, two map to the same slot, or
                the key cannot be inferred to a single non-empty string.
            TypeError: If a variant subclasses none — or more than one — of the
                generic bases.
        """
        if not variants:
            raise ValueError("register_family needs at least one variant class")
        slots: dict[str, type] = {}
        keys: set[str] = set()
        for cls in variants:
            slot = self._slot_of(cls)
            if slot in slots:
                raise ValueError(
                    f"two {slot} variants given: {slots[slot]!r} and {cls!r}"
                )
            slots[slot] = cls
            default = getattr(cls, "node_type", None)
            if isinstance(default, str) and default:
                keys.add(default)
        if key is None:
            if len(keys) != 1:
                raise ValueError(
                    f"cannot infer a single type key from variants: {sorted(keys)}"
                )
            key = keys.pop()
        node = cast("type[Node] | None", slots.get("node"))
        ref = cast("type[RefNode] | None", slots.get("ref"))
        inlined = cast("type[InlinedNode] | None", slots.get("inlined"))
        self.register(key, node=node, ref=ref, inlined=inlined)
        return NodeTypes(node=node, ref=ref, inlined=inlined)

    def _slot_of(self, cls: type) -> str:
        bases = (
            ("node", self._node_base),
            ("ref", self._ref_base),
            ("inlined", self._inlined_base),
        )
        matches = [
            name
            for name, base in bases
            if isinstance(cls, type) and issubclass(cls, base)
        ]
        if len(matches) != 1:
            raise TypeError(
                f"{cls!r} must subclass exactly one of "
                f"{self._node_base.__name__} / {self._ref_base.__name__} / "
                f"{self._inlined_base.__name__}"
            )
        return matches[0]

    def get_node(self, key: str) -> type[Node]:
        """The editable node class for `key`; the generic base if unregistered."""
        record = self._types.get(key)
        return (record.node if record else None) or self._node_base

    def get_ref(self, key: str) -> type[RefNode]:
        """The reference-stub class for `key`; the generic base if unregistered."""
        record = self._types.get(key)
        return (record.ref if record else None) or self._ref_base

    def get_inlined(self, key: str) -> type[InlinedNode]:
        """The inlined node class for `key`; the generic base if unregistered."""
        record = self._types.get(key)
        return (record.inlined if record else None) or self._inlined_base

    def __contains__(self, key: str) -> bool:
        return key in self._types
