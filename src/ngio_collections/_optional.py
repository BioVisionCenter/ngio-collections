"""The optional-dependency seam: pydantic is only needed for typed validation.

The core (open / edit / save / resolve, the raw traits and fields, the
structural validators) runs on the standard library. The typed value models
(traits, scales, coordinate systems, transformations), the `node[Trait]`
lenses, `MultiscaleNode.scales` / `.coordinate_systems` and the schema-shape
validators need pydantic, installed with the `validate` extra. Every such entry
point calls `require_pydantic` first so a missing install fails with one clear,
actionable message instead of a bare `ModuleNotFoundError` deep in a stack.
"""

from __future__ import annotations

INSTALL_HINT = "pip install 'ngio-collections[validate]'"


def require_pydantic(feature: str) -> None:
    """Raise a clear `ImportError` if pydantic is not installed.

    Args:
        feature: What the caller was trying to do (named in the message).

    Raises:
        ImportError: If `pydantic` cannot be imported.
    """
    try:
        import pydantic  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            f"{feature} needs pydantic, which is an optional dependency of "
            f"ngio-collections; install it with `{INSTALL_HINT}`"
        ) from exc
