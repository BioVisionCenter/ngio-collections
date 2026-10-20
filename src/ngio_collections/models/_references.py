"""The typed `ReferenceObj` pointer (`{type, ref, path?}`).

RFC-8 revision 1 (§7.2) separates *declarations* (`{type, id, ...}`) from
*references* (`{type, ref, path?}`): a reference names the kind of its target,
carries the target's UUID under `ref` (never `id`, so the two can always be told
apart) and optionally a `path` to the document that declares the target. A
reference carries nothing else — no traits, no children — which is why this
model forbids extra keys. Resolving it is the resolver's job.
"""

from __future__ import annotations

from pydantic import ConfigDict

from ngio_collections.models._config import BaseObj
from ngio_collections.models._ids import UuidStr
from ngio_collections.models._paths import DocPath


class ReferenceObj(BaseObj):
    """A portable, typed pointer to a declaration (node, scale, coordinate system).

    `type` is the kind of the target (`"multiscale"`, `"scale"`,
    `"coordinate_system"`, …); `ref` is its UUID. A `None` path means the target
    is declared in the *same* document; otherwise `path` locates the document.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    ref: UuidStr
    path: DocPath | None = None
