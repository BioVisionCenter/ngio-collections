"""treeops: pure, no-IO algorithms over built node trees.

One-directional: imports from `models`, never the reverse (at runtime). Holds
the tree-construction and transformation algorithms that operate on already-built
nodes — building inlined mirrors, namespacing merged-document ids, and rewriting
attribute references — kept out of the cohesive `models._nodes` core. These are
the pure operations the `Resolver` leans on, lifted out of the IO layer.
"""

from ngio_collections.treeops._inline import build_inlined_payload
from ngio_collections.treeops._jsonrefs import (
    relativize_attr_refs,
    rewrite_attr_refs,
)
from ngio_collections.treeops._namespace import (
    assert_unique_ids,
    namespace_ids,
)

__all__ = [
    "assert_unique_ids",
    "build_inlined_payload",
    "namespace_ids",
    "relativize_attr_refs",
    "rewrite_attr_refs",
]
