# Make pydantic an optional dependency

## Context

`ngio-collections` declares `pydantic>=2` as a hard runtime dependency. But the
v5 redesign (flat indexed immutable graph: `graph/` `NodeTree`+`NodeRecord`,
`resolve/`, `validate/`, `api/`) keeps the node spine **off pydantic** — a
`NodeRecord` is a frozen `dataclass`, and node `attributes` ride as a raw
`dict[str, JsonValue]` validated only on typed access (`node[WellAttribute]`). As
a result the **core read/write/resolve/inline path no longer needs pydantic** —
the only remaining couplings are:

- `JsonValue` type-alias imports across `graph/`, `resolve/`, and `api/`;
- the small value types `DocPath` (`models/_paths.py`) and `ReferenceObj`
  (`models/_references.py`), plus the `BaseObj` base;
- the genuinely validation-heavy **typed attribute layer** (`models/attributes/*`:
  discriminated transformation union, `RootModel` lists, `Field` constraints);
- the **built-in capability validators** (`validate/_builtins.py`), which import
  those typed models to do their checks.

Goal: `import ngio_collections` plus open/edit/save/resolve/inline work with **no
pydantic installed**. Typed attribute models and the built-in validators stay on
pydantic but behind an optional extra — `pip install ngio-collections[validation]`.
Accessing a typed attribute symbol without pydantic raises a clear, actionable
`ImportError`.

The hard part (reimplementing pydantic's discriminated unions / constraints) is
explicitly **out of scope** — we keep pydantic for what it's good at and gate it.

## Approach

### 1. Packaging — `pyproject.toml`
- Remove `pydantic` from `[project].dependencies` (leave `dependencies = []`).
- Add to `[project.optional-dependencies]`:
  `validation = ["pydantic>=2.0.0,<3.0.0"]`.
- Add `pydantic = "*"` to `[tool.pixi.feature.dev.dependencies]` and
  `[tool.pixi.feature.test.dependencies]` so the existing suites still exercise
  attributes (today pydantic reaches those envs via the editable install's
  `dependencies`).
- Add a pydantic-free guard environment: a `core` pixi feature/environment with
  pytest but **no pydantic**, used to prove the core stays import-clean (see
  Verification).

### 2. A pydantic-free home for shared primitives — `models/_config.py`
`_config.py` becomes fully pydantic-free:
- Add `JsonValue` — a local recursive alias replacing `from pydantic import
  JsonValue` (`dict[str, JsonValue] | list[JsonValue] | str | int | float | bool
  | None`).
- Keep `NodeStateError`.
- **Move `BaseObj`** (the frozen, camelCase-aliased pydantic base) out to the
  attributes layer — after this change only the attributes layer uses it.

### 3. De-pydantic the two core value types — stdlib dataclasses
Make `DocPath` and `ReferenceObj` plain **`@dataclass(frozen=True, slots=True)`**
with no pydantic import. `frozen=True` gives value `__eq__`/`__hash__` for free
(callers/tests rely on it). Validation goes in `__post_init__`.

The key design point (verified against pydantic v2): **pydantic consumes a stdlib
dataclass natively when it appears as a field type** — it coerces an incoming
`dict` into the dataclass, runs the dataclass's `__post_init__` (so pattern
validation still fires through pydantic), and serializes it back on `model_dump`.
So `ReferenceObj` is defined *once*, pydantic-free, and the pydantic
transformation models keep `input: ReferenceObj | None` / `output: ReferenceObj |
None` (`models/attributes/_transformation.py`) unchanged — no duplication, no
`arbitrary_types_allowed`, no `__get_pydantic_core_schema__`.

- **`models/_references.py`** — `ReferenceObj`: `id: str` (validated against
  `ID_PATTERN` in `__post_init__`), `path: DocPath | None = None`. Drop the
  `BaseObj` base and `from pydantic import Field`. Add thin
  `model_validate` (classmethod, `dict -> ReferenceObj`) / `model_dump`
  (`ReferenceObj -> dict`) shims so the **pydantic-free core** (`Node.ref()`,
  `resolve` serialization) can (de)serialize without pydantic. Keep `ID_PATTERN`
  here.
