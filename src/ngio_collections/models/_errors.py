"""Errors of the value layer that the core raises without pydantic."""

from __future__ import annotations


class NodeStateError(ValueError):
    """A node is in the wrong state for the requested operation.

    Subclasses `ValueError` so callers can keep catching `ValueError`. The
    message points to the API that fits the node's actual state.
    """
