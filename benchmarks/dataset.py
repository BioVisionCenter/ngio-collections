"""Builds the benchmark dataset (v5) and writes it to disk at a chosen sharding.

The dataset mirrors a realistic RFC-8 HCS collection:

    root -> 20 plates -> 240 wells/plate -> n scenes/well

and every scene holds 3 multiscale images, 5 multiscale labels and 10 tables
(18 child nodes). Node count scales linearly with ``scenes_per_well``::

    total = 4821 + 4800 * scenes_per_well * 19

so ``scenes_per_well == 11`` yields ~1.0M nodes (see ``scenes_for_target``).

``build_monolithic`` returns the full detached in-memory ``NodeTree`` (every node
inline), built in one O(n) pass with ``TreeBuilder``. ``write_sharded`` writes it
to disk, splitting it into one document per node at or above the chosen boundary
(``leaf`` / ``scene`` / ``well`` / ``plate``) or a single document (``none``);
parent documents reference their children with relativized ``path`` stubs. That is
the layout the ``open_inlined`` read benchmark resolves across. Datasets are cached
under ``benchmarks/.data/<shard>-n<scenes>/`` and reused across runs.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Literal

from benchmarks.harness import Result, measure_value
from ngio_collections.api._node import reference_path
from ngio_collections.graph import ROOT, NodeId, NodeRecord, NodeTree, Reference, TreeBuilder
from ngio_collections.io.store import LocalStore, WritableStore
from ngio_collections.resolve import write_document

# --- fixed layout (per the spec) --------------------------------------------

PLATES = 20
WELLS_PER_PLATE = 240
TOTAL_WELLS = PLATES * WELLS_PER_PLATE  # 4800
IMAGES = 3
LABELS = 5
TABLES = 10
NODES_PER_SCENE = 1 + IMAGES + LABELS + TABLES  # 19 (scene node + 18 children)
FIXED_NODES = 1 + PLATES + TOTAL_WELLS  # 4821 (root + plates + wells)

ShardLevel = Literal["leaf", "scene", "well", "plate", "none"]

# Depth at (and above) which a node becomes its own document. root=0, plate=1,
# well=2, scene=3, leaf (multiscale/table)=4.
_BOUNDARY_DEPTH: dict[ShardLevel, int] = {
    "none": 0,
    "plate": 1,
    "well": 2,
    "scene": 3,
    "leaf": 4,
}


def register_tables() -> None:
    """No-op: tables are plain `bench:table` records (no typed handle needed)."""


# --- node-count helpers ------------------------------------------------------


def estimate_nodes(scenes_per_well: int) -> int:
    """Total node count for a dataset with ``scenes_per_well`` scenes per well."""
    return FIXED_NODES + TOTAL_WELLS * scenes_per_well * NODES_PER_SCENE


def scenes_for_target(target: int = 1_000_000) -> int:
    """Smallest ``scenes_per_well`` whose dataset has at least ``target`` nodes."""
    per_n = TOTAL_WELLS * NODES_PER_SCENE
    return max(1, -(-(target - FIXED_NODES) // per_n))  # ceil division


def node_counts(scenes_per_well: int) -> dict[str, int]:
    """Per-kind node counts for the generated dataset."""
    scenes = TOTAL_WELLS * scenes_per_well
    return {
        "plates": PLATES,
        "wells": TOTAL_WELLS,
        "scenes": scenes,
        "images": scenes * IMAGES,
        "labels": scenes * LABELS,
        "tables": scenes * TABLES,
    }


def document_count(shard: ShardLevel, scenes_per_well: int) -> int:
    """Number of documents (files) written for the given sharding."""
    scenes = TOTAL_WELLS * scenes_per_well
    leaves = scenes * (IMAGES + LABELS + TABLES)
    per_depth = (1, PLATES, TOTAL_WELLS, scenes, leaves)  # depth 0..4
    return sum(per_depth[: _BOUNDARY_DEPTH[shard] + 1])


# --- in-memory builder (detached, one O(n) pass) ----------------------------


def _scene_children(tb: TreeBuilder, scene_key: NodeId, scene_id: str) -> None:
    for i in range(IMAGES):
        tb.add_child(scene_key, NodeRecord(type="multiscale", id=f"{scene_id}-img{i}",
                                           name=f"img{i}", attributes={"role": "image"}))
    for i in range(LABELS):
        tb.add_child(scene_key, NodeRecord(type="multiscale", id=f"{scene_id}-lbl{i}",
                                           name=f"lbl{i}", attributes={"role": "label"}))
    for i in range(TABLES):
        tb.add_child(scene_key, NodeRecord(type="bench:table", id=f"{scene_id}-tbl{i}",
                                           name=f"tbl{i}", attributes={"role": "table"}))


def build_monolithic(scenes_per_well: int) -> NodeTree:
    """Build the full detached collection tree with every node inline (O(n))."""
    tb = TreeBuilder(NodeRecord(type="collection", id="root", name="root",
                                attributes={"role": "root"}, children=()))
    for p in range(PLATES):
        pid = f"p{p}"
        pk = tb.add_child(ROOT, NodeRecord(type="collection", id=pid, name=pid,
                                           attributes={"role": "plate"}, children=()))
        for w in range(WELLS_PER_PLATE):
            wid = f"{pid}-w{w}"
            wk = tb.add_child(pk, NodeRecord(type="collection", id=wid, name=wid,
                                             attributes={"role": "well"}, children=()))
            for s in range(scenes_per_well):
                sid = f"{wid}-s{s}"
                sk = tb.add_child(wk, NodeRecord(type="collection", id=sid, name=sid,
                                                 attributes={"role": "scene"}, children=()))
                _scene_children(tb, sk, sid)
    return tb.finish()


# --- on-disk sharding --------------------------------------------------------


def _writable(store: object) -> WritableStore:
    if not isinstance(store, WritableStore):
        raise TypeError(f"{type(store).__name__} is not writable")
    return store


async def _write_node(
    tree: NodeTree, node_id: NodeId, depth: int, boundary: int, store: object, parent_dir: Path
) -> tuple[str, Reference]:
    """Write `node_id`'s subtree to disk; return its URL and a reference to it."""
    rec = tree.record(node_id)
    url = str(parent_dir / (rec.id or "node") / "collection.json")
    children = tree.children_ids(node_id)
    if depth >= boundary or not children:
        await write_document(store, url, tree, root_id=node_id)
    else:
        # container document: children written as their own docs, referenced here
        container = TreeBuilder(replace(rec, children=()))
        for child in children:
            child_url, child_ref = await _write_node(
                tree, child, depth + 1, boundary, store, parent_dir / (rec.id or "node")
            )
            crec = tree.record(child)
            container.add_child(ROOT, NodeRecord(type=crec.type, name=crec.name, ref=child_ref))
        await write_document(store, url, container.finish(), root_id=ROOT)
    return url, Reference(path=reference_path(url), id=rec.id)


