from pathlib import Path

import pytest

REFERENCE_DIR = Path(__file__).parent / "data"


@pytest.fixture
def by_origin():
    """Return a finder `f(tree, origin_id)` for inlined (namespaced) trees.

    Inlining renames ids to `<origin_id>-<token>`, so address nodes by their
    pre-namespacing id (`_origin_id`) instead of the opaque namespaced id.
    """

    def _find(tree, origin_id):
        return next(
            (n for n in tree.walk() if getattr(n, "_origin_id", None) == origin_id),
            None,
        )

    return _find


@pytest.fixture(params=["inline", "externalised", "mixed"])
def reference(request):
    """(name, directory) for each RFC-8 reference layout."""
    name = request.param
    return name, REFERENCE_DIR / name
