"""The pure, synchronous tree builder: parsed documents → a `NodeTree`.

`build` walks an entry document's payload and produces a `NodeTree`, with no IO
of its own: every document it might need is supplied up front in `docs` (the
`fetch_all` shell gathers them). Two modes:

- `inline=False` (`open`): each external node (one with a `path`) stays an
  external record; the tree spans one document and stays editable.
- `inline=True` (`open_resolved`): each resolvable external node is spliced
  into the tree in place. The target document's root replaces it, keeping the
  target's type, id, fields and children; the traits of the two are combined
  with the declaring entry winning per trait type (RFC-8 rev. 1 §3.1), and the
  declaring entry's name wins when it has one. The result is a read-only
  `resolved` tree that is a *view*: serializing it emits the declaring entries
  again, never a target's body.

Resolution degrades gracefully and deterministically: a node is left external
when the hop budget is exhausted (`depth`), its path format is outside `formats`,
a cycle is hit, the target was not fetched, its root type does not match, or its
root id does not match (the revision requires the declaring entry and the target
root to share one UUID). `on_error` chooses between leaving the node (`"skip"`)
and raising (`"raise"`). A node whose target carries no OME metadata is left in
place under *either* policy: its `path` locates plain data, so there is nothing
to resolve. Identity is the structural `NodeId` path, so the same document
resolved twice yields distinct nodes with no id rewriting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from ngio_collections.graph import (
    RESERVED_NODE_KEYS,
    ROOT,
    EdgeInfo,
    NodeId,
    NodeRecord,
    NodeTree,
    TreeBuilder,
    merge_traits,
    traits_from_list,
)
from ngio_collections.models._paths import (
    ALL_FORMATS,
    DocPath,
    UnsupportedPathFormatError,
    meta_url,
)
from ngio_collections.resolve._document import Document

OnError = Literal["skip", "raise"]

Docs = Mapping[str, Document]


class TypeMismatchError(TypeError):
    """An external node's `type` differs from its target document's root type."""


class IdMismatchError(ValueError):
    """An external node's `id` differs from its target document's root id."""


class CycleError(ValueError):
    """Resolving node paths looped back into an enclosing document."""


def build(
    entry_url: str,
    docs: Docs,
    *,
    inline: bool,
    depth: int | None = None,
    on_error: OnError = "skip",
    formats: frozenset[str] = ALL_FORMATS,
) -> NodeTree:
    """Build a `NodeTree` from the document at `entry_url` using `docs`.

    Args:
        entry_url: The entry document's location (normalised internally).
        docs: A mapping of normalised document URL → parsed `Document`; must
            contain at least `entry_url`.
        inline: Whether to splice resolvable external nodes in place.
        depth: Max boundary hops to follow when resolving (`None` unlimited,
            `0` = entry document only).
        on_error: `"skip"` leaves unresolvable nodes external; `"raise"`
            propagates the failure.
        formats: Path formats to resolve; a node in another format stays
            external under either `on_error` (the spec's "unavailable").

    Returns:
        A `NodeTree` (`editable` when `inline=False`, else `resolved`).

    Raises:
        KeyError: If `entry_url` is not present in `docs`.
        ValueError: If the entry document carries no OME metadata, or a node
            dict is malformed (no `id`, both `nodes` and `path`, bad traits).
    """
    entry_url = meta_url(entry_url)
    doc = docs[entry_url]
    if not doc.has_payload:
        raise ValueError(f"document at {entry_url!r} carries no `ome` metadata")
    mode = "resolved" if inline else "editable"
    builder = _Builder(docs, inline, on_error, formats)
    manifests = {
        u: d.extension_manifest for u, d in docs.items() if d.extension_manifest
    }
    tree = TreeBuilder(
        builder.node_record(doc.root, doc.url), mode=mode, manifests=manifests
    )
    builder.add_children(tree, ROOT, doc.root, doc, depth, frozenset({entry_url}))
    return tree.finish()


@dataclass(frozen=True, slots=True)
class _Resolved:
    """How one payload dict materialises: the record plus how to recurse into it.

    `children_source` is the node dict whose `nodes` should be recursed (the dict
    itself for an embedded node, the target root for a resolved external node),
    or `None` to stop (a leaf, or a node left external). `doc`, `depth`, and
    `ancestors` are the context that recursion continues under.
    """

    record: NodeRecord
    children_source: dict | None
    doc: Document
    depth: int | None
    ancestors: frozenset[str]


class _Builder:
    """Carries the immutable build context while recursing the payload tree."""

    def __init__(
        self, docs: Docs, inline: bool, on_error: OnError, formats: frozenset[str]
    ) -> None:
        """Bind the document set and the inline / error / format policy."""
        self.docs = docs
        self.inline = inline
        self.on_error = on_error
        self.formats = formats

    # -- node dict → record -------------------------------------------------

    def node_record(self, node_dict: dict, origin_url: str) -> NodeRecord:
        """Build the record for `node_dict` (embedded, branch or external).

        Raises:
            ValueError: If the dict has no `id`, carries both `nodes` and
                `path`, or its traits are malformed (not objects with a string
                `type`, or two traits of one type).
        """
        node_id = node_dict.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(
                f"node of type {node_dict.get('type')!r} in {origin_url!r} has no id"
            )
        if "nodes" in node_dict and node_dict.get("path") is not None:
            raise ValueError(
                f"node {node_id!r} carries both `nodes` and `path`; a declaration "
                "is embedded or external, never both"
            )
        path = node_dict.get("path")
        return NodeRecord(
            type=node_dict["type"],
            id=node_id,
            name=node_dict.get("name"),
            traits=traits_from_list(node_dict.get("traits")),
            fields=_fields(node_dict),
            children=() if "nodes" in node_dict else None,
            path=None if path is None else DocPath.model_validate(path),
            origin_url=origin_url,
        )

    # -- recursion ----------------------------------------------------------

    def add_children(
        self,
        tree: TreeBuilder,
        parent_key: NodeId,
        source: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> None:
        """Add every child in `source["nodes"]` under `parent_key`, recursively."""
        for child_dict in source.get("nodes") or ():
            self._add_node(tree, parent_key, child_dict, doc, depth, ancestors)

    def _add_node(
        self,
        tree: TreeBuilder,
        parent_key: NodeId,
        node_dict: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> None:
        """Resolve `node_dict`, attach it under `parent_key`, and recurse."""
        resolved = self._resolve(node_dict, doc, depth, ancestors)
        key = tree.add_child(parent_key, resolved.record)
        if resolved.children_source is not None:
            self.add_children(
                tree,
                key,
                resolved.children_source,
                resolved.doc,
                resolved.depth,
                resolved.ancestors,
            )

    def _resolve(
        self,
        node_dict: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> _Resolved:
        """Decide whether `node_dict` is embedded, left external, or resolved."""
        record = self.node_record(node_dict, doc.url)
        if record.path is None:
            return _Resolved(record, node_dict, doc, depth, ancestors)
        if not self.inline:
            return _Resolved(record, None, doc, depth, ancestors)
        return self._resolve_external(record, doc, depth, ancestors)

    def _resolve_external(
        self,
        stub: NodeRecord,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> _Resolved:
        """Try to splice the external node `stub`'s target in; else leave it."""
        assert stub.path is not None
        leave = _Resolved(stub, None, doc, depth, ancestors)
        if depth == 0:
            return leave  # hop budget exhausted
        try:
            target_url = stub.path.meta_url(doc.url, formats=self.formats)
        except UnsupportedPathFormatError:
            return leave  # the spec's "treat the node as unavailable"
        except Exception:
            if self.on_error == "raise":
                raise
            return leave
        if target_url in ancestors:
            if self.on_error == "raise":
                raise CycleError(
                    f"node {stub.id!r} resolves back into enclosing document "
                    f"{target_url!r}"
                )
            return leave
        target = self.docs.get(target_url)
        if target is None:
            if self.on_error == "raise":
                raise FileNotFoundError(
                    f"target document {target_url!r} was not fetched"
                )
            return leave
        if not target.has_payload:
            # The target is data, not a document: the `path` locates a plain Zarr
            # array. Nothing to resolve, and nothing wrong: the node is whole.
            return leave
        if stub.type != target.root.get("type"):
            if self.on_error == "raise":
                raise TypeMismatchError(
                    f"node type {stub.type!r} does not match target root type "
                    f"{target.root.get('type')!r} at {target_url!r}"
                )
            return leave
        if stub.id != target.root.get("id"):
            if self.on_error == "raise":
                raise IdMismatchError(
                    f"node id {stub.id!r} does not match target root id "
                    f"{target.root.get('id')!r} at {target_url!r}; a declaring "
                    "entry and the root of its document share one UUID"
                )
            return leave
        merged = self._merge_record(stub, target.root, target.url)
        next_depth = None if depth is None else depth - 1
        return _Resolved(
            merged, target.root, target, next_depth, ancestors | {target_url}
        )

    def _merge_record(
        self, stub: NodeRecord, target_root: dict, target_url: str
    ) -> NodeRecord:
        """Splice a target root into the place of its declaring entry `stub`.

        The target supplies type, id, fields and children; traits are combined
        with the declaring entry winning per type; the declaring entry's name
        wins when set. The entry's own pre-merge values survive on `edge`, so
        serializing the resolved node emits the entry again, unchanged.
        """
        assert stub.path is not None
        target = self.node_record(target_root, target_url)
        return NodeRecord(
            type=target.type,
            id=target.id,
            name=stub.name if stub.name is not None else target.name,
            traits=merge_traits(target.traits, stub.traits),
            fields=target.fields,
            children=target.children,
            origin_url=target_url,
            edge=EdgeInfo(
                path=stub.path,
                traits=stub.traits,
                fields=stub.fields,
                name=stub.name,
                origin_url=stub.origin_url,
            ),
        )


def _fields(node_dict: dict) -> dict:
    """Return the node-type fields of a node dict (everything not reserved)."""
    return {k: v for k, v in node_dict.items() if k not in RESERVED_NODE_KEYS}