- **`models/_paths.py`** — `DocPath` (and `ZarrPath`/`JsonPath` subclasses):
  `type: Literal["zarr","json"]`, `path: str`, validated in `__post_init__`. Keep
  `resolve()` / `relativize()` delegating to the module functions, plus
  `model_validate`/`model_dump`/`model_copy` shims for the core path. `PathObj =
  DocPath` alias stays. (`ReferenceObj.path` nests `DocPath`; pydantic handles the
  nested dataclass-in-dataclass too.)
- **`IdStr`** (decision): keep `ID_PATTERN` in `_references.py` (pydantic-free)
  and validate it in `ReferenceObj.__post_init__`. **Keep the pydantic
  `IdStr = Annotated[str, Field(pattern=ID_PATTERN)]` in the attributes tier**
  (move its definition to `models/attributes/`), because `CoordinateSystem.id`
  (a pydantic model in `_coordinate.py`) relies on it — flattening `IdStr` to a
  plain `str` would silently drop pattern validation there.
- **`extra="allow"` (decision):** the old `BaseObj`/`DocPath` round-tripped
  unknown keys; a fixed-field dataclass cannot. These are tiny closed-shape
  locators, so **drop extra-allow for `DocPath`/`ReferenceObj`** rather than carry
  an `extras: dict` field + custom schema. (Revisit only if real documents are
  found stashing extra keys on a reference/path.) The two serialization paths —
  the core's `model_dump` shim and pydantic's nested-dataclass serializer — must
  agree on the wire dict; trivial here since `id`/`path`/`type` need no camelCase
  aliasing.

### 4. Repoint the `JsonValue` imports to `_config`
In each of these, `from pydantic import JsonValue` → `from
ngio_collections.models._config import JsonValue` (all annotation / raw-dict
walking — no validation involved):
`graph/_record.py`, `graph/_tree.py`, `api/_node.py`, `resolve/_build.py`,
`resolve/_jsonrefs.py`.

### 5. Decouple the core handle & validator engine from the attributes import
`api/_node.py`, `validate/_engine.py`, and `validate/_views.py` import
`AnyAttribute` from `models.attributes` only for a `TypeVar` bound plus type
annotations. All three already have `from __future__ import annotations`, so their
annotations are strings already. For each:
- Move `from ngio_collections.models.attributes import AnyAttribute` under a
  `TYPE_CHECKING` block.
- Change `A = TypeVar("A", bound=AnyAttribute)` → `A = TypeVar("A",
  bound="AnyAttribute")` (a string forward-ref bound is not evaluated at import).

No inline guard is needed in the runtime methods (`set_attr`/`drop_attrs`/
`__contains__`, `read_attribute`/`get_attribute`/`has_attribute`): they only ever
call `.key` / `.model_dump` / `.model_validate` on a caller-supplied attribute
*instance or class*, and you cannot obtain one without importing the attributes
layer — which already requires pydantic. Add a one-line comment noting this
invariant.

### 6. Attributes **and** built-in validators stay on pydantic, behind a guard
- `models/attributes/_base.py` — define `BaseObj` here (moved from `_config`);
  keep `_AttributeKey`, `BaseAttribute`, `BaseListAttribute(RootModel[...])`.
- `models/attributes/__init__.py` — top-of-module guard:
  `try: import pydantic` / `except ModuleNotFoundError: raise ImportError("Typed
  attribute models require pydantic — install ngio-collections[validation]")`. The
  `_coordinate` / `_hcs` / `_attributes` / `_transformation` modules stay
  unchanged pydantic code.
- `validate/_builtins.py` is genuinely pydantic (it imports `PlateAttribute`,
  `ScaleTransformation`, … and does `isinstance` checks on them). It belongs to
  the validation tier. Keep it as-is, but make `validate/__init__.py` serve its
  symbols (`ScaleMatchesAxes`, `WellUnderPlate`, `register_builtins`) **lazily**
  via a module `__getattr__`, eager-importing only the engine (`_engine`) and the
  lenses (`_views`).

