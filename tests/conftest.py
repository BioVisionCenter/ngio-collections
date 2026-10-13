import uuid
from pathlib import Path

import pytest

REFERENCE_DIR = Path(__file__).parent / "data"

_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def uid(name: str) -> str:
    """A deterministic, valid UUID for a readable fixture `name`."""
    return str(uuid.uuid5(_NAMESPACE, name))


@pytest.fixture(params=["inline", "externalised", "mixed"])
def reference(request):
    """(name, directory) for each RFC-8 reference layout under tests/data."""
    name = request.param
    return name, REFERENCE_DIR / name
