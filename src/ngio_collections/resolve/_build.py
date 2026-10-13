"""The pure, synchronous tree builder: parsed documents → a `NodeTree`.

`build` walks an entry document's payload and produces a `NodeTree`, with no IO
of its own — every document it might need is supplied up front in `docs` (the
`fetch_all` shell gathers them). A `nodes` entry is either a *declaration*
(carries `id`; its body is every non-structural key) or a *reference* (carries
`ref` and usually a document `path`); both or neither is a document error. Two
modes:

- `inline=False` (open): each reference becomes a *reference* record; the tree
  spans one document and stays editable.
- `inline=True` (open_inlined): each resolvable reference is replaced in place
  by the declaration it points at — the node whose `id` equals `ref`, looked up
  inside the document at `path` (its root and inline children, not through
  further references). The spliced node keeps its own id, name, body and
  children; nothing from the reference overlays it. The result is a `resolved`
  collection.

Resolution degrades gracefully and deterministically: a reference is left in
place when the hop budget is exhausted (`depth`), a cycle is hit, the target
document was not fetched, no node declares `ref` in it, or its type does not
match — `on_error` chooses between leaving the reference (`"skip"`) and raising
(`"raise"`). A bare `ref` (no `path`) is always left in place. Identity is the
structural `NodeId` path, so the same document inlined twice yields distinct
nodes with no id rewriting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from ngio_collections._types import JSONValue

from ngio_collections.graph import (
    ROOT,
    NodeId,
    NodeRecord,
    NodeTree,
    Reference,
    TreeBuilder,
)
from ngio_collections.models._paths import DocPath, meta_url
from ngio_collections.resolve._document import Document

OnError = Literal["skip", "raise"]

Docs = Mapping[str, Document]

STRUCTURAL_KEYS = frozenset({"type", "id", "name", "nodes", "ref", "path"})
"""Wire keys that shape a node; every other key is the node's body."""


def build(
    entry_url: str,
    docs: Docs,
    *,
    inline: bool,
    depth: int | None = None,
    on_error: OnError = "skip",
) -> NodeTree:
    """Build a `NodeTree` from the document at `entry_url` using `docs`.

    Args:
        entry_url: The entry document's location (normalised internally).
        docs: A mapping of normalised document URL → parsed `Document`; must
            contain at least `entry_url`.
        inline: Whether to splice resolvable references in place.
        depth: Max boundary hops to follow when inlining (`None` unlimited,
            `0` = entry document only).
        on_error: `"skip"` leaves unresolvable references as reference records;
            `"raise"` propagates the failure.

    Returns:
        A `NodeTree` (`editable` when `inline=False`, else `resolved`).

    Raises:
        KeyError: If `entry_url` is not present in `docs`.
        ValueError: If the entry document carries no OME metadata, or a node
            carries both `id` and `ref` or neither (regardless of `on_error`).
    """
    entry_url = meta_url(entry_url)
    doc = docs[entry_url]
    if not doc.has_payload:
        raise ValueError(f"document at {entry_url!r} carries no `ome` metadata")
    if "id" not in doc.root:
        raise ValueError(f"document root at {entry_url!r} declares no `id`")
    mode = "resolved" if inline else "editable"
    tree = TreeBuilder(_materialized_record(doc.root, doc.url), mode=mode)
    builder = _Builder(docs, inline, on_error)
    builder.add_children(tree, ROOT, doc.root, doc, depth, frozenset({entry_url}))
    return tree.finish()


@dataclass(frozen=True, slots=True)
class _Resolved:
    """How one payload dict materialises: the record plus how to recurse into it.

    `children_source` is the node dict whose `nodes` should be recursed (the dict
    itself for a declaration, the found declaration for an inlined reference), or
    `None` to stop (a leaf, or a reference left in place). `doc`, `depth`, and
    `ancestors` are the context that recursion continues under.
    """

    record: NodeRecord
    children_source: dict | None
    doc: Document
    depth: int | None
    ancestors: frozenset[str]


