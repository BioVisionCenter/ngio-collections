"""Readable, stable UUIDs for the examples (real code uses `ngc.new_id()`)."""

import uuid

NAMESPACE = uuid.UUID("0192f3a0-7c1e-7b00-9c22-000000000000")


def uid(n: int) -> str:
    """A fixed UUID in the style of the revision's examples (stable across runs)."""
    return f"0192f3a0-7c1e-7b00-9c22-{n:012x}"


def uid_for(key: str) -> str:
    """A UUIDv5 derived from `key`: stable across runs, unique per key."""
    return str(uuid.uuid5(NAMESPACE, key))
