"""Benchmark runner: load (or generate) a dataset, time ops, print a table.

Operations, in the spec's order of importance:

    read (resolved)   open_resolved over the on-disk layout, cold cache
    walk              traverse every node of the in-memory view
    find              look up a random existing UUID (an index lookup)
    edit              set_trait on a random node (returns a new tree)
    validate          CORE_VALIDATORS over the whole view (O(neighbourhood) each)
    write (root doc)  open + save the entry collection document
    write (image doc) open + save one multiscale document

There is no single-snapshot write any more: RFC-8 revision 1 never embeds a
multiscale in a collection, so a self-contained one-document copy of the tree
cannot exist. The full-tree write is reported once as the dataset setup row.

The dataset is generated once and cached under ``benchmarks/.data/`` (keyed by
shard + scale); later runs reuse it. ``walk`` / ``find`` / ``edit`` /
``validate`` share one in-memory ``open_resolved`` view.

Examples::

    python -m benchmarks                                  # all ops, default scale
    python -m benchmarks --target 1000000 --shard scene   # ~1M nodes
    python -m benchmarks --ops read,walk --io-latency-ms 1
"""

from __future__ import annotations

import argparse
import itertools
import random

import ngio_collections as ngc
from benchmarks import dataset as ds
from benchmarks._stores import DelayStore
from benchmarks.harness import Result, format_table, measure

ALL_OPS = ("read", "walk", "find", "edit", "validate", "write")


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
        choices=["scene", "well", "plate", "none"],
        default="scene",
        help="collection document boundary for the on-disk layout (default: scene)",
    )
    p.add_argument(
        "--ops",
        type=_parse_ops,
        default=list(ALL_OPS),
        help=f"subset of {{{','.join(ALL_OPS)}}} or 'all'",
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
        help="inject per-read latency (ms) via a DelayStore",
    )
    return p.parse_args()


def _consume(iterable: object) -> int:
    count = 0
    for _ in iterable:  # type: ignore[attr-defined]
        count += 1
    return count


def main() -> None:
    """Load/generate the dataset, run the selected benchmarks, print the table."""
    from pathlib import Path

    args = _parse_args()
    ngc.register_extension(ds.BENCH_EXTENSION)

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
    print("ngio-collections benchmark (RFC-8 revision 1)")
    print(f"  shard level : {args.shard}")
    print(f"  target      : {args.target:,}")
    print(f"  total nodes : {total_nodes:,}")
    print(f"  documents   : {n_docs:,}  (every multiscale is its own document)")
    print(f"  scenes      : {counts['scenes']:,}")
    print(f"  ops         : {', '.join(ops)}")
    print(f"  repeats     : {args.repeats}")
    print(f"  io latency  : {args.io_latency_ms} ms")
    print(f"  dataset     : {target_dir}  ({'reused' if reused else 'generated'})")
    print()

    def _store() -> ngc.LocalStore | DelayStore:
        """A fresh store honoring --io-latency-ms (cold cache: new each call)."""
        store = ngc.LocalStore()
        return (
            DelayStore(store, args.io_latency_ms / 1000)
            if args.io_latency_ms
            else store
        )

    results: list[Result] = list(setup_results)
    view = None
    if any(op in ops for op in ("walk", "find", "edit", "validate")):
        view = ngc.open_resolved(entry_url, _store())
        ids = [n.id for n in view.walk()]
        sample = random.Random(args.seed).sample(ids, k=min(len(ids), 1000))
        find_ids = itertools.cycle(sample)
        edit_ids = itertools.cycle(sample)

    if "read" in ops:
        results.append(
            measure(
                "read (resolved)",
                lambda: ngc.open_resolved(entry_url, _store()),
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
                "find (random uuid)", lambda: view.find(next(find_ids)), args.repeats
            )
        )
    if "edit" in ops:
        assert view is not None
        results.append(
            measure(
                "edit (set_trait)",
                lambda: view.find(next(edit_ids)).set_trait(
                    {"type": "https://ngio.example/bench/mark", "n": 1}
                ),
                args.repeats,
            )
        )
    if "validate" in ops:
        assert view is not None
        results.append(
            measure(
                "validate (core)",
                lambda: view.validate(ngc.CORE_VALIDATORS),
                max(1, args.repeats // 2),
            )
        )
    if "write" in ops:
        root_doc = ngc.open(entry_url, _store())
        results.append(
            measure(
                "write (root doc)", lambda: ngc.save(root_doc, _store()), args.repeats
            )
        )
        image_url = next(
            n.document_url
            for n in ngc.open_resolved(entry_url, _store()).walk()
            if n.type == "multiscale" and n.document_url
        )
        assert image_url is not None
        image_doc = ngc.open(image_url, _store())
        results.append(
            measure(
                "write (image doc)", lambda: ngc.save(image_doc, _store()), args.repeats
            )
        )

    print(format_table(results))
    print()


if __name__ == "__main__":
    main()
