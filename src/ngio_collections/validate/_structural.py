"""CORE structural validators: the rules RFC-8 revision 1 states for every node.

Each check reads the focus node, at most its parent / children, and the
index lookups its own references need, so one node costs O(neighbourhood):

- `id_is_uuid`: the node id and every declaration it carries are UUIDs (§6).
- `known_types`: node and trait types are keywords the revision names or URIs (§4, §5).
- `node_fields_allowed`: a collection has no node fields; a multiscale has only
  `coordinate_systems` and `scales` (§2.1). No `attributes` bag survives.
- `multiscale_is_complete`: a multiscale declares at least one coordinate system
  and one scale, each well-formed (§8.2).
- `no_embedded_multiscale`: a multiscale inside a collection is external (§8.1).
- `references_resolve`: a same-document `{type, ref}` points at a declaration of
  that type (§7.2). References carrying a `path` are not checked here.
- `extension_types_declared`: every URI type is covered by the document's
  `extension_manifest` (§4).
- `external_unresolved`: in a fully resolved view, no node is left external.
- `paths_are_core` (opt-in): every path object uses the `relative` format, the
  only core one (§7.3). Not bundled: this package resolves all formats.

All but `multiscale_is_complete` (which validates through the pydantic
`MultiscaleFields` model) run without pydantic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Mapping

from ngio_collections._optional import require_pydantic
from ngio_collections._types import JSONValue
from ngio_collections.graph import find_declaration, iter_declarations
from ngio_collections.models._ids import is_uuid
from ngio_collections.models._manifest import ExtensionManifestEntry, is_extension_type
from ngio_collections.models._vocabulary import BUILTIN_TRAIT_TYPES
from ngio_collections.resolve import is_path_object
from ngio_collections.validate._engine import ValidationError

if TYPE_CHECKING:
    from ngio_collections.api._node import Node

NODE_TYPES = frozenset({"collection", "multiscale"})
"""Keyword node types RFC-8 revision 1 defines."""

MULTISCALE_FIELDS = frozenset({"coordinate_systems", "scales"})


def id_is_uuid(node: Node) -> None:
    """The node id and every declaration it carries must be canonical UUIDs."""
    if not is_uuid(node.id):
        raise ValidationError(f"node id {node.id!r} is not a UUID")
    for declaration in iter_declarations(node.record):
        if not is_uuid(declaration["id"]):
            raise ValidationError(
                f"{declaration['type']} id {declaration['id']!r} is not a UUID"
            )


def known_types(node: Node) -> None:
    """Node and trait types must be revision keywords or extension URIs."""
    if node.type not in NODE_TYPES and not is_extension_type(node.type):
        raise ValidationError(
            f"unknown node type {node.type!r}: built-in types are "
            f"{sorted(NODE_TYPES)}; extension types are URIs"
        )
    for trait_type in node.traits:
        if trait_type not in BUILTIN_TRAIT_TYPES and not is_extension_type(trait_type):
            raise ValidationError(
                f"unknown trait type {trait_type!r}: built-in traits are "
                f"{sorted(BUILTIN_TRAIT_TYPES)}; extension traits are URIs"
            )


def node_fields_allowed(node: Node) -> None:
    """Built-in node types carry only the fields the revision gives them."""
    if "attributes" in node.fields:
        raise ValidationError(
            "node carries an `attributes` bag; RFC-8 revision 1 replaced it with "
            "typed `traits`"
        )
    if node.type == "collection" and node.fields:
        raise ValidationError(
            f"collection carries unexpected fields {sorted(node.fields)}; "
            "a collection has only `nodes`, `path` and `traits`"
        )
    if node.type == "multiscale":
        extra = set(node.fields) - MULTISCALE_FIELDS
        if extra:
            raise ValidationError(
                f"multiscale carries unexpected fields {sorted(extra)}; "
                f"allowed: {sorted(MULTISCALE_FIELDS)}"
            )


def multiscale_is_complete(node: Node) -> None:
    """A multiscale body declares well-formed coordinate systems and scales.

    Validates the fields through `MultiscaleFields`, so it needs pydantic.
    """
    if node.type != "multiscale" or node.is_external:
        return
    require_pydantic("multiscale_is_complete")
    from ngio_collections.models._multiscale import MultiscaleFields

    try:
        fields = MultiscaleFields.model_validate(dict(node.fields))
    except Exception as exc:  # pydantic.ValidationError
        raise ValidationError(f"multiscale fields do not validate: {exc}") from exc
    if not fields.coordinate_systems:
        raise ValidationError("multiscale declares no coordinate system")
    if not fields.scales:
        raise ValidationError("multiscale declares no scale")


def no_embedded_multiscale(node: Node) -> None:
    """A multiscale under a parent is always external (its own document)."""
    if node.type != "multiscale" or node.parent() is None:
        return
    if node.record.path is None and node.record.edge is None:
        raise ValidationError(
            "multiscale is embedded in its parent; RFC-8 revision 1 requires a "
            "`path` to the image's own document"
        )


def _walk_references(value: object) -> Iterator[Mapping[str, JSONValue]]:
    """Yield every `{type, ref}` reference object nested in `value`."""
    if isinstance(value, Mapping):
        if isinstance(value.get("ref"), str) and isinstance(value.get("type"), str):
            yield value
        for item in value.values():
            yield from _walk_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_references(item)


def _same_document_refs(node: Node) -> Iterator[Mapping[str, JSONValue]]:
    """Yield the node's references that carry no `path` (same-document ones)."""
    for container in (node.record.fields, node.record.traits):
        for ref in _walk_references(dict(container)):
            if ref.get("path") is None:
                yield ref


