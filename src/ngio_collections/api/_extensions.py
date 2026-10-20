"""The process-wide extension registry behind `extension_manifest` derivation.

RFC-8 revision 1 (§4) requires every extension a document uses to be declared
in that document's `extension_manifest`. Rather than asking callers to assemble
the manifest by hand on every write, the API derives it: each URI-typed node or
trait type a document uses is matched against the entries registered here (plus
whatever the document already declared), and the matching entries are written.
"""

from __future__ import annotations

from typing import Mapping

from ngio_collections.models._manifest import ExtensionManifestEntry, ExtensionRegistry

EXTENSIONS = ExtensionRegistry()
"""The default registry `create` / `save` derive manifests from."""


def register_extension(
    entry: ExtensionManifestEntry | Mapping,
    *,
    registry: ExtensionRegistry = EXTENSIONS,
) -> ExtensionManifestEntry:
    """Register an extension so documents using its URI types declare it.

    Args:
        entry: The manifest entry (`id`, `version`, `schemas`, `homepage?`), as
            a model or a plain mapping.
        registry: The registry to add it to (the default one unless testing).

    Returns:
        The registered `ExtensionManifestEntry`.
    """
    model = (
        entry
        if isinstance(entry, ExtensionManifestEntry)
        else ExtensionManifestEntry.from_dict(entry)
    )
    return registry.register(model)
