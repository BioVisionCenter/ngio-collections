# benchmarks

Performance benchmarks for ngio-collections. Builds a realistic RFC-8
revision-1 HCS collection at a configurable scale (up to ~1M nodes), caches it
on disk, runs the core operations, and prints average run time + peak memory
per operation. Standard-library only (no extra dependencies).

## Run

```bash
# first run: generate + cache the dataset, then run all ops
pixi run --environment dev python -m benchmarks

# run again: the dataset is reused from cache (no write), much faster
pixi run --environment dev python -m benchmarks

# the real target: ~1M nodes (lower repeats: read is heavy)
pixi run --environment dev python -m benchmarks --target 1000000 --shard scene --repeats 3

# run only some operations, or model a slow store
pixi run --environment dev python -m benchmarks --ops read,walk
pixi run --environment dev python -m benchmarks --ops read --io-latency-ms 1

# force regeneration of the cached dataset
pixi run --environment dev python -m benchmarks --rebuild
```

## Dataset

```
root -> 20 plates (plate trait) -> 240 wells/plate (well trait, 4800 wells) -> n scenes/well
each scene: 1 image multiscale + 1 label multiscale (labels trait) + 16 extension-type tables
total nodes = 4821 + 4800 * n * 19
```

`--target` (default 90,000) is the only scale knob: the dataset uses the
smallest whole number of scenes-per-well that reaches at least `target` nodes.
Each step adds 91,200 nodes (4800 wells × 19), so the realized count rounds up:
`--target 1000000` ⇒ 1,008,021 nodes.

Node count means *declared nodes*: scales and coordinate systems are
declarations inside a multiscale document, not nodes. Every multiscale carries
one coordinate system and three scales.

### Documents

Under the revision a multiscale is never embedded in a collection, so every
image and label is written as its own `zarr.json` whatever the sharding: at
~1M nodes that is ~105,600 image documents. `--shard` decides only where the
*collection* documents are cut:

- `scene` (default): root / plate / well / scene are each documents.
- `well`: root / plate / well documents; scenes embedded in their well.
- `plate`: root / plate documents; wells and scenes embedded.
- `none`: one collection document (with ~105k declaring entries at 1M).

Tables (an extension node type, `https://ngio.example/bench/table`) are
embedded in their scene; the manifest declaring the extension is written on
every document.

### Local cache

Datasets are generated once into `benchmarks/.data/<shard>-n<scenes>/`
(gitignored) and reused on later runs, keyed by sharding + scale. A
`.benchmark.json` marker records the entry document, node and document counts.
Use `--rebuild` to regenerate, or `--data-root PATH` to store the cache
elsewhere. If you change the builders in `dataset.py`, pass `--rebuild`.

## Operations

| operation           | what it measures                                              |
| ------------------- | ------------------------------------------------------------- |
| `read (resolved)`   | `open_resolved` over the on-disk layout, cold cache           |
| `walk`              | full depth-first traversal of the in-memory view              |
| `find`              | `find(uuid)` for a random existing id (an index lookup, O(1)) |
| `edit`              | `set_trait` on a random node (new tree; copy-on-write map)    |
| `validate`          | `CORE_VALIDATORS` over the whole view (each check O(neighbourhood)) |
| `write (root doc)`  | `save` of the opened entry collection document                |
| `write (image doc)` | `save` of one opened multiscale document                      |

`--ops` selects any subset (comma-separated, or `all`). `walk` / `find` /
`edit` / `validate` share one in-memory `open_resolved` view; `read` builds and
discards a view each run.

**There is no single-snapshot write any more.** The previous `write` row
(`save_inlined` of the whole tree into one document) measured a layout the
revision forbids: a collection can never contain a multiscale's body. The cost
of writing the whole tree is reported once as the `dataset write (disk)` setup
row of a fresh run. Consolidated metadata, the revision's answer to
one-request loading, is a planned follow-up and will get its own row.

## Modifying

- **Add an operation:** write a zero-arg callable, add it to `ALL_OPS` and append
  `measure("<name>", fn, args.repeats)` to `results` in `benchmarks/__main__.py`.
- **Change the layout / traits:** edit the builders in `benchmarks/dataset.py`
  (`_Writer`, `_multiscale_record`), then re-run with `--rebuild`. Traits are
  intentionally light so node *count*, not trait validation, is what scales.
- **Change measurement:** `benchmarks/harness.py` (timing, memory, formatting).
