"""Benchmark runner: load (or generate) a dataset, time ops, print a table.

Operations, in the spec's order of importance:

    read (inlined)  open_inlined over the on-disk (sharded) layout, cold cache
    walk            traverse every node of the in-memory tree
    find            look up a random existing id (an O(n) walk)
    edit            set_attrs on a random node (immutable spine rebuild)
    write           snapshot a tree to one document, into a scratch dir

The dataset is generated once and cached under ``benchmarks/.data/`` (keyed by
shard + scale); later runs reuse it. ``read`` is measured against that on-disk
layout; ``walk`` / ``find`` / ``edit`` share one in-memory ``open_inlined`` view;
``write`` owns a *separate* view and writes to its own scratch dir, so it is
fully decoupled from the read path. Use ``--ops`` to run any subset.

Examples::

    python -m benchmarks                          # generate + cache, run all ops
    python -m benchmarks                          # again: reuse cache, much faster
    python -m benchmarks --target 1000000 --shard none   # ~1M nodes, one document
    python -m benchmarks --ops read,walk          # only these operations
    python -m benchmarks --shard leaf --target 100000    # per-leaf documents
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
    # preserve importance order regardless of how they were listed
    return [o for o in ALL_OPS if o in ops]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="benchmarks", description=__doc__)
    p.add_argument(
        "--target",
        type=int,
        default=90_000,
        help="approximate node count; the scale knob (default: 90,000)",
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
        help=f"comma-separated subset of {{{','.join(ALL_OPS)}}} or 'all' (default: all)",
    )
    p.add_argument(
        "--repeats", type=int, default=5, help="timed runs per operation (default: 5)"
    )
    p.add_argument(
        "--rebuild",
        action="store_true",
        help="regenerate the cached dataset even if it already exists",
    )
    p.add_argument(
        "--data-root",
        type=str,
        default=None,
        help="override the dataset cache root (default: benchmarks/.data)",
    )
    p.add_argument(
        "--seed", type=int, default=0, help="RNG seed for find/edit id sampling"
    )
    return p.parse_args()


def _consume(iterable: object) -> int:
    """Drain an iterable, returning how many items it yielded."""
    count = 0
    for _ in iterable:  # type: ignore[attr-defined]
        count += 1
    return count


def main() -> None:
    """Load/generate the dataset, run the selected benchmarks, print the table."""
    args = _parse_args()
    ds.register_tables()

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
    print("ngio-collections benchmark")
    print(f"  shard level : {args.shard}")
    print(f"  target      : {args.target:,}")
    print(f"  total nodes : {total_nodes:,}")
    print(f"  files       : {n_docs:,}")
    print(f"  plates      : {counts['plates']:,}")
    print(f"  wells       : {counts['wells']:,}")
    print(f"  scenes      : {counts['scenes']:,}")
    print(f"  images      : {counts['images']:,}")
    print(f"  labels      : {counts['labels']:,}")
    print(f"  tables      : {counts['tables']:,}")
    print(f"  ops         : {', '.join(ops)}")
    print(f"  repeats     : {args.repeats}")
    print(f"  dataset     : {target_dir}  ({'reused' if reused else 'generated'})")
    print()

    results: list[Result] = list(setup_results)
    scratch: Path | None = None
    try:
        # one shared view for the in-memory ops; loaded only if any is selected
        view = None
        if any(op in ops for op in ("walk", "find", "edit")):
            view = ngc.open_inlined(entry_url)
            ids = [n.id for n in view.walk() if getattr(n, "id", None) is not None]
            sample = random.Random(args.seed).sample(ids, k=min(len(ids), 1000))
            find_ids = itertools.cycle(sample)
            edit_ids = itertools.cycle(sample)

        if "read" in ops:
            results.append(
                measure(
                    "read (inlined)", lambda: ngc.open_inlined(entry_url), args.repeats
                )
            )
        if "walk" in ops:
            assert view is not None
            results.append(measure("walk", lambda: _consume(view.walk()), args.repeats))
        if "find" in ops:
            assert view is not None
            results.append(
                measure(
                    "find (random id)",
                    lambda: view.find(id=next(find_ids)),
                    args.repeats,
                )
            )
        if "edit" in ops:
            assert view is not None
            results.append(
                measure(
                    "edit (set_attrs)",
                    lambda: view.set_attrs(id=next(edit_ids), values={"bench": 1}),
                    args.repeats,
                )
            )
        if "write" in ops:
            # decoupled: its own view + its own scratch destination
            write_view = ngc.open_inlined(entry_url)
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
