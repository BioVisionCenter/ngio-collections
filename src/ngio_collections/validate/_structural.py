"""CORE structural validators: the rules RFC-8 revision 2 states for every node.

Each check reads the focus node, at most its parent / children, and the
index lookups its own references need, so one node costs O(neighbourhood):

- `id_is_valid`: the node id and every declaration it carries match
  `ID_PATTERN` (upstream "IDs"; UUIDs are allowed, not required).
- `known_types`: node and trait types are keywords the revision names or URIs.
- `node_fields_allowed`: a collection has no node fields; a multiscale has only
  `coordinateSystems`, `coordinateTransformations` and `data`. No `attributes`
  bag survives.
- `multiscale_is_complete`: a multiscale carries `coordinateSystems`,
  `coordinateTransformations` and `data`, with at least one coordinate system
  and one array, each well-formed; every array but the first carries
  `downsamplingTransformations`.
- `multiscale_transformations_wellformed`: a multiscale's
  `coordinateTransformations` go from the multiscale itself (its array space)
  to one coordinate system it declares.
- `no_embedded_multiscale`: a multiscale inside a collection is external (a
  rule of this package, see the README).
- `references_resolve`: a same-document `{type, ref}` points at a declaration of
  that type (upstream "`Reference` interface"). References carrying a `path`
  are not checked here.
- `extension_types_declared`: every URI type (node, trait or path type) is
  covered by the document's `extensionManifest` (upstream "Extension manifest").
- `manifest_well_formed`: at each document root, the manifest parses, its ids
  are unique and every entry lists at least one `jsonschema` / `linkml` schema
  (upstream "Extension manifest" section).
- `must_understand_supported`: a URI type from a `mustUnderstand` extension is
  only acceptable when this process registered the extension (upstream "The
  `mustUnderstand` flag").
- `external_unresolved`: in a fully resolved view, no node is left external.
- `paths_are_core` (opt-in): every path object uses the `relative` format, the
  only core one (upstream "`Path` interface"), and a built-in path type. Not bundled: this package
  resolves all formats and accepts URI path types.

All but `multiscale_is_complete` (which validates through the pydantic
`MultiscaleFields` model) run without pydantic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Mapping

from ngio_collections._optional import require_pydantic
from ngio_collections._types import JSONValue
from ngio_collections.graph import find_declaration, iter_declarations
from ngio_collections.models._ids import ID_PATTERN, is_id
from ngio_collections.models._manifest import (
    SCHEMA_TYPES,
    ExtensionManifestEntry,
    is_extension_type,
)
from ngio_collections.models._multiscale_keys import (
    COORDINATE_SYSTEMS_KEY,
    COORDINATE_TRANSFORMATIONS_KEY,
    MULTISCALE_FIELDS,
)
from ngio_collections.models._paths import BUILTIN_PATH_TYPES
from ngio_collections.models._vocabulary import BUILTIN_TRAIT_TYPES
from ngio_collections.resolve import is_path_object
from ngio_collections.validate._engine import ValidationError

if TYPE_CHECKING:
    from ngio_collections.api._node import Node

NODE_TYPES = frozenset({"collection", "multiscale"})
"""Keyword node types RFC-8 revision 2 defines."""


def id_is_valid(node: Node) -> None:
    """The node id and every declaration it carries must match `ID_PATTERN`."""
    if not is_id(node.id):
        raise ValidationError(
            f"node id {node.id!r} is not a valid id (pattern {ID_PATTERN})"
        )
    for declaration in iter_declarations(node.record):
        if not is_id(declaration["id"]):
            raise ValidationError(
                f"{declaration['type']} id {declaration['id']!r} is not a valid id "
                f"(pattern {ID_PATTERN})"
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
            "node carries an `attributes` bag; RFC-8 revision 2 replaced it with "
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
    """A multiscale body declares well-formed coordinate systems and arrays.

    `coordinateTransformations` is required. Every array but the first must
    carry `downsamplingTransformations`.
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
    if not fields.arrays:
        raise ValidationError("multiscale declares no array")


def _local_ref(value: object, kind: str) -> str | None:
    """Return the `ref` of a same-document `{type: kind, ref}` reference, else `None`."""
    if not isinstance(value, Mapping) or value.get("type") != kind:
        return None
    ref = value.get("ref")
    return ref if isinstance(ref, str) and value.get("path") is None else None


