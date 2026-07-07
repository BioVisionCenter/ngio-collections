from typing import TypeAlias

JSONValue: TypeAlias = (
    dict[str, "JSONType"] | list["JSONType"] | str | int | float | bool | None  # ty:ignore[unresolved-reference]
)
"""Type of a JSON document."""