### 7. Make the public surface lazy — the crux
Today `models/__init__.py` (eager attribute imports), `api/__init__.py`
(`from ngio_collections.models import *`), and the top-level `__init__.py`
(`from .api import *`) eagerly re-export every attribute/transformation symbol, so
`import ngio_collections` still needs pydantic. Convert all three to PEP 562 lazy
loading.

Key gotcha: **`from X import *` resolves every name in `X.__all__` eagerly and
does *not* trigger module `__getattr__`.** So the two star-imports must be
replaced with explicit eager imports of the core names plus a forwarding
`__getattr__` for the lazy names.

- `models/__init__.py`: import the **core** symbols eagerly (`NodeStateError`;
  `DocPath`/`JsonPath`/`PathObj`/`ZarrPath`; `IdStr`/`ReferenceObj`). The ~34
  attribute/transformation names **plus `BaseObj`** become lazy: define
  `__getattr__(name)` importing them from `ngio_collections.models.attributes` on
  first access (surfacing the guard's `ImportError` if pydantic is absent). Keep
  `__all__` complete and add `__dir__`.
- `api/__init__.py`: replace `from ngio_collections.models import *` with an
  explicit eager import of the core model names, and add a module `__getattr__`
  forwarding the lazy attribute names to `ngio_collections.models`. Keep `__all__`.
  The composition root must **not** eagerly register pydantic-bound validators:
  guard `register_builtins(DEFAULT_VALIDATORS)` on pydantic availability
  (`try: import pydantic` → register; `except ModuleNotFoundError: pass`).
  `register_node_types()` stays unconditional (no pydantic).
- top-level `src/ngio_collections/__init__.py`: replace `from .api import *` with
  an eager import of `api`'s eager names plus a `__getattr__` forwarding the lazy
  names to `.api`. Keep `__all__`.

## Critical files
- `pyproject.toml` — dependency move + extra + pixi envs.
- `src/ngio_collections/models/_config.py` — drop pydantic; add `JsonValue`;
  remove `BaseObj`.
- `src/ngio_collections/models/_paths.py` — hand-rolled `DocPath`.
- `src/ngio_collections/models/_references.py` — hand-rolled `ReferenceObj`,
  plain `IdStr`.
- `src/ngio_collections/graph/_record.py`, `graph/_tree.py`,
  `resolve/_build.py`, `resolve/_jsonrefs.py` — `JsonValue` import from `_config`.
- `src/ngio_collections/api/_node.py` — `JsonValue` import; `TYPE_CHECKING`
  `AnyAttribute` + string `TypeVar` bound.
- `src/ngio_collections/validate/_engine.py`, `validate/_views.py` —
  `TYPE_CHECKING` `AnyAttribute` + string `TypeVar` bound.
- `src/ngio_collections/models/attributes/_base.py` — host `BaseObj`.
- `src/ngio_collections/models/attributes/__init__.py` — pydantic guard.
- `src/ngio_collections/validate/__init__.py` — lazy `_builtins` symbols.
- `src/ngio_collections/models/__init__.py`, `api/__init__.py`,
  `src/ngio_collections/__init__.py` — lazy `__getattr__`, replace star-imports,
  guard composition-root validator registration.

## Verification
1. Full suite with pydantic: `pixi run --environment dev pytest` — green
   (attributes + built-in validators still validated).
2. `pixi run lint` and `pixi run type-check` — clean.
3. Pydantic-free core (new `core` env, no pydantic). A small test asserting:
   - `import ngio_collections` succeeds;
   - an open → edit (`set_attrs`/`rename`/`add`) → save round-trip works
     (attributes round-trip as raw dicts);
   - reference resolve + `open_inlined` works;
   - accessing a typed symbol (e.g. `ngio_collections.WellAttribute` or
     `node[WellAttribute]`) raises `ImportError` mentioning
     `ngio-collections[validation]`.
   Run via `pixi run --environment core pytest tests/test_no_pydantic.py` (or a
   subprocess that blocks `pydantic` from `sys.modules`).