def multiscale_transformations_wellformed(node: Node) -> None:
    """A multiscale's transformations map its array space into one of its systems.

    Array objects have no id, so every `input` must be a same-document
    reference to the multiscale itself (`{type: "multiscale", ref: <its id>}`),
    standing for the array space of its highest-resolution array. Every
    `output` must be a same-document `coordinate_system` reference to a system
    the multiscale declares, and all outputs must name the same one.
    """
    if node.type != "multiscale" or node.is_external:
        return
    transforms = node.fields.get(COORDINATE_TRANSFORMATIONS_KEY)
    systems = node.fields.get(COORDINATE_SYSTEMS_KEY)
    if not isinstance(transforms, list) or not isinstance(systems, list):
        return  # missing or malformed fields are `multiscale_is_complete`'s concern
    system_ids = {s.get("id") for s in systems if isinstance(s, Mapping)}
    outputs: set[str] = set()
    for transform in transforms:
        if not isinstance(transform, Mapping):
            return
        source, target = transform.get("input"), transform.get("output")
        if _local_ref(source, "multiscale") != node.id:
            raise ValidationError(
                "multiscale transformation input must reference the multiscale "
                f"itself ({{type: 'multiscale', ref: {node.id!r}}}), got {source!r}"
            )
        target_id = _local_ref(target, "coordinate_system")
        if target_id is None or target_id not in system_ids:
            raise ValidationError(
                "multiscale transformation output must reference a coordinate "
                f"system this multiscale declares, got {target!r}"
            )
        outputs.add(target_id)
    if len(outputs) > 1:
        raise ValidationError(
            "multiscale transformations must all output to the same coordinate "
            f"system, got {sorted(outputs)}"
        )