def references_resolve(node: Node) -> None:
    """Every same-document `{type, ref}` names a declaration of that type.

    Node references are looked up in the id index, other declarations (scales,
    coordinate systems, acquisitions) in the declaration index of the tree the
    node belongs to. References carrying a `path` locate another document and
    are not checked here.
    """
    tree = node.tree
    for ref in _same_document_refs(node):
        uuid, kind = str(ref["ref"]), str(ref["type"])
        if any(tree.record(k).type == kind for k in tree.find(uuid)):
            continue
        found = False
        for key in tree.declarations(uuid):
            declaration = find_declaration(tree.record(key), uuid)
            if declaration is not None and declaration.get("type") == kind:
                found = True
                break
        if not found:
            raise ValidationError(
                f"reference {{type: {kind!r}, ref: {uuid!r}}} does not resolve to a "
                f"{kind} declared in this document"
            )


def _manifest_entries(node: Node, url: str | None) -> list[ExtensionManifestEntry]:
    """Return the parsed manifest of the document at `url` in the node's tree."""
    if url is None:
        return []
    return [
        ExtensionManifestEntry.from_dict(e) for e in node.tree.manifests.get(url, ())
    ]


def _require_declared(
    type_name: str, entries: list[ExtensionManifestEntry], where: str
) -> None:
    """Raise unless `type_name` is a keyword or is covered by `entries`."""
    if not is_extension_type(type_name):
        return
    if not any(entry.covers(type_name) for entry in entries):
        raise ValidationError(
            f"extension type {type_name!r} is not declared in the "
            f"`extension_manifest` of {where!r}"
        )


def extension_types_declared(node: Node) -> None:
    """Every URI node / trait type is declared by the document that uses it.

    A resolved boundary node spans two documents: the traits of its declaring
    entry are checked against the declaring document's manifest, the target's
    own traits against the target document's, and the node type against both.
    """
    if node.is_detached:
        return
    own_url = node.document_url
    own_entries = _manifest_entries(node, own_url)
    edge = node.record.edge
    if edge is None:
        for type_name in (node.type, *node.traits):
            _require_declared(type_name, own_entries, str(own_url))
        return
    entry_entries = _manifest_entries(node, edge.origin_url)
    _require_declared(node.type, entry_entries, str(edge.origin_url))
    _require_declared(node.type, own_entries, str(own_url))
    for trait_type in edge.traits:
        _require_declared(trait_type, entry_entries, str(edge.origin_url))
    for trait_type in node.traits:
        if trait_type not in edge.traits:
            _require_declared(trait_type, own_entries, str(own_url))


def external_unresolved(node: Node) -> None:
    """In a resolved view, a node still external could not be resolved."""
    if node.tree.mode != "resolved" or node.parent() is None:
        return
    if node.is_external:
        raise ValidationError(
            f"external node {node.id!r} ({node.ref_path!r}) could not be resolved: "
            "missing document, type or id mismatch, cycle, or unsupported path format"
        )


def _walk_path_objects(value: object) -> Iterator[Mapping[str, JSONValue]]:
    """Yield every path object nested in `value`."""
    if isinstance(value, Mapping):
        if is_path_object(value):
            yield value
            return
        for item in value.values():
            yield from _walk_path_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_path_objects(item)


def paths_are_core(node: Node) -> None:
    """Opt-in: every path object on the node uses the core `relative` format."""
    path = node.record.path
    if path is not None and path.format != "relative":
        raise ValidationError(
            f"node path uses non-core format {path.format!r} (href {path.href!r})"
        )
    for container in (node.record.fields, node.record.traits):
        for obj in _walk_path_objects(dict(container)):
            if obj.get("format") != "relative":
                raise ValidationError(
                    f"path object uses non-core format {obj.get('format')!r} "
                    f"(href {obj.get('href')!r})"
                )


CORE_VALIDATORS = (
    id_is_uuid,
    known_types,
    node_fields_allowed,
    multiscale_is_complete,
    no_embedded_multiscale,
    references_resolve,
    extension_types_declared,
    external_unresolved,
)
"""The structural checks every revision-1 document must pass."""
