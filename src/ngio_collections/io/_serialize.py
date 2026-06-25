"""Serialization bridge between node trees and metadata documents.

Module-level helpers used by the `Resolver`: classify a URL to its document
class, stamp a parsed tree with its owning document, dump a node subtree to its
OME-payload dict (relativizing co-located reference paths), and rebuild an
editable root from a payload. Kept apart from the `Resolver` orchestration so
the read/write wire format lives in one place.
"""

from __future__ import annotations

from ngio_collections.treeops._jsonrefs import relativize_attr_refs
from ngio_collections.io._document import (
    VERSION,
    JsonMetadataDocument,
    MetadataDocument,
    ZarrMetadataDocument,
)
from ngio_collections.models._config import NodeStateError
from ngio_collections.models._nodes import (
    BaseNode,
    Node,
    RefNode,
    set_private,
    build_node,
)
from ngio_collections.models._paths import meta_url as _clean_url
from ngio_collections.models._references import ReferenceObj

ZARR_METADATA_FILE = "zarr.json"


def _ref_target(ref: ReferenceObj) -> tuple[str, str]:
    """Return the `(document url, node id)` a `ReferenceObj` points at.

    A portable `ReferenceObj` must carry an absolute locator (as minted by
    `node.ref()`): it is resolved with no base, so a relative path has nothing to
    resolve against.

    Args:
        ref: A reference locator carrying an absolute path and the target id.

    Returns:
        The normalised document URL and the referenced node's id.

    Raises:
        NodeStateError: If `ref` is a same-document pointer (`path is None`) and
            so has no document to open.
        ValueError: If `ref.path` is relative (no base to resolve against).
    """
    if ref.path is None:
        raise NodeStateError(
            f"reference {ref.id!r} is a same-document pointer (path=None); "
            "it has no document to open"
        )
    return _clean_url(ref.path.resolve(None)), ref.id


def _classify_url(url: str) -> type[MetadataDocument]:
    """Return the document class that should parse `url`."""
    if url.endswith(".json") and not url.endswith(ZARR_METADATA_FILE):
        return JsonMetadataDocument
    return ZarrMetadataDocument


def _assign_document(node: BaseNode, doc: MetadataDocument) -> None:
    """Stamp `doc` as the owning document of every node in a parsed tree.

    Args:
        node: Root of the tree to stamp.
        doc: The document that owns `node` and all its descendants.
    """
    set_private(node, "_document", doc)
    for child in getattr(node, "nodes", None) or ():
        _assign_document(child, doc)


def _dump_node(node: BaseNode, document: MetadataDocument, relativize: bool) -> dict:
    """Serialize one node (and its subtree) to its OME-payload dict.

    Embedded children serialize inline; `RefNode` stubs serialize as path
    references. When `relativize` is `True`, a stub's path AND any reference path
    embedded in `attributes` are rewritten relative to the document's `url` if
    they are co-located local paths (best-effort: remote, cross-root, and
    already-relative paths are kept verbatim). The base is `dirname(document.url)`
    — the same base resolution uses — so a relativized path round-trips. None
    fields and an empty `attributes` dict are dropped so an unedited document
    re-serializes identically.

    Args:
        node: The node to serialize.
        document: The document being written, used as the relativization base.
        relativize: Whether to relativize co-located local stub paths.

    Returns:
        A JSON-serializable dict representing `node` in the OME wire format.
    """
    base_url = document.url
    data = node.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude={"nodes"}
    )
    if relativize and "attributes" in data:
        data["attributes"] = relativize_attr_refs(data["attributes"], base_url)
    if data.get("attributes") == {}:
        data.pop("attributes")
    if isinstance(node, RefNode):
        path = node.path.relativize(base_url) if relativize else node.path
        data["path"] = path.model_dump(mode="json", by_alias=True)
    children: tuple[BaseNode, ...] | None = getattr(node, "nodes", None)
    if children is None:  # a RefNode leaf: no embedded children
        return data
    data["nodes"] = [_dump_node(child, document, relativize) for child in children]
    return data


def _doc_payload(root: BaseNode, document: MetadataDocument, relativize: bool) -> dict:
    """Return the full OME payload for a document rooted at `root`.

    The `version` is a document-envelope key, stamped at the payload top and kept
    off the node itself so it never nests into embedded children.

    Args:
        root: The root node of the document.
        document: The document being written (relativization base).
        relativize: Whether to relativize co-located local stub paths.

    Returns:
        The OME payload dict (`version` + the dumped root node).
    """
    return {"version": VERSION, **_dump_node(root, document, relativize)}


def _node_from_payload(payload: dict) -> Node:
    """Build the editable root node from a document's OME payload.

    Args:
        payload: The OME payload dict (may carry the envelope `version`).

    Returns:
        The editable root `Node`, with `version` stripped off.
    """
    return build_node({k: v for k, v in payload.items() if k != "version"})
