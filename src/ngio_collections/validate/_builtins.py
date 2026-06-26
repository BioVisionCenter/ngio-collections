"""The built-in example validators and their explicit registration.

These demonstrate the two neighbourhood shapes from the design:

- `WellUnderPlate` reads *up* (a node with a `well` capability must sit under a
  node with a `plate` capability) — `Scope(ancestors=1)`.
- `ScaleMatchesAxes` follows a *reference*: a `scale` transform's factor count
  must match the axis count of the coordinate system it points at, which is
  searched on the node itself and its ancestors — `Scope(ancestors=None,
  refs=True)`.

Registration is explicit (`register_builtins`) rather than import-side-effect, so
the composition root decides what is active.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from ngio_collections.models.attributes import (
    CoordinateSystem,
    CoordinateSystemsAttribute,
    CoordinateTransformationsAttribute,
    PlateAttribute,
    SceneAttribute,
    ScaleTransformation,
    WellAttribute,
)
from ngio_collections.validate._engine import (
    CapabilityValidator,
    Context,
    Issue,
    Scope,
    ValidatorRegistry,
)


class WellUnderPlate(CapabilityValidator):
    """A node carrying `well` must be a child of a node carrying `plate`."""

    name = "well-under-plate"
    capability = WellAttribute
    scope = Scope(ancestors=1)

    def check(self, ctx: Context) -> Iterable[Issue]:
        """Flag a `well` node whose parent does not carry a `plate`."""
        parent = ctx.parent
        if parent is None or not parent.has(PlateAttribute):
            yield Issue(
                ctx.node_id,
                self.name,
                "a node with a `well` attribute must be a child of a node with a "
                "`plate` attribute",
            )


class ScaleMatchesAxes(CapabilityValidator):
    """A `scale` transform's factor count must match its coordinate system's axes."""

    name = "scale-matches-axes"
    capability = CoordinateTransformationsAttribute
    scope = Scope(ancestors=None, refs=True)

    def check(self, ctx: Context) -> Iterable[Issue]:
        """Flag each `scale` transform whose length differs from its axes count."""
        for transform in ctx.view(CoordinateTransformationsAttribute).root:
            if not isinstance(transform, ScaleTransformation) or transform.scale is None:
                continue
            ref = transform.output or transform.input
            if ref is None:
                continue
            system = _find_coordinate_system(ctx, ref.id)
            if system is None:
                continue  # unresolved system: a referential check's concern, not this one
            if len(transform.scale) != len(system.axes):
                yield Issue(
                    ctx.node_id,
                    self.name,
                    f"scale transform has {len(transform.scale)} factor(s) but "
                    f"coordinate system {system.id!r} has {len(system.axes)} axis/axes",
                )


def _find_coordinate_system(ctx: Context, system_id: str) -> CoordinateSystem | None:
    """Search the focus node and its ancestors for coordinate system `system_id`."""
    for scope_ctx in _self_and_ancestors(ctx):
        system = _coordinate_system_in(scope_ctx, system_id)
        if system is not None:
            return system
    return None


def _self_and_ancestors(ctx: Context) -> Iterator[Context]:
    """Yield `ctx` then each of its ancestors up to the root."""
    yield ctx
    yield from ctx.ancestors()


def _coordinate_system_in(ctx: Context, system_id: str) -> CoordinateSystem | None:
    """Return the coordinate system `system_id` defined on `ctx`'s node, if any."""
    systems: list[CoordinateSystem] = []
    coordinate_systems = ctx.get(CoordinateSystemsAttribute)
    if coordinate_systems is not None:
        systems.extend(coordinate_systems.root)
    scene = ctx.get(SceneAttribute)
    if scene is not None and scene.coordinate_systems:
        systems.extend(scene.coordinate_systems)
    return next((s for s in systems if s.id == system_id), None)


def register_builtins(registry: ValidatorRegistry | None = None) -> ValidatorRegistry:
    """Register the built-in validators on `registry` (a fresh one if omitted)."""
    registry = registry if registry is not None else ValidatorRegistry()
    registry.register(WellUnderPlate())
    registry.register(ScaleMatchesAxes())
    return registry
