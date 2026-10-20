"""Extension manifest models: the per-document declaration of URI-typed extensions.

RFC-8 revision 1 (§4) identifies extension node types and traits by URI and
requires every extension a document uses to be declared in an
`extension_manifest` under the `ome` key, so a reader can list the extensions
and their schemas without a central registry. `ExtensionManifestEntry` is one
such declaration; `ExtensionRegistry` is the process-wide table of entries a
writer draws on to fill a document's manifest automatically. Pure data: no IO.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Mapping

from pydantic import Field

from ngio_collections.models._config import BaseObj


def is_extension_type(type_name: str) -> bool:
    """Return whether `type_name` is a URI-identified (extension) type.

    Built-in types are plain keywords (`collection`, `well`, …); extension types
    are URIs derived from the extension id (`https://napari.org/ngff/rendering`).
    """
    return "://" in type_name


class SchemaRef(BaseObj):
    """One schema an extension publishes: its kind and where to fetch it."""

    type: str
    url: str


class ExtensionManifestEntry(BaseObj):
    """One `extension_manifest` entry: the extension's id, version and schemas."""

    id: str
    version: str
    schemas: list[SchemaRef] = Field(default_factory=list)
    homepage: str | None = None

    def covers(self, type_name: str) -> bool:
        """Return whether `type_name` is derived from this extension's `id`."""
        return type_name == self.id or type_name.startswith(self.id)


class ExtensionRegistry:
    """The table of known extensions a writer fills `extension_manifest` from."""

    def __init__(self, entries: Iterable[ExtensionManifestEntry] = ()) -> None:
        """Start a registry holding `entries` (keyed by extension id)."""
        self._by_id: dict[str, ExtensionManifestEntry] = {e.id: e for e in entries}

    def register(self, entry: ExtensionManifestEntry) -> ExtensionManifestEntry:
        """Add (or replace) `entry`, keyed by its `id`; return it."""
        self._by_id[entry.id] = entry
        return entry

    def lookup(self, type_name: str) -> ExtensionManifestEntry | None:
        """Return the entry whose `id` is the longest prefix of `type_name`, if any."""
        best: ExtensionManifestEntry | None = None
        for entry in self._by_id.values():
            if entry.covers(type_name) and (
                best is None or len(entry.id) > len(best.id)
            ):
                best = entry
        return best

    def __iter__(self) -> Iterator[ExtensionManifestEntry]:
        """Iterate over the registered entries."""
        return iter(self._by_id.values())

    def __len__(self) -> int:
        """Return the number of registered extensions."""
        return len(self._by_id)


def manifest_entries(
    used_types: Iterable[str],
    *,
    registry: ExtensionRegistry | None = None,
    known: Iterable[Mapping] = (),
) -> list[dict]:
    """Return the manifest entries a document needs for the URI types it uses.

    Entries already present in `known` (for example the manifest the document
    was opened with) are kept when still used; URIs not covered by them are
    looked up in `registry`. A URI nobody knows is simply left undeclared: that
    is a validation finding (`extension_types_declared`), not a write failure.

    Args:
        used_types: Every URI-typed node / trait type the document contains.
        registry: The table of known extensions to draw new entries from.
        known: Existing manifest entries (plain dicts) to keep when still used.

    Returns:
        The manifest as a list of plain dicts, in first-use order.
    """
    uris = [t for t in dict.fromkeys(used_types) if is_extension_type(t)]
    out: list[dict] = []
    seen_ids: set[str] = set()
    known_entries = [ExtensionManifestEntry.model_validate(k) for k in known]
    for uri in uris:
        hit = next((k for k in known_entries if k.covers(uri)), None)
        if hit is None and registry is not None:
            hit = registry.lookup(uri)
        if hit is None or hit.id in seen_ids:
            continue
        seen_ids.add(hit.id)
        out.append(hit.model_dump(mode="json", exclude_none=True))
    return out
