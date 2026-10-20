"""The async shell: gather every document a build will need, concurrently.

This is the only async code in resolution. `fetch_all` walks the reference graph
breadth-first from an entry document, reading each document through the store and
following the `path` of every node up to `depth`, bounded by `concurrency`. The
pure `reference_targets` helper supplies the frontier (which URLs a document
points at); the build that follows is pure and reads everything from the returned
`docs` map. Discovery and reading are interleaved because a document's references
are only known once it is parsed, but no resolution *logic* lives here.

Reads are best-effort: a document that cannot be fetched is simply absent from
`docs`, and `build` then leaves the referring node external (or raises, per its
`on_error`). A document that *was* read but carries no OME payload is kept, marked
`has_payload=False`; `build` needs that distinction, since such a node points at
data rather than at a broken reference.

Only node paths are followed. The `path` inside a typed reference (a scene
transform's `input`, say) only *locates* a declaration; following those for every
collection would re-read every image. `trait_reference_targets` lists them for
callers that want to.
"""

from __future__ import annotations

import asyncio
from typing import Iterator, Mapping

from ngio_collections._types import JSONValue
from ngio_collections.io.store import AsyncReadableStore, default_store
from ngio_collections.models._paths import ALL_FORMATS, DocPath, meta_url
from ngio_collections.resolve._document import Document


def reference_targets(
    doc: Document, *, formats: frozenset[str] = ALL_FORMATS
) -> Iterator[str]:
    """Yield the normalised URL of every external node declared in `doc`.

    Mirrors the resolution in `build`: each node dict carrying a `path` is
    resolved against `doc.url` and normalised to its metadata-file URL, so the
    yielded keys match the ones `fetch_all` caches under. Malformed paths and
    paths in a format outside `formats` are skipped (the build re-resolves and
    reports them).
    """
    for node_dict in _walk_nodes(doc.root):
        path = node_dict.get("path")
        if path is None:
            continue
        try:
            yield DocPath.model_validate(path).meta_url(doc.url, formats=formats)
        except Exception:
            continue


def trait_reference_targets(
    doc: Document, *, formats: frozenset[str] = ALL_FORMATS
) -> Iterator[str]:
    """Yield the URL of every document a typed reference in `doc` points into.

    Walks the traits and fields of every node (not the `nodes` tree itself) for
    `{type, ref, path}` objects and resolves their `path`. Not used by
    `fetch_all`; see the module docstring.
    """
    for node_dict in _walk_nodes(doc.root):
        for key, value in node_dict.items():
            if key == "nodes":
                continue
            for ref in _walk_references(value):
                try:
                    path = DocPath.model_validate(ref["path"])
                    yield path.meta_url(doc.url, formats=formats)
                except Exception:
                    continue


def _walk_nodes(node_dict: dict) -> Iterator[dict]:
    """Yield `node_dict` and every descendant node dict, depth-first."""
    yield node_dict
    for child in node_dict.get("nodes") or ():
        yield from _walk_nodes(child)


def _walk_references(value: object) -> Iterator[Mapping[str, JSONValue]]:
    """Yield every `{type, ref, path}` reference object nested in `value`."""
    if isinstance(value, Mapping):
        if (
            isinstance(value.get("ref"), str)
            and isinstance(value.get("type"), str)
            and isinstance(value.get("path"), Mapping)
        ):
            yield value
        for item in value.values():
            yield from _walk_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_references(item)


async def fetch_all(
    entry_url: str,
    store: AsyncReadableStore | None = None,
    *,
    depth: int | None = None,
    concurrency: int = 16,
    formats: frozenset[str] = ALL_FORMATS,
    docs: Mapping[str, Document] | None = None,
) -> dict[str, Document]:
    """Fetch the entry document and every document reachable within `depth`.

    Args:
        entry_url: The entry document's location (normalised internally).
        store: The store to read through; defaults to the scheme-routed store
            (`LocalStore` for local paths, `HttpStore` for `http(s)://`).
        depth: Max boundary hops to follow (`None` unlimited, `0` = entry only).
        concurrency: Max documents read at once.
        formats: Path formats to follow; others are treated as unavailable.
        docs: Documents already in hand (a cache); they are reused, not re-read.

    Returns:
        A mapping of normalised document URL → parsed `Document`. Documents that
        could not be read or parsed are omitted (best-effort).
    """
    store = store if store is not None else default_store()
    entry_url = meta_url(entry_url)
    found: dict[str, Document] = dict(docs) if docs else {}
    seen: set[str] = set()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def visit(url: str, hops: int | None) -> None:
        if url in seen:  # dedup; also terminates cycles
            return
        seen.add(url)
        doc = found.get(url)
        if doc is None:
            async with sem:
                try:
                    content = await store.get(url=url)
                except Exception:
                    return  # unreadable; build leaves the referring node external
            try:
                doc = Document.from_content(url, content)
            except Exception:
                return  # not an OME document; leave the node external
            found[url] = doc
        if hops == 0:
            return
        nxt = None if hops is None else hops - 1
        targets = reference_targets(doc, formats=formats)
        await asyncio.gather(*(visit(target, nxt) for target in targets))

    await visit(entry_url, depth)
    return found
