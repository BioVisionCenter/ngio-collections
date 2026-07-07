from typing import TypeAlias

JSONValue: TypeAlias = (
    dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None
)
"""Type of a JSON document."""
