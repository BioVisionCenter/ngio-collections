# benchmarks

Performance benchmarks for ngio-collections. Builds a realistic RFC-8 HCS
collection at a configurable scale (up to ~1M nodes), caches it on disk, runs
the core operations, and prints average run time + peak memory per operation.
Standard-library only (no extra dependencies).

## Run

```bash
# first run: generate + cache the dataset, then run all ops
pixi run --environment dev python -m benchmarks

# run again: the dataset is reused from cache (no build/write), much faster
pixi run --environment dev python -m benchmarks

# the real target: ~1M nodes (lower repeats — read/write are heavy)
pixi run --environment dev python -m benchmarks --target 1000000 --shard none --repeats 3

# run only some operations
pixi run --environment dev python -m benchmarks --ops read,walk
pixi run --environment dev python -m benchmarks --ops write

# force regeneration of the cached dataset
pixi run --environment dev python -m benchmarks --rebuild
```

## Dataset

```
root -> 20 plates -> 240 wells/plate (4800 wells) -> n scenes/well
each scene: 3 multiscale images + 5 multiscale labels + 10 tables
total nodes = 4821 + 4800 * n * 19
```

`--target` (default 100,000) is the only scale knob: the dataset uses the
smallest whole number of scenes-per-well that reaches at least `target` nodes.
Because each scenes-per-well step adds 91,200 nodes (4800 wells × 19), the
realized count rounds up to that granularity — e.g. `--target 100000` ⇒ 187,221
nodes, `--target 1000000` ⇒ 1,008,021.

### Local cache

Datasets are expensive to build, so each is generated once into
`benchmarks/.data/<shard>-n<scenes>/` (gitignored) and reused on later runs —
keyed by sharding + scale. A `.benchmark.json` marker records the entry document
and node count. Use `--rebuild` to regenerate, or `--data-root PATH` to store
the cache elsewhere (e.g. a faster disk). The cache key covers only
`(shard, scenes-per-well)`; if you change the builders in `dataset.py`, pass
`--rebuild`.

## Operations (in order of importance)

| operation        | what it measures                                            |
| ---------------- | ---------------------------------------------------------- |
| `read (inlined)` | `open_inlined` over the on-disk layout, cold cache         |
| `walk`           | full depth-first traversal of the in-memory tree           |
| `find`           | `find(id)` for a random existing id (an index lookup, O(1))|
| `edit`           | `set_attrs` on a random node (new tree; copy-on-write map) |
| `write`          | `save_inlined` snapshot of a tree to one document          |

`--ops` selects any subset (comma-separated, or `all`). `walk` / `find` / `edit`
share one in-memory `open_inlined` view; `read` and `write` are independent:
`read` builds and discards a view each run, and `write` owns a *separate* view
and writes to its own scratch dir (removed afterwards) — it never touches the
cached dataset or the read path. Running the walk-group and `write` together
holds two full trees in memory (~2× at 1M); isolate them with `--ops` for the
largest runs.

`write` uses `save_inlined` to snapshot the resolved (inlined) view to one
self-contained document, repeatably, into a scratch dir.

## Results & backend (v5)

At ~1.0M nodes (in-memory, stdlib `PersistentMap`): build ~5.9 s, walk ~127 ms,
`find` ~90 ns, a single `set_attrs` ~9.3 ms (one 1M-entry dict copy), and 200
edits batched through one `mutate()` evolver ~38 µs each. The single-edit cost is
fine for interactive use and batch edits amortise via the evolver, so the
**stdlib backend is sufficient — no `pyrsistent` needed**. Bulk construction goes
through `graph.TreeBuilder` (one O(n) pass); per-node `add_child` is O(n) and only
for incremental edits.

## Sharding (`--shard`)

Controls the document boundary of the on-disk layout, which dominates the
`read (inlined)` cost (inlining resolves across every boundary):

- `scene` (default): root/plate/well are documents referencing per-scene docs.
- `well`: root/plate documents referencing per-well docs (scenes inline).
- `plate`: root referencing per-plate docs (everything below inline).
- `none`: a single monolithic document.
- `leaf`: every multiscale image, label, and table is its own single-node
  document (scene docs reference them). **Warning:** at ~1M nodes this writes
  ~1M files — use it at a small `--target` for comparison, not routine 1M runs.

## Modifying

- **Add an operation:** write a zero-arg callable, add it to `ALL_OPS` and append
  `measure("<name>", fn, args.repeats)` to `results` in `benchmarks/__main__.py`.
- **Change the layout / attributes:** edit the builder in
  `benchmarks/dataset.py` (`build_monolithic` / `_scene_children`), then
  re-run with `--rebuild`. Attributes are intentionally light (a `{"role": ...}`
  marker) so node *count*, not attribute validation, is what scales.
- **Change measurement:** `benchmarks/harness.py` (timing, memory, formatting).
