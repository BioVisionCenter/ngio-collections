"""Readable, stable ids for the examples.

Ids are free-form strings (`ngc.ID_PATTERN`); the examples keep the UUID look of
the revision's documents so the generated files are easy to compare with it.
Real code picks any id it likes, or lets `ngc.new_id()` mint one.
"""

import uuid

NAMESPACE = uuid.UUID("0192f3a0-7c1e-7b00-9c22-000000000000")


def uid(n: int) -> str:
    """A fixed id in the UUID style of the revision's examples (stable across runs)."""
    return f"0192f3a0-7c1e-7b00-9c22-{n:012x}"


def uid_for(key: str) -> str:
    """A UUIDv5 derived from `key`: stable across runs, unique per key."""
    return str(uuid.uuid5(NAMESPACE, key))
