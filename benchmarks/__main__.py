"""Benchmark runner (v5): load (or generate) a dataset, time ops, print a table.

Operations, in the spec's order of importance:

    read (inlined)  open_inlined over the on-disk (sharded) layout, cold cache
    walk            traverse every node of the in-memory tree
    find            look up a random existing id (an index lookup)
    edit            set_attrs on a random node (returns a new tree)
    write           snapshot a tree to one document, into a scratch dir

The dataset is generated once and cached under ``benchmarks/.data/`` (keyed by
shard + scale); later runs reuse it. ``walk`` / ``find`` / ``edit`` share one
in-memory ``open_inlined`` view; ``write`` owns a separate view + scratch dir.

Examples::

    python -m benchmarks                                  # all ops, default scale
    python -m benchmarks --target 1000000 --shard scene   # ~1M nodes
    python -m benchmarks --ops read,walk
"""

from __future__ import annotations

import argparse
import itertools
import random
import shutil
import tempfile
from pathlib import Path

import ngio_collections as ngc
from benchmarks import dataset as ds
from benchmarks._stores import DelayStore
from benchmarks.harness import Result, format_table, measure

ALL_OPS = ("read", "walk", "find", "edit", "write")


def _parse_ops(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return list(ALL_OPS)
    ops = [o.strip() for o in value.split(",") if o.strip()]
    unknown = [o for o in ops if o not in ALL_OPS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown op(s): {', '.join(unknown)}; choose from {', '.join(ALL_OPS)}"
        )
    return [o for o in ALL_OPS if o in ops]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="benchmarks", description=__doc__)
    p.add_argument(
        "--target", type=int, default=90_000, help="approx node count (default: 90,000)"
    )
    p.add_argument(
        "--shard",
        choices=["leaf", "scene", "well", "plate", "none"],
        default="scene",
        help="document boundary for the on-disk layout (default: scene)",
    )
    p.add_argument(
        "--ops",
        type=_parse_ops,
        default=list(ALL_OPS),
        help=f"subset of {{{','.join(ALL_OPS)}}} or 'all' (default: all)",
    )
    p.add_argument(
        "--repeats", type=int, default=5, help="timed runs per op (default: 5)"
    )
    p.add_argument(
        "--rebuild", action="store_true", help="regenerate the cached dataset"
    )
    p.add_argument(
        "--data-root", type=str, default=None, help="override the dataset cache root"
    )
    p.add_argument(
        "--seed", type=int, default=0, help="RNG seed for find/edit id sampling"
    )
    p.add_argument(
        "--io-latency-ms",
        type=float,
        default=0.0,
        help="inject per-read latency (ms) via a DelayStore (default: 0)",
    )
    return p.parse_args()


def _consume(iterable: object) -> int:
    count = 0
    for _ in iterable:  # type: ignore[attr-defined]
        count += 1
    return count


def main() -> None:
    """Load/generate the dataset, run the selected benchmarks, print the table."""
    args = _parse_args()

    scenes_per_well = ds.scenes_for_target(args.target)
    total_nodes = ds.estimate_nodes(scenes_per_well)
    counts = ds.node_counts(scenes_per_well)
    n_docs = ds.document_count(args.shard, scenes_per_well)
    data_root = Path(args.data_root) if args.data_root else None
    ops: list[str] = args.ops

    target_dir = ds.dataset_dir(args.shard, scenes_per_well, data_root)
    entry_url, setup_results = ds.ensure_dataset(
        args.shard, scenes_per_well, rebuild=args.rebuild, data_root=data_root
    )
    reused = not setup_results

    print()
    print("ngio-collections benchmark (v5)")
    print(f"  shard level : {args.shard}")
    print(f"  target      : {args.target:,}")
    print(f"  total nodes : {total_nodes:,}")
    print(f"  files       : {n_docs:,}")
    print(f"  scenes      : {counts['scenes']:,}")
    print(f"  ops         : {', '.join(ops)}")
    print(f"  repeats     : {args.repeats}")
    print(f"  io latency  : {args.io_latency_ms} ms")
    print(f"  dataset     : {target_dir}  ({'reused' if reused else 'generated'})")
    print()

    def _read_store() -> ngc.LocalStore | DelayStore:
        """A fresh store honoring --io-latency-ms (cold cache: new each call)."""
        store = ngc.LocalStore()
        return (
            DelayStore(store, args.io_latency_ms / 1000)
            if args.io_latency_ms
            else store
        )

    results: list[Result] = list(setup_results)
    scratch: Path | None = None
    try:
        view = None
        if any(op in ops for op in ("walk", "find", "edit")):
            view = ngc.open_inlined(entry_url, _read_store())
            ids = [n.id for n in view.walk() if n.id is not None]
            sample = random.Random(args.seed).sample(ids, k=min(len(ids), 1000))
            find_ids = itertools.cycle(sample)
            edit_ids = itertools.cycle(sample)

        if "read" in ops:
            results.append(
                measure(
                    "read (inlined)",
                    lambda: ngc.open_inlined(entry_url, _read_store()),
                    args.repeats,
                )
            )
        if "walk" in ops:
            assert view is not None
            results.append(measure("walk", lambda: _consume(view.walk()), args.repeats))
        if "find" in ops:
            assert view is not None
            results.append(
                measure(
                    "find (random id)", lambda: view.find(next(find_ids)), args.repeats
                )
            )
        if "edit" in ops:
            assert view is not None
            results.append(
                measure(
                    "edit (set_attrs)",
                    lambda: view.find(next(edit_ids)).set_attrs({"bench": 1}),
                    args.repeats,
                )
            )
        if "write" in ops:
            write_view = ngc.open_inlined(entry_url, _read_store())
            scratch = Path(tempfile.mkdtemp(prefix="ngio-bench-write-"))
            out_url = str(scratch / "snapshot.json")
            results.append(
                measure(
                    "write (snapshot)",
                    lambda: ngc.save_inlined(write_view, out_url, overwrite=True),
                    args.repeats,
                )
            )

        print(format_table(results))
        print()
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
