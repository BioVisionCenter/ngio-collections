"""Keyword vocabularies RFC-8 revision 1 names, usable without pydantic."""

from __future__ import annotations

BUILTIN_TRAIT_TYPES: frozenset[str] = frozenset(
    {"scene", "plate", "well", "acquisition", "labels", "bioformats2raw"}
)
"""Keyword trait types the revision names (core or recommended tier)."""
