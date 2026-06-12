"""First-class MetadataDocument: the unit of provenance, serialization, and saving.

A ``MetadataDocument`` corresponds to exactly ONE metadata file — either a standalone
``*.json`` (``{"ome": payload}``) or a ``zarr.json`` envelope
(``{"attributes": {"ome": payload}}``). ``MetadataDocument.serialize()`` is the single
emission path (DESIGN.md §3.1, §3.6); the ``ome`` version lives here, off the
node models.

Detachment semantics: ``model_copy()`` and re-validation produce a node with
``_document is None``. A detached node cannot be saved directly — saving goes
through its owning :class:`MetadataDocument`, so re-attach by grafting the node into a
parsed tree (or re-parse) before saving.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from ome_zarr_collections.models.base import BaseNode, PathObj
from ome_zarr_collections.models.nodes import validate_node
from ome_zarr_collections.registry import DEFAULT_REGISTRY, NodeRegistry

MetadataDocumentForm = Literal["json", "zarr"]

DEFAULT_VERSION = "0.x"


class NotOmeDocumentError(ValueError):
    """The target parses as JSON but is not an OME metadata document.

    Distinguishes a *data leaf* (e.g. a plain Zarr array's ``zarr.json``
    behind a stub path) from genuinely malformed metadata, so callers like
    ``Resolver.resolve_tree(on_error="skip")`` can skip the former without
    masking the latter.
    """


@dataclass
class MetadataDocument:
    """One parsed metadata document and its provenance.

    Attributes:
        root: The document's root node.
        url: Full URL of the metadata document.
        form: ``"json"`` for a standalone ``*.json`` document, ``"zarr"`` for
            a ``zarr.json`` envelope.
        version: The ``ome`` version of this document.
        stub_path: How the parent document references this one; ``None`` for
            a top-level document.
    """

    root: BaseNode
    url: str
    form: MetadataDocumentForm
    version: str
    stub_path: PathObj | None = None

    def serialize_payload(self) -> dict[str, JsonValue]:
        """The value of this document's ``ome`` key (version on the root).

        Pure (no IO). While dumping, a child node whose ``_document`` is set
        and differs from this document is emitted as a path stub using that
        document's ``stub_path``.
        """
        _assert_unique_ids(self.root)
        payload: dict[str, JsonValue] = {"version": self.version}
        payload.update(_dump_node(self.root, self))
        return payload

    def serialize(self) -> dict[str, JsonValue]:
        """Spec-shaped dict for this document, wrapped in its envelope form.

        Note: for the zarr form this builds a *fresh* envelope; preserving
        sibling keys of an existing ``zarr.json`` is the resolver's
        read-modify-write job (``Resolver.save``).
        """
        payload = self.serialize_payload()
        if self.form == "json":
            return {"ome": payload}
        return {
            "zarr_format": 3,
            "node_type": "group",
            "attributes": {"ome": payload},
        }

    def serialize_bytes(self) -> bytes:
        """UTF-8 JSON bytes of :meth:`serialize`."""
        return json.dumps(self.serialize(), indent=2).encode()


def parse_metadata_document(
    data: bytes | str | dict,
    *,
    url: str,
    registry: NodeRegistry = DEFAULT_REGISTRY,
    stub_path: PathObj | None = None,
) -> MetadataDocument:
    """Parse one metadata document, detecting its envelope form.

    Pure (no IO). Detects the ``json`` vs ``zarr`` form from the envelope,
    validates the payload through ``registry``, checks that node ids are
    unique within the document, and sets the ``_document`` / ``_parent``
    provenance back-references on every parsed node.
    """
    if isinstance(data, (bytes, str)):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError("document must be a JSON object")
    if "ome" in data:
        payload, form = data["ome"], "json"
    elif isinstance(data.get("attributes"), dict) and "ome" in data["attributes"]:
        payload, form = data["attributes"]["ome"], "zarr"
    else:
        raise NotOmeDocumentError(
            "no 'ome' metadata found (expected at the document root or under "
            "'attributes')"
        )
    if not isinstance(payload, dict):
        raise ValueError("'ome' metadata must be a JSON object")

    # The version belongs to the MetadataDocument, not the node model (DESIGN.md §3.1).
    payload = dict(payload)
    version = payload.pop("version", DEFAULT_VERSION)
    if not isinstance(version, str):
        raise ValueError(f"'version' must be a string, got {version!r}")

    root = validate_node(payload, context={"registry": registry})
    _assert_unique_ids(root)

    document = MetadataDocument(
        root=root, url=url, form=form, version=version, stub_path=stub_path
    )
    _set_provenance(document)
    return document


def _set_provenance(document: MetadataDocument) -> None:
    """Set the ``_document`` / ``_parent`` back-references on every node."""
    stack: list[tuple[BaseNode, BaseNode | None]] = [(document.root, None)]
    while stack:
        node, parent = stack.pop()
        node._document = document
        node._parent = parent
        for child in getattr(node, "nodes", None) or []:
            if isinstance(child, BaseNode):
                stack.append((child, node))


def _assert_unique_ids(root: BaseNode) -> None:
    """Node ids MUST be unique within a single JSON document."""
    seen: set[str] = set()
    stack: list[BaseNode] = [root]
    while stack:
        node = stack.pop()
        if node.id in seen:
            raise ValueError(f"duplicate node id {node.id!r} in document")
        seen.add(node.id)
        children = getattr(node, "nodes", None) or []
        stack.extend(child for child in children if isinstance(child, BaseNode))


def _dump_node(node: BaseNode, document: MetadataDocument) -> dict[str, JsonValue]:
    """Dump one node, recursing into children and emitting stubs for
    children owned by a different document (DESIGN.md §3.6)."""
    data = node.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude={"nodes"}
    )
    # `attributes` is optional in the spec; don't emit an empty dict.
    if data.get("attributes") == {}:
        data.pop("attributes")
    children = getattr(node, "nodes", None)
    if children is None:
        return data
    dumped: list[JsonValue] = []
    for child in children:
        if not isinstance(child, BaseNode):
            dumped.append(child)
        elif child._document is not None and child._document is not document:
            dumped.append(_stub_for(child))
        else:
            dumped.append(_dump_node(child, document))
    data["nodes"] = dumped
    return data


def _stub_for(child: BaseNode) -> dict[str, JsonValue]:
    """The path-stub emission of an externalized child."""
    assert child._document is not None
    stub_path = child._document.stub_path
    if stub_path is None:
        raise ValueError(
            f"node {child.id!r} belongs to externalized document "
            f"{child._document.url!r} which has no stub_path; the enclosing "
            "document cannot reference it"
        )
    return {
        "type": child.type,
        "id": child.id,
        "name": child.name,
        "path": stub_path.model_dump(mode="json", by_alias=True),
    }
