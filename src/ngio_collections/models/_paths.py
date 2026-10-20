"""Path objects (`{type, format, href}`) and the pure URL math behind them.

No IO and no dependency on the node models: just the string/URL math that turns
a stored path object into an absolute URL and back. The rule the rest of the
package relies on: :func:`resolve` and :func:`relativize` are inverses keyed off
the *same* base URL (a document's ``url``), so a path written relative round-trips
to the same absolute URL when read.

**Formats.** RFC-8 revision 1 (§7.3) makes ``format`` explicit — ``relative``,
``absolute`` or ``http`` — and forbids readers from inferring it from the string.
The revision also makes only ``relative`` a *core* format and defers the other two
to a sub-RFC. **This package deliberately deviates from that**: all three formats
resolve, so a collection or multiscale document can point at existing local or
remote data (a published image, remote arrays as scales) without bundling it.
``CORE_FORMATS`` exists so callers who want strict conformance can opt in
(``resolve(..., formats=CORE_FORMATS)``, or the ``paths_are_core`` validator).
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, replace
from typing import Literal, Mapping, cast, get_args
from urllib.parse import urljoin

from ngio_collections._types import JSONValue

ZARR_METADATA_FILE = "zarr.json"

PathType = Literal["zarr", "json"]
PathFormat = Literal["relative", "absolute", "http"]

_PATH_TYPES: frozenset[str] = frozenset(get_args(PathType))
_PATH_FORMATS: frozenset[str] = frozenset(get_args(PathFormat))

ALL_FORMATS: frozenset[str] = frozenset({"relative", "absolute", "http"})
"""Every format this package resolves (the documented deviation from the spec)."""

CORE_FORMATS: frozenset[str] = frozenset({"relative"})
"""The only format RFC-8 revision 1 makes core; opt in for strict conformance."""


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
    also accepted as a field of the pydantic value models. Unknown keys are not
    kept: the shape is closed.
    """

    type: PathType
    format: PathFormat
    href: str

    def __post_init__(self) -> None:
        """Check the literals and reject inconsistent `format` / `href` pairings.

        Raises:
            ValueError: If `type` or `format` is not a known literal, `href` is
                not a string, an `http` path has no `http(s)://` href, or a
                `relative` path carries a URL href.
        """
        if self.type not in _PATH_TYPES:
            raise ValueError(
                f"path type must be one of {sorted(_PATH_TYPES)}, got {self.type!r}"
            )
        if self.format not in _PATH_FORMATS:
            raise ValueError(
                f"path format must be one of {sorted(_PATH_FORMATS)}, got {self.format!r}"
            )
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

        A `DocPath` instance is returned as is.

        Raises:
            ValueError: If `data` is not a mapping, misses one of the three keys,
                or fails the checks in `__post_init__`.
        """
        if isinstance(data, DocPath):
            return data
        if not isinstance(data, Mapping):
            raise ValueError(f"a path object must be a mapping, got {data!r}")
        missing = [k for k in ("type", "format", "href") if k not in data]
        if missing:
            raise ValueError(f"path object {dict(data)!r} is missing {missing}")
        type_, format_, href = data["type"], data["format"], data["href"]
        if not (isinstance(type_, str) and isinstance(format_, str)):
            raise ValueError(f"path object {dict(data)!r} needs string type and format")
        if not isinstance(href, str):
            raise ValueError(f"path href must be a string, got {href!r}")
        # `__post_init__` checks the literals; the casts only satisfy the checker.
        return cls(
            type=cast(PathType, type_), format=cast(PathFormat, format_), href=href
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the wire form `{type, format, href}`."""
        return {"type": self.type, "format": self.format, "href": self.href}

    def resolve(
        self, base_url: str | None, *, formats: frozenset[str] = ALL_FORMATS
    ) -> str:
        """Return the absolute URL this path locates (see :func:`resolve`)."""
        return resolve(self.href, self.format, base_url, formats=formats)

    def meta_url(
        self, base_url: str | None, *, formats: frozenset[str] = ALL_FORMATS
    ) -> str:
        """Return the metadata-file URL of the document this path locates.

        Keyed on the declared `type`, never on the string: a `zarr` path locates a
        group directory whose metadata is `<dir>/zarr.json`; a `json` path locates
        the document itself.
        """
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
