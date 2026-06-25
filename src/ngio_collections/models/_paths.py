"""Pure path mechanics for document references: resolve, relativize, join.

No IO and no dependency on the node models — just the string/URL math that turns
a stored reference path into an absolute URL and back. The single rule the rest
of the package relies on: :func:`resolve` and :func:`relativize` are inverses
keyed off the *same* base URL (a document's ``url``), so a path written relative
round-trips to the same absolute URL when read.

Scheme handling is deliberately small: bare local filesystem paths, ``file://``,
and ``http(s)://`` work today. :func:`split_scheme` is the one seam to extend for
``s3`` / ``gcs`` / other fsspec protocols — resolution already flows through
``urljoin`` (scheme-aware), and relativization is intentionally limited to
co-located *local* paths (remote / cross-store targets stay absolute locators).
"""

from __future__ import annotations

import posixpath
from typing import Literal
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict

ZARR_METADATA_FILE = "zarr.json"


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


def meta_url(location: str) -> str:
    """Normalise an addressable `location` to its metadata-file URL.

    A `.json` document or an explicit `zarr.json` is returned verbatim; anything
    else is taken to be a Zarr group directory and gets `/zarr.json` appended.

    Args:
        location: A document URL or a Zarr group directory.

    Returns:
        The URL of the metadata file the store actually reads/writes.
    """
    if location.endswith(ZARR_METADATA_FILE) or location.endswith(".json"):
        return location
    return location.rstrip("/") + "/" + ZARR_METADATA_FILE


def resolve(path: str, base_url: str | None) -> str:
    """Resolve a stored reference `path` to an absolute URL.

    Relative paths (`./x`, `../x`, `x`, `sub/x`) are joined against `base_url`
    with `urljoin`, which is scheme-aware and walks `..` for local, `file://`,
    and `http(s)://` bases alike. Absolute paths (`/x`) and absolute URLs
    (`scheme://...`) are returned unchanged. This is the inverse of
    :func:`relativize` for the same `base_url`.

    Args:
        path: The raw path string as stored on a reference.
        base_url: The owning document's `url`; required for relative paths.

    Returns:
        An absolute URL suitable for a store.

    Raises:
        ValueError: If `path` is relative but `base_url` is `None`.
    """
    if base_url is None:
        if _is_local_abs(path) or "://" in path:
            return path
        raise ValueError(f"relative path {path!r} needs a base URL to resolve")
    return urljoin(base_url, path)


def relativize(path: str, base_url: str | None) -> str:
    """Rewrite an absolute local `path` relative to `base_url`'s directory.

    Best-effort and symmetric with :func:`resolve`: the base is
    `dirname(base_url)`, so a co-located target becomes `./name`, a descendant
    `./sub/name`, and an ancestor `../name` / `../../name`. A target that is not
    a bare local absolute path, a remote/`file://` base, or a target sharing only
    the filesystem root with the base is left absolute (it still resolves, just
    as an absolute locator).

    Args:
        path: The absolute path to rewrite.
        base_url: The owning document's `url`; the relativization base.

    Returns:
        A possibly-relativized path string that `resolve(.., base_url)` maps back
        to the original absolute path.
    """
    if base_url is None or not _is_local_abs(path) or not _is_local_abs(base_url):
        return path
    base = posixpath.dirname(base_url)
    try:
        if posixpath.commonpath([base, path]) == "/":
            return path  # nothing shared but the root → keep absolute
    except ValueError:
        return path
    rel = posixpath.relpath(path, base)
    return rel if rel.startswith("../") else "./" + rel


class DocPath(BaseModel):
    """A `{type, path}` reference to an external document (Zarr or JSON).

    The single wire/value type for reference paths. `resolve` / `relativize`
    delegate to the module functions so the inverse-pair invariant lives in one
    place. Frozen and `extra="allow"` so unknown keys round-trip; constructed
    directly or via the `ZarrPath` / `JsonPath` convenience subclasses.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    type: Literal["zarr", "json"]
    path: str

    def resolve(self, base_url: str | None) -> str:
        """Return the absolute URL for this path (see :func:`resolve`)."""
        return resolve(self.path, base_url)

    def relativize(self, base_url: str | None) -> DocPath:
        """Return a copy with `path` relativized (see :func:`relativize`)."""
        return self.model_copy(update={"path": relativize(self.path, base_url)})


class ZarrPath(DocPath):
    """A `zarr`-typed `DocPath` (group directory reference)."""

    type: Literal["zarr"] = "zarr"


class JsonPath(DocPath):
    """A `json`-typed `DocPath` (JSON document reference)."""

    type: Literal["json"] = "json"


# `DocPath` already validates the `type` literal directly, so no discriminated
# union is needed; the alias keeps the historical public name.
PathObj = DocPath
