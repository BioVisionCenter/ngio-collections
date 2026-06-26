# Make pydantic an optional dependency

## Context

`ngio-collections` declares `pydantic>=2` as a hard runtime dependency. But the
recent "make nodes pure data classes" work (commit 80746fc) already moved the
node spine off pydantic onto hand-rolled frozen `__slots__` classes, and node
`attributes` ride as raw `dict[str, JsonValue]` validated only on typed access.
As a result the **core read/write/resolve/inline path no longer needs pydantic**
— the only remaining couplings are small value types (`DocPath`, `ReferenceObj`),
a couple of `JsonValue` type-alias imports, the `BaseObj` base in `_config.py`,
and the genuinely validation-heavy **typed attribute layer** (`attributes/*`:
discriminated transformation union, `RootModel` lists, `Field` constraints).

Goal: `import ngio_collections` plus open/edit/save/resolve/inline work with **no
pydantic installed**. Typed attribute models stay on pydantic but behind an
optional extra — `pip install ngio-collections[validation]`. Accessing a typed
attribute symbol without pydantic raises a clear, actionable `ImportError`.

The hard part (reimplementing pydantic's discriminated unions / constraints) is
explicitly **out of scope** — we keep pydantic for what it's good at and gate it.

## Approach

### 1. Packaging — `pyproject.toml`
- Remove `pydantic` from `[project].dependencies` (leave `dependencies = []`).
- Add to `[project.optional-dependencies]`: `validation = ["pydantic>=2.0.0,<3.0.0"]`.
- Add `pydantic = "*"` to `[tool.pixi.feature.dev.dependencies]` and
  `[tool.pixi.feature.test.dependencies]` so the existing suites still exercise
  attributes (today pydantic reached those envs via the editable install's
  `dependencies`).
- Add a pydantic-free guard environment: a `core` pixi feature/environment with
  pytest but **no pydantic**, used to prove the core stays import-clean (see
  Verification).

### 2. A pydantic-free home for shared primitives — `models/_config.py`
`_config.py` becomes fully pydantic-free and gains the two primitives the core
needs:
- `JsonValue` — local recursive alias replacing `from pydantic import JsonValue`
  (`dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None`).
- `_AttributeKey` — the plain `ClassVar[str] key` + `name_space()` mixin, **moved
  here** from `attributes/_base.py` (it is pure Python and the node core uses it
  at runtime in `set_attr`/`drop_attrs`).
- Keep `NodeObj`, `NodeState`, `NodeStateError`.
- **Move `BaseObj`** (the frozen, camelCase-aliased pydantic base) out to the
  attributes layer — after this change only attributes use it.

### 3. De-pydantic the two core value types
Mirror the existing node shim pattern (frozen `__slots__` + `model_validate` /
`model_dump` / `model_copy` stand-ins). Implement `__eq__`/`__hash__` explicitly
(pydantic `BaseModel` gave value equality that callers/tests rely on).

- **`models/_paths.py`** — `DocPath` (and `ZarrPath`/`JsonPath` subclasses):
  fields `type: Literal["zarr","json"]`, `path: str`, plus an extras dict to
  preserve the old `extra="allow"` round-trip. Keep `resolve()` / `relativize()`
  delegating to the module functions (unchanged). Validate `type` in
  `model_validate`/`__init__`. `PathObj = DocPath` alias stays.
- **`models/_references.py`** — `ReferenceObj`: fields `id` (validated against the
  shared `ID_PATTERN`), `path: PathObj | None` (coerced from dict via
  `DocPath.model_validate`). Drop the `BaseObj` base and `from pydantic import
  Field`; replace `IdStr = Annotated[str, Field(pattern=...)]` with a plain
  `IdStr = str` alias (still exported).

### 4. Cut pydantic from the node core — `models/_nodes.py`
- `from pydantic import JsonValue` → import `JsonValue` from `_config`.
- The `attributes._base` import splits: import `_AttributeKey` from `_config`
  (runtime), and move `AnyAttribute` / `AttributeType` under a `TYPE_CHECKING`
  block (annotation-only).
- No guard needed inside `__getitem__`/`get_attr`/`set_attr`: they call
  `attr_type.model_validate(...)`, and an `attr_type` can only be obtained by
  importing the attributes layer, which already requires pydantic. Add a one-line
  comment noting this invariant.

### 5. `treeops/_jsonrefs.py`
- `from pydantic import JsonValue` → import from `_config`. (This module only
  walks raw dicts; no validation involved.)

### 6. Attributes subpackage stays on pydantic, behind a guard
- `models/attributes/_base.py` — define `BaseObj` here (moved from `_config`),
  re-import `_AttributeKey` from `_config`, keep `BaseAttribute` /
  `BaseListAttribute(RootModel[...])`.
- `models/attributes/__init__.py` — top-of-module guard:
  `try: import pydantic` `except ModuleNotFoundError: raise ImportError("Typed
  attribute models require pydantic — install ngio-collections[validation]")`.
  All the `_coordinate` / `_hcs` / `_attributes` / `_transformation` modules
  remain unchanged pydantic code.

### 7. Make the public surface lazy — the crux
Today `models/__init__.py` and the top-level `__init__.py` **eagerly** re-export
every attribute/transformation symbol, so `import ngio_collections` would still
need pydantic. Convert those re-exports to PEP 562 lazy loading:
- Import the **core** symbols eagerly (nodes, families, registry, `_paths`,
  `_references`, `_config`, stores, `Resolver`, `register_builtins`).
- For the ~33 attribute/transformation names (the symbols sourced from
  `models.attributes` — e.g. `PlateAttribute`, `CoordinateTransformation`,
  `Axis`, `BaseAttribute`, `RgbaColor`, `AnyAttribute`, …) define a module-level
  `__getattr__(name)` that imports them lazily from `ngio_collections.models
  .attributes` on first access (surfacing the guard's `ImportError` if pydantic
  is absent). Keep `__all__` complete and add `__dir__` for discoverability.
- Apply the same `__getattr__` in both `models/__init__.py` and the top-level
  `__init__.py`.
- `register_builtins()` keeps running at top-level import — the family modules
  (`_collection`/`_multiscale`/`_singlescale`) import neither attributes nor
  pydantic, so this is safe.

## Critical files
- `pyproject.toml` — dependency move + extra + pixi envs.
- `src/ngio_collections/models/_config.py` — drop pydantic; add `JsonValue`,
  `_AttributeKey`; remove `BaseObj`.
- `src/ngio_collections/models/_paths.py` — hand-rolled `DocPath`.
- `src/ngio_collections/models/_references.py` — hand-rolled `ReferenceObj`,
  plain `IdStr`.
- `src/ngio_collections/models/_nodes.py` — `JsonValue`/`_AttributeKey` imports,
  `TYPE_CHECKING` for attribute annotations.
- `src/ngio_collections/treeops/_jsonrefs.py` — `JsonValue` import.
- `src/ngio_collections/models/attributes/_base.py` — host `BaseObj`.
- `src/ngio_collections/models/attributes/__init__.py` — pydantic guard.
- `src/ngio_collections/models/__init__.py` + `src/ngio_collections/__init__.py`
  — lazy `__getattr__` for attribute symbols.

## Verification
1. Full suite with pydantic: `pixi run --environment dev pytest` — green
   (attributes still validated).
2. `pixi run lint` and `pixi run type-check` — clean.
3. Pydantic-free core (new `core` env, no pydantic). A small test asserting:
   - `import ngio_collections` succeeds;
   - an open → edit (`set_attrs`/`rename`/`add`) → save round-trip works
     (attributes round-trip as raw dicts);
   - reference resolve + `open_inlined` works;
   - accessing a typed symbol (e.g. `ngio_collections.PlateAttribute` or
     `node[PlateAttribute]`) raises `ImportError` mentioning
     `ngio-collections[validation]`.
   Run via `pixi run --environment core pytest tests/test_no_pydantic.py` (or a
   subprocess that blocks `pydantic` from `sys.modules`).
