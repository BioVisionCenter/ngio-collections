"""Base model classes and shared field types.

Pure Pydantic layer: no IO (DESIGN.md §7); the only URL handling is the pure
string join in :attr:`BaseNode.target_url`. Models never import the document,
resolver, or store layers.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import urljoin
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Literal,
    Self,
    TypeVar,
    Union,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    RootModel,
)
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from ome_zarr_collections.document import MetadataDocument

ID_PATTERN = r"^[a-zA-Z0-9\-_.]+$"

IdStr = Annotated[str, Field(pattern=ID_PATTERN)]


class BaseObj(BaseModel):
    # extra="allow" keeps unknown and custom-prefixed fields through a
    # round-trip, per the RFC's graceful-degradation rules.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class ZarrPath(BaseObj):
    type: Literal["zarr"] = "zarr"
    path: str


class JsonPath(BaseObj):
    type: Literal["json"] = "json"
    path: str


PathObj = Annotated[
    Union[ZarrPath, JsonPath],
    Field(discriminator="type"),
]


class ReferenceObj(BaseObj):
    id: IdStr
    path: PathObj | None = None


class _AttributeKey:
    """Mixin declaring the `attributes` dict key an attribute model maps to."""

    key: ClassVar[str]

    @classmethod
    def name_space(cls) -> str | None:
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


class AttrsView:
    """Typed, validating view over a node's raw ``attributes`` dict.

    Reads validate the raw JSON value into the requested attribute model;
    assignment writes the spec-shaped dump back into the dict (DESIGN.md §3.5).
    The raw dict itself stays the source of truth, so unknown attributes
    round-trip untouched.

    Usage::

        plate = node.attrs[PlateAttribute]      # typed, validated view
        node.attrs[PlateAttribute] = plate      # explicit write-back
        PlateAttribute in node.attrs            # membership
    """

    def __init__(self, node: BaseNode) -> None:
        self._node = node

    def __contains__(self, attrs_type: type[AnyAttribute]) -> bool:
        return attrs_type.key in self._node.attributes

    def __getitem__(self, attrs_type: type[AttributeType]) -> AttributeType:
        if attrs_type not in self:
            raise KeyError(attrs_type.key)
        return attrs_type.model_validate(self._node.attributes[attrs_type.key])

    def get(
        self, attrs_type: type[AttributeType], default: AttributeType | None = None
    ) -> AttributeType | None:
        if attrs_type not in self:
            return default
        return self[attrs_type]

    def __setitem__(
        self, attrs_type: type[AttributeType], value: AttributeType
    ) -> None:
        validated = attrs_type.model_validate(value)
        # ty can't match RootModel.model_dump's Self bound through the
        # BaseAttribute | BaseListAttribute typevar bound.
        self._node.attributes[attrs_type.key] = validated.model_dump(  # ty: ignore[invalid-argument-type]
            mode="json", by_alias=True, exclude_none=True
        )

    def __delitem__(self, attrs_type: type[AnyAttribute]) -> None:
        del self._node.attributes[attrs_type.key]


class BaseNode(BaseObj):
    """Common shape of every collection node.

    Unregistered node types parse as a plain ``BaseNode`` (graceful
    degradation). Note: no ``version`` field — the ``ome`` version lives on
    :class:`~ome_zarr_collections.document.MetadataDocument` (DESIGN.md §3.1).
    """

    type: str
    id: IdStr
    name: str = Field(min_length=1)
    path: PathObj | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    # The narrowed class for this type's *reference form* (`path` required,
    # no embedded children); `validate_node` routes path-bearing dicts to it.
    # Assigned after the ref class definition; None means no narrowed form.
    ref_form: ClassVar[type[BaseNode] | None] = None

    # Provenance back-references, set during parsing. Private attrs never
    # serialize, so the model stays spec-pure on the wire. A node produced by
    # `model_copy()` or re-validation is *detached*: `_document is None`.
    _document: MetadataDocument | None = PrivateAttr(default=None)
    _parent: BaseNode | None = PrivateAttr(default=None)

    # Copies are detached (DESIGN.md §3.1): provenance describes the original
    # tree, never the copy. `model_copy()` delegates to these.
    def __copy__(self) -> Self:
        copied = super().__copy__()
        copied._document = None
        copied._parent = None
        return copied

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        copied = super().__deepcopy__(memo)
        copied._document = None
        copied._parent = None
        return copied

    @property
    def attrs(self) -> AttrsView:
        """Typed view over the raw ``attributes`` dict."""
        return AttrsView(self)

    @property
    def target_url(self) -> str | None:
        """Full URL this node's ``path`` points to, in the store frame.

        Relative paths are document-relative (DESIGN.md §6), so the join
        needs the owning document's URL — the same base the resolver uses
        when it fetches a stub's target. Pure string manipulation, no IO.
        ``None`` when the node has no ``path``; raises ``ValueError`` on a
        detached node (relative or not, a detached path has no frame).
        """
        if self.path is None:
            return None
        if self._document is None:
            raise ValueError(
                f"node {self.id!r} is detached (no owning document); paths "
                "need the declaring document's URL — use nodes from an "
                "opened tree"
            )
        return urljoin(self._document.url, self.path.path)

    def walk(self) -> Iterator[BaseNode]:
        """Yield this node and every descendant, depth-first in document order.

        Pure in-memory traversal: reference stubs are yielded as-is, never
        resolved — cross-document traversal goes through the resolver.
        """
        yield self
        for child in getattr(self, "nodes", None) or []:
            if isinstance(child, BaseNode):
                yield from child.walk()

    def find(self, id: str) -> BaseNode | None:
        """First node in ``walk()`` order whose ``id`` matches, or ``None``.

        Ids are unique within a document, so within one parsed document the
        match is unambiguous.
        """
        return next((node for node in self.walk() if node.id == id), None)


def merged_attributes(stub: BaseNode, target_root: BaseNode) -> dict[str, JsonValue]:
    """Effective attributes of a resolved stub: the target root's attributes
    overlaid by the stub's own.

    The single home of the merge rule (shallow, key-level, stub wins —
    DESIGN.md §5): stub attributes are metadata of the parent→child
    reference, and the nearer scope overrides. ``Resolver.inline()`` applies
    this rule when collapsing a stub into its resolved subtree — the one
    place the merge is materialized.
    """
    return {**target_root.attributes, **stub.attributes}
