from pathlib import Path

import pytest

REFERENCE_DIR = Path(__file__).parent / "data"


@pytest.fixture(params=["inline", "externalised", "mixed"])
def reference(request):
    """(name, directory) for each RFC-8 reference layout."""
    name = request.param
    return name, REFERENCE_DIR / name
