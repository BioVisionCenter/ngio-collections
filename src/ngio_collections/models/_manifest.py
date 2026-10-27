"""Extension manifest models: the per-document declaration of URI-typed extensions.

RFC-8 revision 1 (§4) identifies extension node types and traits by URI and
requires every extension a document uses to be declared in an
`extension_manifest` under the `ome` key, so a reader can list the extensions
and their schemas without a central registry. An entry is
`{id, version, schemas, name?, description?, must_understand?, homepage?}`,
where `schemas` is a non-empty list of `{type: jsonschema | linkml, url}`
(upstream "Extension manifest" section). `ExtensionManifestEntry` is one such
declaration; `ExtensionRegistry` is the process-wide table of entries a writer
draws on to fill a document's manifest automatically. Pure data: no IO, and no
pydantic, since the write path derives manifests through these. Reading is
lenient (unknown keys are ignored, vocabularies are not enforced); the
`manifest_well_formed` validator reports the spec's MUSTs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping

from ngio_collections._types import JSONValue


def is_extension_type(type_name: str) -> bool:
    """Return whether `type_name` is a URI-identified (extension) type.

    Built-in types are plain keywords (`collection`, `well`, …); extension types
    are URIs derived from the extension id (`https://napari.org/ngff/rendering`).
    """
    return "://" in type_name


SCHEMA_TYPES = frozenset({"jsonschema", "linkml"})
"""The schema kinds a manifest entry may list (`SchemaRef.type`)."""


@dataclass(frozen=True, kw_only=True)
class SchemaRef:
    """One schema an extension publishes: its kind (`SCHEMA_TYPES`) and URL."""

    type: str
    url: str

    @classmethod
    def from_dict(cls, data: Mapping[str, JSONValue] | SchemaRef) -> SchemaRef:
        """Build a schema reference from its wire mapping (`{type, url}`).

        Raises:
            ValueError: If `data` is not a mapping with string `type` and `url`.
        """
        if isinstance(data, SchemaRef):
            return data
        if not isinstance(data, Mapping):
            raise ValueError(f"a schema reference must be a mapping, got {data!r}")
        type_, url = data.get("type"), data.get("url")
        if not isinstance(type_, str) or not isinstance(url, str):
            raise ValueError(
                f"schema reference {dict(data)!r} needs string `type` and `url`"
            )
        return cls(type=type_, url=url)

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the wire form `{type, url}`."""
        return {"type": self.type, "url": self.url}


def _optional_str(data: Mapping[str, JSONValue], key: str) -> str | None:
    """Return `data[key]` as a string, `None` when absent.

    Raises:
        ValueError: If the value is present but not a string.
    """
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"manifest `{key}` must be a string, got {value!r}")
    return value


@dataclass(frozen=True, kw_only=True)
class ExtensionManifestEntry:
    """One `extension_manifest` entry: the extension's id, version and schemas.

    `must_understand` marks an extension whose data changes what the document
    *means*: a reader that does not support it must not fall back to a generic
    reading of its custom types (`must_understand_supported` validator).
    """

    id: str
    version: str
    schemas: tuple[SchemaRef, ...] = ()
    name: str | None = None
    description: str | None = None
    must_understand: bool = False
    homepage: str | None = None

    def __post_init__(self) -> None:
        """Type-check the fields and coerce `schemas` to `SchemaRef`s.

        Raises:
            ValueError: If `id` or `version` is not a string, an optional text
                field is not a string, `must_understand` is not a bool, or a
                schema entry is malformed.
        """
        if not isinstance(self.id, str) or not isinstance(self.version, str):
            raise ValueError(
                f"manifest entry needs string `id` and `version`, got "
                f"{self.id!r} / {self.version!r}"
            )
        for key in ("name", "description", "homepage"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"manifest `{key}` must be a string, got {value!r}")
        if not isinstance(self.must_understand, bool):
            raise ValueError(
                f"manifest `must_understand` must be a bool, got "
                f"{self.must_understand!r}"
            )
        # Mappings are accepted for convenience and coerced to `SchemaRef`s.
        object.__setattr__(
            self, "schemas", tuple(SchemaRef.from_dict(s) for s in self.schemas)
        )

    @classmethod
    def from_dict(
        cls, data: Mapping[str, JSONValue] | ExtensionManifestEntry
    ) -> ExtensionManifestEntry:
        """Build an entry from its wire mapping.

        Reads `id`, `version`, `schemas?`, `name?`, `description?`,
        `must_understand?` and `homepage?`. Unknown keys are ignored. An
        `ExtensionManifestEntry` is returned as is.

        Raises:
            ValueError: If `data` is not a mapping or fails the field checks.
        """
        if isinstance(data, ExtensionManifestEntry):
            return data
        if not isinstance(data, Mapping):
            raise ValueError(f"a manifest entry must be a mapping, got {data!r}")
        if "id" not in data or "version" not in data:
            raise ValueError(f"manifest entry {dict(data)!r} needs `id` and `version`")
        id_, version = data["id"], data["version"]
        if not isinstance(id_, str) or not isinstance(version, str):
            raise ValueError(
                f"manifest entry {dict(data)!r} needs string `id` and `version`"
            )
        schemas = data.get("schemas") or ()
        if not isinstance(schemas, (list, tuple)):
            raise ValueError(f"manifest `schemas` must be a list, got {schemas!r}")
        refs: list[SchemaRef] = []
        for item in schemas:
            if not isinstance(item, Mapping):
                raise ValueError(f"a schema reference must be a mapping, got {item!r}")
            refs.append(SchemaRef.from_dict(item))
        must_understand = data.get("must_understand", False)
        if not isinstance(must_understand, bool):
            raise ValueError(
                f"manifest `must_understand` must be a bool, got {must_understand!r}"
            )
        return cls(
            id=id_,
            version=version,
            schemas=tuple(refs),
            name=_optional_str(data, "name"),
            description=_optional_str(data, "description"),
            must_understand=must_understand,
            homepage=_optional_str(data, "homepage"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the wire form.

        `id`, `version` and `schemas` are always written; `name`, `description`
        and `homepage` only when set, `must_understand` only when `True`.
        """
        out: dict[str, JSONValue] = {
            "id": self.id,
            "version": self.version,
            "schemas": [s.to_dict() for s in self.schemas],
        }
        if self.name is not None:
            out["name"] = self.name
        if self.description is not None:
            out["description"] = self.description
        if self.must_understand:
            out["must_understand"] = True
        if self.homepage is not None:
            out["homepage"] = self.homepage
        return out

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
    # Known entries are kept as the dicts the document declared (lossless),
    # paired with their parsed form for `covers` / `id`.
    known_entries = [(ExtensionManifestEntry.from_dict(k), dict(k)) for k in known]
    for uri in uris:
        hit = next((k for k, _ in known_entries if k.covers(uri)), None)
        wire = next((d for k, d in known_entries if k is hit), None)
        if hit is None and registry is not None:
            hit = registry.lookup(uri)
        if hit is None or hit.id in seen_ids:
            continue
        seen_ids.add(hit.id)
        out.append(wire if wire is not None else hit.to_dict())
    return out