async def write_sharded(tree: NodeTree, shard: ShardLevel, store: object, workdir: str | Path) -> str:
    """Write `tree` to `workdir` at the given sharding; return the entry URL."""
    _writable(store)
    url, _ = await _write_node(tree, ROOT, 0, _BOUNDARY_DEPTH[shard], store, Path(workdir))
    return url


# --- local dataset cache -----------------------------------------------------

DATA_ROOT = Path(__file__).parent / ".data"
_MARKER = ".benchmark.json"


def dataset_dir(shard: ShardLevel, scenes_per_well: int, data_root: Path | None = None) -> Path:
    """Cache directory for a given (shard, scale) dataset."""
    return (data_root or DATA_ROOT) / f"{shard}-n{scenes_per_well}"


def ensure_dataset(
    shard: ShardLevel,
    scenes_per_well: int,
    *,
    rebuild: bool = False,
    data_root: Path | None = None,
) -> tuple[str, list[Result]]:
    """Return the entry-document URL for the dataset, generating it if needed."""
    target_dir = dataset_dir(shard, scenes_per_well, data_root)
    marker = target_dir / _MARKER

    if rebuild and target_dir.exists():
        shutil.rmtree(target_dir)
    if not rebuild and marker.exists():
        return json.loads(marker.read_text())["entry_url"], []

    build_res, tree = measure_value("build (in-mem)", lambda: build_monolithic(scenes_per_well))

    async def _write() -> str:
        return await write_sharded(tree, shard, LocalStore(), target_dir)

    write_res, entry_url = measure_value("dataset write (disk)", lambda: asyncio.run(_write()))

    target_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(
        {"entry_url": entry_url, "shard": shard, "scenes_per_well": scenes_per_well,
         "nodes": estimate_nodes(scenes_per_well)}, indent=2))
    return entry_url, [build_res, write_res]