class _Builder:
    """Carries the immutable build context while recursing the payload tree."""

    def __init__(self, docs: Docs, inline: bool, on_error: OnError) -> None:
        """Bind the document set and the inline / error policy for this build."""
        self.docs = docs
        self.inline = inline
        self.on_error = on_error

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
        """Decide whether `node_dict` is a declaration, a reference, or inlined."""
        has_ref, has_id = "ref" in node_dict, "id" in node_dict
        if has_ref == has_id:
            raise ValueError(
                f"node {node_dict.get('type')!r} in {doc.url!r} must carry exactly "
                "one of `id` (a declaration) or `ref` (a reference)"
            )
        if has_id:
            record = _materialized_record(node_dict, doc.url)
            return _Resolved(record, node_dict, doc, depth, ancestors)
        if not self.inline or "path" not in node_dict:
            return _Resolved(
                _reference_record(node_dict, doc.url), None, doc, depth, ancestors
            )
        return self._inline_reference(node_dict, doc, depth, ancestors)

    def _inline_reference(
        self,
        node_dict: dict,
        doc: Document,
        depth: int | None,
        ancestors: frozenset[str],
    ) -> _Resolved:
        """Try to splice the declaration `node_dict` points at; else leave it."""
        stub = _reference_record(node_dict, doc.url)
        leave = _Resolved(stub, None, doc, depth, ancestors)
        if depth == 0:
            return leave  # hop budget exhausted
        assert stub.ref is not None and stub.ref.path is not None
        try:
            target_url = meta_url(stub.ref.path.resolve(doc.url))
        except Exception:
            if self.on_error == "raise":
                raise
            return leave
        if target_url in ancestors:
            return leave  # cycle
        target = self.docs.get(target_url)
        if target is None:
            if self.on_error == "raise":
                raise FileNotFoundError(
                    f"reference target {target_url!r} was not fetched"
                )
            return leave
        found = _find_declared(target.root, stub.ref.ref)
        if found is None:
            if self.on_error == "raise":
                raise LookupError(
                    f"no node declares id {stub.ref.ref!r} in {target_url!r}"
                )
            return leave
        if node_dict.get("type") != found.get("type"):
            if self.on_error == "raise":
                raise TypeError(
                    f"reference type {node_dict.get('type')!r} does not match "
                    f"node {stub.ref.ref!r} of type {found.get('type')!r} "
                    f"in {target_url!r}"
                )
            return leave
        next_depth = None if depth is None else depth - 1
        return _Resolved(
            _materialized_record(found, target.url),
            found,
            target,
            next_depth,
            ancestors | {target_url},
        )


def _body(node_dict: dict) -> Mapping[str, JSONValue]:
    """Return a node dict's body: every key that is not structural, in order."""
    return {k: v for k, v in node_dict.items() if k not in STRUCTURAL_KEYS}


def _materialized_record(node_dict: dict, origin_url: str) -> NodeRecord:
    """Build the record for a declaration (branch when it has `nodes`)."""
    return NodeRecord(
        type=node_dict["type"],
        name=node_dict.get("name"),
        id=node_dict["id"],
        attributes=_body(node_dict),
        children=() if "nodes" in node_dict else None,
        origin_url=origin_url,
    )


def _reference_record(node_dict: dict, origin_url: str) -> NodeRecord:
    """Build a reference record (a left-in-place `{type, ref, path?}` entry)."""
    path = node_dict.get("path")
    return NodeRecord(
        type=node_dict["type"],
        ref=Reference(
            ref=node_dict["ref"],
            path=None if path is None else DocPath.model_validate(path),
        ),
        origin_url=origin_url,
    )


def _find_declared(root: dict, ref: str) -> dict | None:
    """Return the node dict declaring `id == ref` in `root`'s inline tree, if any.

    Walks the root and the `nodes` of declarations only; entries that are
    themselves references are not followed (lookup is not transitive).
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if "ref" in node:
            continue
        if node.get("id") == ref:
            return node
        stack.extend(reversed(node.get("nodes") or ()))
    return None
