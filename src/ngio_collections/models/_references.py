"""The portable `ReferenceObj` pointer and node-id primitives.

Pure value types. In the Fall 2026 proposal an `id` *declares* a node (a UUID,
declared exactly once in the document that holds the body) and a `ref` *points*
at one. `ReferenceObj` is the `{type, ref, path?}` locator `node.ref()` returns
and that attribute values (`input` / `output`, `source`, …) carry. Resolving the
node it points at is the resolver's job: a `ref` with a `path` is looked up
inside the document at `path`; a bare `ref` resolves in the current document.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import Field

from ngio_collections.models._config import BaseObj
from ngio_collections.models._paths import PathObj

UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
"""Canonical lowercase hyphenated UUID; any version is accepted."""

UuidStr = Annotated[str, Field(pattern=UUID_PATTERN)]

# Deprecated: the pre-proposal free-form id. Still used by the typed attribute
# models (`CoordinateSystem.id`, HCS `ColumnObj.id`, …) until they are ported
# to traits; do not use it for node ids.
ID_PATTERN = r"^[a-zA-Z0-9\-_.]+$"
IdStr = Annotated[str, Field(pattern=ID_PATTERN)]


def new_id() -> str:
    """Mint a fresh node id: `uuid7` when the interpreter has it, else `uuid4`."""
    make = getattr(uuid, "uuid7", uuid.uuid4)
    return str(make())


class ReferenceObj(BaseObj):
    """A portable pointer to a declared node: `{type, ref, path?}`.

    Not a node itself: it carries no name and no body — locating the node is its
    whole job. `type` repeats the target's type (a mismatch is an error on
    resolution). A `None` path means a reference within the *same* document.
    """

    type: str
    ref: UuidStr
    path: PathObj | None = None
