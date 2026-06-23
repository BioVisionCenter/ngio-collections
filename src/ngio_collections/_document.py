"""Metadata documents: one parsed JSON/Zarr file plus its provenance.

A document owns the form-specific (de)serialization envelope. JSON keeps the OME
payload under the top-level `ome` key; Zarr keeps it under `attributes.ome`
inside the group wrapper. `serialize_payload` overrides only the `ome` slice,
preserving every sibling key so an unedited round-trip is byte-identical.
"""

from dataclasses import dataclass
from typing import Protocol

from ngio_collections.store import ReadableStore

# The models are not versioned: there is exactly one OME payload version, stamped
# on every document written by Resolver.create.
VERSION = "0.x"


class MetadataDocument(Protocol):
    content: dict
    store: ReadableStore
    url: str

    def deserialize_payload(self, payload: dict) -> dict:
        """Extract the OME payload dict from the raw document content.

        Args:
            payload: The full document content dict as loaded from the store.

        Returns:
            The OME payload dict ready for node construction.
        """
        ...

    def serialize_payload(self, payload: dict, existing_context: dict) -> dict:
        """Wrap an OME payload dict back into the document envelope.

        Args:
            payload: The OME payload dict to embed.
            existing_context: The current full document content (used to
                preserve sibling keys not owned by the OME payload).

        Returns:
            The full document content dict ready to be written to the store.
        """
        ...


@dataclass
class BaseMetadataDocument:
    content: dict
    store: ReadableStore
    url: str

    def _deserialize_payload(self, payload: dict) -> dict:
        """Extract the value under the `ome` key."""
        return payload["ome"]

    def _serialize_payload(self, payload: dict, existing_context: dict) -> dict:
        # Override only the ome field.
        return {**existing_context, "ome": payload}


@dataclass
class JsonMetadataDocument(BaseMetadataDocument):
    """A parsed JSON metadata document and its provenance."""

    def deserialize_payload(self, payload: dict) -> dict:
        """Extract the OME payload from a top-level `ome` key.

        Args:
            payload: Full JSON document content.

        Returns:
            The OME payload dict.
        """
        return self._deserialize_payload(payload)

    def serialize_payload(self, payload: dict, existing_context: dict) -> dict:
        """Embed the OME payload under the top-level `ome` key.

        Args:
            payload: The OME payload dict to embed.
            existing_context: Current full document content.

        Returns:
            Updated document content with the new OME payload.
        """
        return self._serialize_payload(payload, existing_context)


@dataclass
class ZarrMetadataDocument(BaseMetadataDocument):
    """A parsed Zarr metadata document and its provenance."""

    def _get_attributes(self, payload: dict) -> dict:
        """Return the `attributes` sub-dict, defaulting to empty."""
        return payload.get("attributes", {})

    def _ensure_group(self, payload: dict) -> dict:
        """Ensure `zarr_format` and `node_type` keys are present."""
        if "zarr_format" not in payload:
            payload["zarr_format"] = 3
        if "node_type" not in payload:
            payload["node_type"] = "group"
        return payload

    def deserialize_payload(self, payload: dict) -> dict:
        """Extract the OME payload from `attributes.ome` inside the Zarr group.

        Args:
            payload: Full Zarr group metadata content (`zarr.json`).

        Returns:
            The OME payload dict.
        """
        attributes = self._get_attributes(payload)
        return self._deserialize_payload(attributes)

    def serialize_payload(self, payload: dict, existing_context: dict) -> dict:
        """Embed the OME payload under `attributes.ome`, preserving other keys.

        Args:
            payload: The OME payload dict to embed.
            existing_context: Current full Zarr group metadata content.

        Returns:
            Updated Zarr group metadata with the new OME payload under
            `attributes.ome` and all other top-level keys preserved.
        """
        # ome lives under attributes.ome; override only that key, preserving the
        # other attributes and all sibling top-level keys (zarr_format, etc.).
        attributes = self._get_attributes(existing_context)
        new_attributes = self._serialize_payload(payload, attributes)
        group = {**existing_context, "attributes": new_attributes}
        return self._ensure_group(group)
