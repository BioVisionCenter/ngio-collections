"""Metadata documents: one parsed JSON/Zarr file plus its provenance.

A document owns the form-specific (de)serialization envelope. JSON keeps the OME
payload under the top-level ``ome`` key; Zarr keeps it under ``attributes.ome``
inside the group wrapper. ``serialize_payload`` overrides only the ``ome`` slice,
preserving every sibling key so an unedited round-trip is byte-identical.
"""

from dataclasses import dataclass
from typing import Protocol

from ngio_collections.store import ReadableStore


class MetadataDocument(Protocol):
    content: dict
    store: ReadableStore
    url: str

    def deserialize_payload(self, payload: dict) -> dict: ...

    def serialize_payload(self, payload: dict, existing_context: dict) -> dict: ...


@dataclass
class BaseMetadataDocument:
    content: dict
    store: ReadableStore
    url: str

    def _deserialize_payload(self, payload: dict) -> dict:
        return payload["ome"]

    def _serialize_payload(self, payload: dict, existing_context: dict) -> dict:
        # Override only the ome field.
        return {**existing_context, "ome": payload}


@dataclass
class JsonMetadataDocument(BaseMetadataDocument):
    """A parsed JSON metadata document and its provenance."""

    def deserialize_payload(self, payload: dict) -> dict:
        return self._deserialize_payload(payload)

    def serialize_payload(self, payload: dict, existing_context: dict) -> dict:
        return self._serialize_payload(payload, existing_context)


@dataclass
class ZarrMetadataDocument(BaseMetadataDocument):
    """A parsed Zarr metadata document and its provenance."""

    def _get_attributes(self, payload: dict) -> dict:
        return payload.get("attributes", {})

    def _ensure_group(self, payload: dict) -> dict:
        if "zarr_format" not in payload:
            payload["zarr_format"] = 3
        if "node_type" not in payload:
            payload["node_type"] = "group"
        return payload

    def deserialize_payload(self, payload: dict) -> dict:
        attributes = self._get_attributes(payload)
        return self._deserialize_payload(attributes)

    def serialize_payload(self, payload: dict, existing_context: dict) -> dict:
        # ome lives under attributes.ome; override only that key, preserving the
        # other attributes and all sibling top-level keys (zarr_format, etc.).
        attributes = self._get_attributes(existing_context)
        new_attributes = self._serialize_payload(payload, attributes)
        group = {**existing_context, "attributes": new_attributes}
        return self._ensure_group(group)
