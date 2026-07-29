"""The async shell: gather every document a build will need, concurrently.

This is the only async code in resolution. `fetch_all` walks the reference graph
breadth-first from an entry document, reading each document through the store and
following its cross-document references up to `depth`, bounded by `concurrency`.
The pure `reference_targets` helper supplies the frontier (which URLs a document
points at); the build that follows is pure and reads everything from the returned
`docs` map. Discovery and reading are interleaved because a document's references
are only known once it is parsed — but no resolution *logic* lives here.

Reads are best-effort: a document that cannot be fetched or is not an OME document
is simply absent from `docs`, and `build` then leaves the referring stub in place
(or raises, per its `on_error`).
"""

from __future__ import annotations

import asyncio

from ngio_collections.io.store import LocalStore, ReadableStore
from ngio_collections.models._paths import DocPath, meta_url
from ngio_collections.resolve._document import Document


def reference_targets(doc: Document):  # -> Iterator[str]
    """Yield the normalised URL of every cross-document stub in `doc`.

    Mirrors the resolution in `build`: each node dict carrying a `path` is
    resolved against `doc.url` and normalised to its metadata-file URL, so the
    yielded keys match the ones `fetch_all` caches under. Malformed paths are
    skipped (the build re-resolves and reports them).
    """
    for node_dict in _walk(doc.root):
        path = node_dict.get("path")
        if path is None:
            continue
        try:
            yield meta_url(DocPath.model_validate(path).resolve(doc.url))
        except Exception:
            continue


def _walk(node_dict: dict):  # -> Iterator[dict]
    """Yield `node_dict` and every descendant node dict, depth-first."""
    yield node_dict
    for child in node_dict.get("nodes") or ():
        yield from _walk(child)


async def fetch_all(
    entry_url: str,
    store: ReadableStore | None = None,
    *,
    depth: int | None = None,
    concurrency: int = 16,
) -> dict[str, Document]:
    """Fetch the entry document and every document reachable within `depth`.

    Args:
        entry_url: The entry document's location (normalised internally).
        store: The store to read through; defaults to `LocalStore`.
        depth: Max boundary hops to follow (`None` unlimited, `0` = entry only).
        concurrency: Max documents read at once.

    Returns:
        A mapping of normalised document URL → parsed `Document`. Documents that
        could not be read or parsed are omitted (best-effort).
    """
    store = store if store is not None else LocalStore()
    entry_url = meta_url(entry_url)
    docs: dict[str, Document] = {}
    seen: set[str] = set()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def visit(url: str, hops: int | None) -> None:
        if url in seen:  # dedup; also terminates cycles
            return
        seen.add(url)
        async with sem:
            try:
                content = await store.get(url=url)
            except Exception:
                return  # unreadable; build leaves the referring stub
        try:
            doc = Document.from_content(url, content)
        except Exception:
            return  # not an OME document; leave the stub
        docs[url] = doc
        if hops == 0:
            return
        nxt = None if hops is None else hops - 1
        await asyncio.gather(*(visit(target, nxt) for target in reference_targets(doc)))

    await visit(entry_url, depth)
    return docs
