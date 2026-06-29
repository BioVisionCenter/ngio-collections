"""The validator engine: cheap, raising callables over a node subtree.

A validator is just a `Callable[[Node], None]` — it inspects the node it is
handed and `raise`s a `ValidationError` if the node fails its check, returning
normally otherwise. Applicability is an early `return`. `validate` runs every
validator over a node and its descendants; it attaches *which node* and *which
validator* to each error it catches, so a validator only has to spell the
message. Validators *compose*: a node carrying both `well` and `scene` simply
runs both checks, with no combinatorial classes, and each check touches only the
bounded neighbourhood it reads via the `Node` handle (parent, ancestors, …), so
checking one node stays cheap even at 1M nodes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from ngio_collections.graph import NodeId

if TYPE_CHECKING:
    from ngio_collections.api._node import Node

ValidatorType = Callable[["Node"], None]


class ValidationError(Exception):
    """Raised by a validator when a node fails its check.

    `node_id` and `validator` are filled in by `validate` when it catches this,
    so a validator only has to supply the human-readable message.
    """

    def __init__(self, message: str) -> None:
        """Record the failure `message`; the engine fills in node and validator."""
        super().__init__(message)
        self.node_id: NodeId | None = None
        self.validator: str | None = None


def validate(
    node: Node,
    validators: Sequence[ValidatorType],
    *,
    raise_on_error: bool = False,
) -> list[ValidationError]:
    """Run every validator over `node` and its descendants.

    Each `ValidationError` raised by a validator is caught, tagged with the
    focus node's id and the validator's name, and collected. With
    `raise_on_error` the first failure is re-raised instead of collected.

    Args:
        node: The node whose subtree (itself plus descendants) is validated.
        validators: The checks to run on every node.
        raise_on_error: Re-raise the first failure rather than collecting all.

    Returns:
        Every failure found, in walk order (empty if the subtree is valid).
    """
    errors: list[ValidationError] = []
    for focus in node.walk():
        for validator in validators:
            try:
                validator(focus)
            except ValidationError as error:
                error.node_id = focus.node_id
                error.validator = getattr(validator, "__name__", repr(validator))
                if raise_on_error:
                    raise
                errors.append(error)
    return errors