def no_embedded_multiscale(node: Node) -> None:
    """A multiscale under a parent is always external (its own document)."""
    if node.type != "multiscale" or node.parent() is None:
        return
    if node.record.path is None and node.record.edge is None:
        raise ValidationError(
            "multiscale is embedded in its parent; this package requires a "
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

    Node references are looked up in the id index, other declarations (arrays,
    coordinate systems, acquisitions) in the declaration index of the tree the
    node belongs to. References carrying a `path` locate another document and
    are not checked here.
    """
    tree = node.tree
    for ref in _same_document_refs(node):
        target, kind = str(ref["ref"]), str(ref["type"])
        if any(tree.record(k).type == kind for k in tree.find(target)):
            continue
        found = False
        for key in tree.declarations(target):
            declaration = find_declaration(tree.record(key), target)
            if declaration is not None and declaration.get("type") == kind:
                found = True
                break
        if not found:
            raise ValidationError(
                f"reference {{type: {kind!r}, ref: {target!r}}} does not resolve to a "
                f"{kind} declared in this document"
            )


def _manifest_entries(node: Node, url: str | None) -> list[ExtensionManifestEntry]:
    """Return the parsed manifest of the document at `url` in the node's tree.

    Malformed entries are skipped here; `manifest_well_formed` reports them.
    """
    if url is None:
        return []
    entries: list[ExtensionManifestEntry] = []
    for raw in node.tree.manifests.get(url, ()):
        try:
            entries.append(ExtensionManifestEntry.from_dict(raw))
        except ValueError:
            continue
    return entries


def _entry_types(node: Node) -> tuple[str, ...]:
    """The types a node's declaring entry carries besides traits: its type and path type."""
    path = node.record.path
    if path is not None and is_extension_type(path.type):
        return (node.type, path.type)
    return (node.type,)


def _require_declared(
    type_name: str, entries: list[ExtensionManifestEntry], where: str
) -> None:
    """Raise unless `type_name` is a keyword or is covered by `entries`."""
    if not is_extension_type(type_name):
        return
    if not any(entry.covers(type_name) for entry in entries):
        raise ValidationError(
            f"extension type {type_name!r} is not declared in the "
            f"`extensionManifest` of {where!r}"
        )


def extension_types_declared(node: Node) -> None:
    """Every URI node / trait / path type is declared by the document that uses it.

    A resolved boundary node spans two documents: the traits and path type of
    its declaring entry are checked against the declaring document's manifest,
    the target's own traits against the target document's, and the node type
    against both.
    """
    if node.is_detached:
        return
    own_url = node.document_url
    own_entries = _manifest_entries(node, own_url)
    edge = node.record.edge
    if edge is None:
        for type_name in (*_entry_types(node), *node.traits):
            _require_declared(type_name, own_entries, str(own_url))
        return
    entry_entries = _manifest_entries(node, edge.origin_url)
    for type_name in _entry_types(node):
        _require_declared(type_name, entry_entries, str(edge.origin_url))
    _require_declared(node.type, own_entries, str(own_url))
    for trait_type in edge.traits:
        _require_declared(trait_type, entry_entries, str(edge.origin_url))
    for trait_type in node.traits:
        if trait_type not in edge.traits:
            _require_declared(trait_type, own_entries, str(own_url))


def manifest_well_formed(node: Node) -> None:
    """At a document root, the `extensionManifest` meets the spec's MUSTs.

    Runs on the node that opens a document (the tree root, or a node whose
    document differs from its parent's). Every entry must parse, extension ids
    must be unique within the manifest, and every entry must list at least one
    schema of a known kind (`jsonschema` or `linkml`).
    """
    url = node.document_url
    if url is None:
        return
    parent = node.parent()
    if parent is not None and parent.document_url == url:
        return
    seen: set[str] = set()
    for raw in node.tree.manifests.get(url, ()):
        try:
            entry = ExtensionManifestEntry.from_dict(raw)
        except ValueError as exc:
            raise ValidationError(
                f"malformed `extensionManifest` entry: {exc}"
            ) from exc
        if entry.id in seen:
            raise ValidationError(
                f"extension {entry.id!r} is declared twice in the "
                f"`extensionManifest` of {url!r}"
            )
        seen.add(entry.id)
        if not entry.schemas:
            raise ValidationError(
                f"extension {entry.id!r} lists no schema; the manifest entry "
                "needs at least one"
            )
        for schema in entry.schemas:
            if schema.type not in SCHEMA_TYPES:
                raise ValidationError(
                    f"extension {entry.id!r} lists a schema of unknown kind "
                    f"{schema.type!r}; known kinds are {sorted(SCHEMA_TYPES)}"
                )


def _require_understood(
    type_name: str, entries: list[ExtensionManifestEntry], registered: set[str]
) -> None:
    """Raise if `type_name` belongs to a `mustUnderstand` extension not in `registered`."""
    if not is_extension_type(type_name):
        return
    for entry in entries:
        if (
            entry.must_understand
            and entry.covers(type_name)
            and (entry.id not in registered)
        ):
            raise ValidationError(
                f"extension type {type_name!r} belongs to {entry.id!r}, which is "
                "flagged `mustUnderstand` but is not registered in this process "
                "(`register_extension`)"
            )


def must_understand_supported(node: Node) -> None:
    """URI types of `mustUnderstand` extensions are understood by this process.

    "Understood" means the extension is registered in the default registry
    (`EXTENSIONS`, via `register_extension`). The declaring-entry / target split
    follows `extension_types_declared`.
    """
    if node.is_detached:
        return
    from ngio_collections.api._extensions import EXTENSIONS

    registered = {entry.id for entry in EXTENSIONS}
    own_entries = _manifest_entries(node, node.document_url)
    edge = node.record.edge
    if edge is None:
        for type_name in (*_entry_types(node), *node.traits):
            _require_understood(type_name, own_entries, registered)
        return
    entry_entries = _manifest_entries(node, edge.origin_url)
    for type_name in _entry_types(node):
        _require_understood(type_name, entry_entries, registered)
    _require_understood(node.type, own_entries, registered)
    for trait_type in edge.traits:
        _require_understood(trait_type, entry_entries, registered)
    for trait_type in node.traits:
        if trait_type not in edge.traits:
            _require_understood(trait_type, own_entries, registered)


def external_unresolved(node: Node) -> None:
    """In a resolved view, a node still external could not be resolved.

    A node whose path is URI-typed locates data and is never resolved; it is
    not reported.
    """
    if node.tree.mode != "resolved" or node.parent() is None:
        return
    path = node.record.path
    if node.is_external and (path is None or path.is_document):
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
    """Opt-in: every path object on the node uses the core `relative` format and a built-in type."""
    path = node.record.path
    if path is not None:
        _require_core_path(path.type, path.format, path.href, "node path")
    for container in (node.record.fields, node.record.traits):
        for obj in _walk_path_objects(dict(container)):
            _require_core_path(
                str(obj.get("type")),
                str(obj.get("format")),
                str(obj.get("href")),
                "path object",
            )


def _require_core_path(type_: str, format_: str, href: str, what: str) -> None:
    """Raise unless the path uses a built-in type and the `relative` format."""
    if type_ not in BUILTIN_PATH_TYPES:
        raise ValidationError(f"{what} uses non-core type {type_!r} (href {href!r})")
    if format_ != "relative":
        raise ValidationError(
            f"{what} uses non-core format {format_!r} (href {href!r})"
        )


CORE_VALIDATORS = (
    id_is_valid,
    known_types,
    node_fields_allowed,
    multiscale_is_complete,
    multiscale_transformations_wellformed,
    no_embedded_multiscale,
    references_resolve,
    extension_types_declared,
    manifest_well_formed,
    must_understand_supported,
    external_unresolved,
)
"""The structural checks every revision-2 document must pass."""
