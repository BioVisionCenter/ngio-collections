"""A parsed metadata document: one JSON/Zarr file reduced to its root node dict.

This is the v5 view of a document the pure `build` consumes. It deliberately
holds only what resolution needs — the normalised metadata-file `url`, the form
`kind`, and the version-stripped `root` node dict — so `build` stays free of IO
and of the wire-envelope details (JSON keeps the OME payload at top-level `ome`;
Zarr keeps it under `attributes.ome`). `from_content` is the one place that knows
those envelopes; `fetch_all` calls it after a successful read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ngio_collections.models._paths import ZARR_METADATA_FILE, meta_url

# The models are not versioned: there is exactly one OME payload version, stamped
# on every document written by `write_document`.
VERSION = "0.x"

Kind = Literal["zarr", "json"]


def _kind_for(url: str) -> Kind:
    """Return the document form implied by `url`'s suffix."""
    if url.endswith(".json") and not url.endswith(ZARR_METADATA_FILE):
        return "json"
    return "zarr"


@dataclass(frozen=True, slots=True)
class Document:
    """One parsed document: its metadata-file `url`, `kind`, and `root` node dict.

    `has_payload` is `False` for a document that was read successfully but carries
    no `ome` key at all — a plain Zarr array, say. That is a *different* fact from
    the document being absent (unreadable), and resolution needs both: a stub whose
    target is data is already complete, while a stub whose target is missing is an
    error. `root` is `{}` in that case.
    """

    url: str
    kind: Kind
    root: dict
    has_payload: bool = True

    @property
    def ref_url(self) -> str:
        """The absolute locator a reference *to* this document stores.

        JSON stores the document URL verbatim; Zarr stores the group directory
        (the URL without the trailing `zarr.json`).
        """
        if self.kind == "zarr":
            suffix = "/" + ZARR_METADATA_FILE
            return self.url[: -len(suffix)] if self.url.endswith(suffix) else self.url
        return self.url

    @classmethod
    def kind_for(cls, url: str) -> Kind:
        """Return the document form implied by `url`'s suffix."""
        return _kind_for(meta_url(url))

    @classmethod
    def from_content(cls, url: str, content: dict) -> Document:
        """Parse raw document `content` into a `Document`, stripping the envelope.

        Args:
            url: The document's location (normalised to its metadata-file URL).
            content: The full document dict as loaded from the store.

        Returns:
            A `Document` whose `root` is the OME payload's root node dict with the
            envelope `version` removed. A document carrying no `ome` key at all
            (e.g. a plain data array) is not an error: it comes back with
            `has_payload=False` and an empty `root`.
        """
        url = meta_url(url)
        kind = _kind_for(url)
        container = content if kind == "json" else content.get("attributes") or {}
        ome = container.get("ome")
        if ome is None:
            return cls(url=url, kind=kind, root={}, has_payload=False)
        root = {k: v for k, v in ome.items() if k != "version"}
        return cls(url=url, kind=kind, root=root)


def wrap_payload(kind: Kind, payload: dict, existing: dict | None = None) -> dict:
    """Wrap an OME `payload` back into a `kind` document envelope.

    JSON puts the payload at the top-level `ome` key; Zarr puts it under
    `attributes.ome` and ensures the group markers. `existing` (the current
    on-disk content, if any) is preserved so sibling keys round-trip and an
    unedited write is byte-identical.

    Args:
        kind: The document form to produce.
        payload: The OME payload dict (`version` + root node).
        existing: Current full document content to preserve siblings from.

    Returns:
        The full document content dict ready to serialize and store.
    """
    existing = existing or {}
    if kind == "json":
        return {**existing, "ome": payload}
    attributes = {**existing.get("attributes", {}), "ome": payload}
    group = {**existing, "attributes": attributes}
    group.setdefault("zarr_format", 3)
    group.setdefault("node_type", "group")
    return group
