"""Path objects (`{type, format, href}`) and the pure URL math behind them.

No IO and no dependency on the node models: just the string/URL math that turns
a stored path object into an absolute URL and back. The rule the rest of the
package relies on: :func:`resolve` and :func:`relativize` are inverses keyed off
the *same* base URL (a document's ``url``), so a path written relative round-trips
to the same absolute URL when read.

**Formats.** RFC-8 revision 2 makes ``format`` explicit — ``relative``,
``absolute`` or ``http`` — and forbids readers from inferring it from the string.
The revision also makes only ``relative`` a *core* format and defers the other two
to a sub-RFC. **This package deliberately deviates from that**: all three formats
resolve, so a collection or multiscale document can point at existing local or
remote data (a published image, remote arrays as levels) without bundling it.
``CORE_FORMATS`` exists so callers who want strict conformance can opt in
(``resolve(..., formats=CORE_FORMATS)``, or the ``paths_are_core`` validator).

**Types.** ``type`` is an extension point (upstream "Path" interface): besides
the built-in ``zarr`` (a group whose metadata is ``<dir>/zarr.json``) and
``json`` (the document itself), a URI type declared by an extension is accepted.
Such a path *locates data*: it is declared in the manifest, but is never
fetched or opened as a node document (``is_document`` is false and ``meta_url``
refuses it). Its shape is the extension's to define: ``format`` may be absent
and any further keys (``host``, ``port``, ... in the revision's ``OMEROPath``
example) are kept in ``extra`` and written back. When it does declare a
``format``, it resolves and relativizes like any other path. The built-in types
keep the closed ``{type, format, href}`` shape.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping, cast, get_args
from urllib.parse import urljoin

from ngio_collections._types import JSONValue
from ngio_collections.models._manifest import is_extension_type

ZARR_METADATA_FILE = "zarr.json"

PathType = Literal["zarr", "json"]
"""The built-in path types; `DocPath.type` also admits extension URIs."""
PathFormat = Literal["relative", "absolute", "http"]

BUILTIN_PATH_TYPES: frozenset[str] = frozenset(get_args(PathType))
"""The path types that locate a node document (`zarr`, `json`)."""
_PATH_FORMATS: frozenset[str] = frozenset(get_args(PathFormat))
_PATH_KEYS: frozenset[str] = frozenset({"type", "format", "href"})
"""The keys every path object may carry; a URI-typed path may add its own."""

ALL_FORMATS: frozenset[str] = frozenset({"relative", "absolute", "http"})
"""Every format this package resolves (the documented deviation from the spec)."""

CORE_FORMATS: frozenset[str] = frozenset({"relative"})
"""The only format RFC-8 revision 2 makes core; opt in for strict conformance."""


class UnsupportedPathFormatError(ValueError):
    """A path declares a `format` the caller chose not to resolve."""


def split_scheme(url: str) -> tuple[str, str]:
    """Split `url` into `(scheme, rest)`; scheme is `""` for a local path.

    Args:
        url: A bare filesystem path or a `scheme://...` URL.

    Returns:
        `(scheme, rest)` where `rest` is everything after `://` (or the whole
        string for a schemeless local path).
    """
    scheme, sep, rest = url.partition("://")
    return (scheme, rest) if sep else ("", url)


def _is_local_abs(url: str) -> bool:
    """True iff `url` is a bare absolute local filesystem path (`/...`)."""
    return url.startswith("/")


def is_http(url: str) -> bool:
    """True iff `url` is an `http://` or `https://` URL."""
    return split_scheme(url)[0] in ("http", "https")


def meta_url(location: str) -> str:
    """Normalise an addressable `location` to its metadata-file URL.

    A `.json` document or an explicit `zarr.json` is returned verbatim; anything
    else is taken to be a Zarr group directory and gets `/zarr.json` appended.
    This is for *entry* URLs typed by a caller; a path object knows its `type`
    and uses :meth:`DocPath.meta_url` instead.

    Args:
        location: A document URL or a Zarr group directory.

    Returns:
        The URL of the metadata file the store actually reads/writes.
    """
    if location.endswith(ZARR_METADATA_FILE) or location.endswith(".json"):
        return location
    return location.rstrip("/") + "/" + ZARR_METADATA_FILE


def format_for_url(url: str) -> PathFormat:
    """Return the `format` a path object pointing at the absolute `url` declares.

    Args:
        url: An absolute locator (local path, `file://`, or `http(s)://`).

    Returns:
        `"http"` for `http(s)://` URLs, `"absolute"` otherwise.
    """
    return "http" if is_http(url) else "absolute"


def resolve(
    href: str,
    format: PathFormat,
    base_url: str | None,
    *,
    formats: frozenset[str] = ALL_FORMATS,
) -> str:
    """Resolve a stored `href` of the declared `format` to an absolute URL.

    Nothing is inferred from the string. A `relative` href is joined against
    `base_url` with `urljoin` (scheme-aware, walks `..`); an `absolute` or `http`
    href is returned verbatim.

    Args:
        href: The raw `href` string as stored on the path object.
        format: The declared path format.
        base_url: The owning document's `url`; required for relative paths.
        formats: The formats the caller agrees to resolve; others raise.

    Returns:
        An absolute URL suitable for a store.

    Raises:
        UnsupportedPathFormatError: If `format` is not in `formats`.
        ValueError: If `format` is `relative` but `base_url` is `None`.
    """
    if format not in formats:
        raise UnsupportedPathFormatError(
            f"path format {format!r} is not resolved here (allowed: {sorted(formats)})"
        )
    if format != "relative":
        return href
    if base_url is None:
        raise ValueError(f"relative path {href!r} needs a base URL to resolve")
    return urljoin(base_url, href)


def relativize(href: str, base_url: str | None) -> tuple[PathFormat, str]:
    """Rewrite an absolute local `href` relative to `base_url`'s directory.

    Best-effort and symmetric with :func:`resolve`: the base is
    `dirname(base_url)`, so a co-located target becomes `./name`, a descendant
    `./sub/name`, and an ancestor `../name`. A target that is not a bare local
    absolute path, a remote / `file://` base, or a target sharing only the
    filesystem root with the base is left as an `absolute` locator.

    Args:
        href: The absolute local path to rewrite.
        base_url: The owning document's `url`; the relativization base.

    Returns:
        `(format, href)`: `("relative", "./x")` when rewritten, else
        `("absolute", href)` unchanged.
    """
    if base_url is None or not _is_local_abs(href) or not _is_local_abs(base_url):
        return "absolute", href
    base = posixpath.dirname(base_url)
    try:
        if posixpath.commonpath([base, href]) == "/":
            return "absolute", href  # nothing shared but the root → keep absolute
    except ValueError:
        return "absolute", href
    rel = posixpath.relpath(href, base)
    return "relative", (rel if rel.startswith("../") else "./" + rel)


@dataclass(frozen=True, kw_only=True)
class DocPath:
    """A `{type, format, href}` path object locating a document or array.

    The single wire/value type for paths. `resolve` / `relativize` delegate to
    the module functions so the inverse-pair invariant lives in one place. A
    frozen stdlib dataclass (no pydantic): construct it directly, via the
    `ZarrPath` / `JsonPath` convenience subclasses, or with `from_dict`; it is
    also accepted as a field of the pydantic value models. `type` is a built-in
    (`zarr`, `json`) or an extension URI; only the built-ins locate a document
    (`is_document`). A built-in path has exactly the three keys. A URI-typed
    path may omit `format` and carries any other keys its extension defines in
    `extra`.
    """

    type: str
    format: PathFormat | None = None
    href: str
    extra: Mapping[str, JSONValue] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        """Check the vocabularies and reject inconsistent `format` / `href` pairings.

        Raises:
            ValueError: If `type` is neither a built-in nor a URI, `format` is
                not a known literal (or is missing on a built-in path), `href`
                is not a string, an `http` path has no `http(s)://` href, a
                `relative` path carries a URL href, or a built-in path carries
                `extra` keys.
        """
        if not isinstance(self.type, str) or (
            self.type not in BUILTIN_PATH_TYPES and not is_extension_type(self.type)
        ):
            raise ValueError(
                f"path type must be one of {sorted(BUILTIN_PATH_TYPES)} or an "
                f"extension URI, got {self.type!r}"
            )
        custom = self.type not in BUILTIN_PATH_TYPES
        if self.format not in _PATH_FORMATS and not (custom and self.format is None):
            raise ValueError(
                f"path format must be one of {sorted(_PATH_FORMATS)}, got {self.format!r}"
            )
        if self.extra and not custom:
            raise ValueError(
                f"a {self.type!r} path has only type, format and href; got extra "
                f"keys {sorted(self.extra)}"
            )
        if _PATH_KEYS & set(self.extra):
            raise ValueError(f"path `extra` cannot hold {sorted(_PATH_KEYS)}")
        if not isinstance(self.href, str):
            raise ValueError(f"path href must be a string, got {self.href!r}")
        if self.format == "http" and not is_http(self.href):
            raise ValueError(
                f"format 'http' needs an http(s):// href, got {self.href!r}"
            )
        if self.format == "relative" and "://" in self.href:
            raise ValueError(f"format 'relative' cannot carry a URL href {self.href!r}")

    @classmethod
    def from_dict(cls, data: Mapping[str, JSONValue] | DocPath) -> DocPath:
        """Build a path object from its wire mapping (`{type, format, href}`).

        A `DocPath` instance is returned as is. On a URI-typed path `format` is
        optional and the remaining keys are kept in `extra`; on a built-in path
        unknown keys are ignored.

        Raises:
            ValueError: If `data` is not a mapping, misses a required key, or
                fails the checks in `__post_init__`.
        """
        if isinstance(data, DocPath):
            return data
        if not isinstance(data, Mapping):
            raise ValueError(f"a path object must be a mapping, got {data!r}")
        type_ = data.get("type")
        if not isinstance(type_, str):
            raise ValueError(f"path object {dict(data)!r} needs a string type")
        custom = type_ not in BUILTIN_PATH_TYPES
        required = ("href",) if custom else ("format", "href")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"path object {dict(data)!r} is missing {missing}")
        format_, href = data.get("format"), data["href"]
        if format_ is not None and not isinstance(format_, str):
            raise ValueError(f"path format must be a string, got {format_!r}")
        if not isinstance(href, str):
            raise ValueError(f"path href must be a string, got {href!r}")
        extra = {k: v for k, v in data.items() if k not in _PATH_KEYS} if custom else {}
        # `__post_init__` checks the vocabularies; the cast only satisfies the checker.
        return cls(
            type=type_,
            format=cast("PathFormat | None", format_),
            href=href,
            extra=extra,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the wire form: `type`, `format` (when set), `href`, then `extra`."""
        out: dict[str, JSONValue] = {"type": self.type}
        if self.format is not None:
            out["format"] = self.format
        out["href"] = self.href
        out.update(self.extra)
        return out

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        """Let pydantic models hold a path: parse with `from_dict`, dump with `to_dict`.

        Only pydantic calls this, so the import stays out of the core.
        """
        from pydantic_core import core_schema

        return core_schema.no_info_plain_validator_function(
            cls.from_dict,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda path: path.to_dict()
            ),
        )

    @property
    def is_document(self) -> bool:
        """Whether this path locates a node document (`zarr` / `json`) rather than data."""
        return self.type in BUILTIN_PATH_TYPES

    def resolve(
        self, base_url: str | None, *, formats: frozenset[str] = ALL_FORMATS
    ) -> str:
        """Return the absolute URL this path locates (see :func:`resolve`).

        A URI-typed path without a `format` is the extension's to interpret:
        its `href` is returned as written.
        """
        if self.format is None:
            return self.href
        return resolve(self.href, self.format, base_url, formats=formats)

    def meta_url(
        self, base_url: str | None, *, formats: frozenset[str] = ALL_FORMATS
    ) -> str:
        """Return the metadata-file URL of the document this path locates.

        Keyed on the declared `type`, never on the string: a `zarr` path locates a
        group directory whose metadata is `<dir>/zarr.json`; a `json` path locates
        the document itself.

        Raises:
            ValueError: If the path's `type` is an extension URI: such a path
                locates data, not a document (use `resolve`).
        """
        if not self.is_document:
            raise ValueError(
                f"path type {self.type!r} locates data, not a node document"
            )
        url = self.resolve(base_url, formats=formats)
        if self.type == "json" or url.endswith("/" + ZARR_METADATA_FILE):
            return url
        return url.rstrip("/") + "/" + ZARR_METADATA_FILE

    def relativize(self, base_url: str | None) -> DocPath:
        """Return a copy relativized against `base_url` when it is a local absolute path.

        `relative` and `http` paths are returned unchanged.
        """
        if self.format != "absolute":
            return self
        format, href = relativize(self.href, base_url)
        if format == self.format and href == self.href:
            return self
        return replace(self, format=format, href=href)

    def rebase(self, origin_url: str | None, base_url: str | None) -> DocPath:
        """Return a copy that still locates the same target from another document.

        A `relative` path is anchored on the document it was read from
        (`origin_url`). When it is about to be written into a different
        document (`base_url`), it is first made absolute against its origin, so
        that `relativize` can re-express it for the new document. Paths of
        other formats, paths with no known origin, and paths staying in their
        document are returned unchanged.
        """
        if self.format != "relative" or origin_url is None or origin_url == base_url:
            return self
        href = resolve(self.href, "relative", origin_url)
        return replace(self, format=format_for_url(href), href=href)

    @classmethod
    def for_url(cls, url: str) -> DocPath:
        """Return the path object that points at the document at `url`.

        A JSON document is located by its file URL; a Zarr group by its directory
        (the metadata URL without the trailing `zarr.json`). The `format` is the
        absolute one matching the URL's scheme (`http` or `absolute`); the
        serializer relativizes local paths on write.
        """
        url = meta_url(url)
        suffix = "/" + ZARR_METADATA_FILE
        if url.endswith(suffix):
            return cls(
                type="zarr", format=format_for_url(url), href=url[: -len(suffix)]
            )
        if url.endswith(".json"):
            return cls(type="json", format=format_for_url(url), href=url)
        return cls(type="zarr", format=format_for_url(url), href=url)


@dataclass(frozen=True, kw_only=True)
class ZarrPath(DocPath):
    """A `zarr`-typed `DocPath` (group or array directory), `relative` by default."""

    type: Literal["zarr"] = "zarr"
    format: PathFormat = "relative"


@dataclass(frozen=True, kw_only=True)
class JsonPath(DocPath):
    """A `json`-typed `DocPath` (standalone JSON document), `relative` by default."""

    type: Literal["json"] = "json"
    format: PathFormat = "relative"


# `DocPath` already checks the `type` literal directly, so no discriminated
# union is needed; the alias keeps the historical public name.
PathObj = DocPath
