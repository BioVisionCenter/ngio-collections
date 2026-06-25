"""The portable `ReferenceObj` pointer and node-id primitives.

Pure value types: a `ReferenceObj` is the `{id, path?}` locator `node.ref()`
returns. The functions that *mint* references from a document (`reference_to` /
`stub_to`) need the node registry, so they live with the node core in `_nodes`.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ngio_collections.models._config import BaseObj
from ngio_collections.models._paths import PathObj

ID_PATTERN = r"^[a-zA-Z0-9\-_.]+$"

IdStr = Annotated[str, Field(pattern=ID_PATTERN)]


class ReferenceObj(BaseObj):
    """A portable pointer to a node that exists on disk.

    Not a node itself: it carries no attributes and no type — locating the node
    is its whole job. Resolved by loading the document at `path` and finding the
    node whose `id` matches inside it (the resolved node carries the type). A
    `None` path means a reference within the *same* document (resolve `id`
    locally).
    """

    id: IdStr
    path: PathObj | None = None
