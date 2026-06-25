"""Builds the benchmark dataset and writes it to disk at a chosen sharding.

The dataset mirrors a realistic RFC-8 HCS collection:

    root -> 20 plates -> 240 wells/plate -> n scenes/well

and every scene holds 3 multiscale images, 5 multiscale labels and 10 tables
(18 child nodes). Node count scales linearly with ``scenes_per_well``::

    total = 4821 + 4800 * scenes_per_well * 19

so ``scenes_per_well == 11`` yields ~1.0M nodes (see ``scenes_for_target``).

Two products are derived from the same builders:

* ``build_monolithic`` returns the full, detached in-memory tree (every node
  inline). It is what gets written to disk, and the canonical source the
  in-memory operation benchmarks (walk / find / edit) run against.
* ``write_sharded`` writes that tree to disk, splitting it into one document per
  node at or above the chosen boundary (``leaf`` / ``scene`` / ``well`` /
  ``plate``), or a single document (``none``). Parent documents reference their
  children with the ``RefNode`` stubs that ``Resolver.create`` hands back,
  composed via ``add_ref`` — the documented multi-document pattern. This is the
  layout the ``open_inlined`` read benchmark resolves across.

Generated datasets are expensive, so ``ensure_dataset`` caches them under
``benchmarks/.data/<shard>-n<scenes>/`` and reuses them across runs.

Tables have no built-in node type, so a small custom family is registered here
(mirroring ``examples/custom_node_types.py``); all data still lives in the open
``attributes`` dict.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Literal

import ngio_collections as ngc

from benchmarks.harness import Result, measure_value
from ngio_collections import RefNode, Resolver

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
# well=2, scene=3, leaf (multiscale/table)=4; everything below the boundary
# stays inline.
_BOUNDARY_DEPTH: dict[ShardLevel, int] = {
    "none": 0,
    "plate": 1,
    "well": 2,
    "scene": 3,
    "leaf": 4,
}


# --- custom table family (no built-in table node) ---------------------------


class _TableType(ngc.NodeObj):
    """Marks the ``bench:table`` node type; data lives in ``attributes``."""

    __slots__ = ()
    node_type = "bench:table"


class TableNode(_TableType, ngc.Node):
    """Editable table node."""

    __slots__ = ()


class RefTableNode(_TableType, ngc.RefNode):
    """Reference stub for a table document."""

    __slots__ = ()


class InlinedTableNode(_TableType, ngc.InlinedNode):
    """Resolved (read-only) table node."""

    __slots__ = ()


def register_tables() -> None:
    """Register the table family once (idempotent across re-runs)."""
    if "bench:table" not in ngc.DEFAULT_REGISTRY:
        ngc.register_family(TableNode, RefTableNode, InlinedTableNode)


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
    """Number of documents (files) written for the given sharding.

    A node becomes its own document iff its depth is at or above the shard
    boundary; this counts every such node (root=0 .. leaf=4).
    """
    scenes = TOTAL_WELLS * scenes_per_well
    leaves = scenes * (IMAGES + LABELS + TABLES)
    per_depth = (1, PLATES, TOTAL_WELLS, scenes, leaves)  # depth 0..4
    return sum(per_depth[: _BOUNDARY_DEPTH[shard] + 1])


# --- in-memory builders (detached) ------------------------------------------


def build_scene(scene_id: str) -> ngc.CollectionNode:
    """Build one scene: 3 image + 5 label multiscales and 10 tables, inline."""
    images = tuple(
        ngc.MultiscaleNode(
            id=f"{scene_id}-img{i}", name=f"img{i}", attributes={"role": "image"}
        )
        for i in range(IMAGES)
    )
    labels = tuple(
        ngc.MultiscaleNode(
            id=f"{scene_id}-lbl{i}", name=f"lbl{i}", attributes={"role": "label"}
        )
        for i in range(LABELS)
    )
    tables = tuple(
        TableNode(id=f"{scene_id}-tbl{i}", name=f"tbl{i}", attributes={"role": "table"})
        for i in range(TABLES)
    )
    return ngc.CollectionNode(
        id=scene_id,
        name=scene_id,
        attributes={"role": "scene"},
        nodes=(*images, *labels, *tables),
    )


def build_well(well_id: str, scenes_per_well: int) -> ngc.CollectionNode:
    """Build one well containing ``scenes_per_well`` scenes."""
    scenes = tuple(build_scene(f"{well_id}-s{s}") for s in range(scenes_per_well))
    return ngc.CollectionNode(
        id=well_id, name=well_id, attributes={"role": "well"}, nodes=scenes
    )


def build_plate(plate_id: str, scenes_per_well: int) -> ngc.CollectionNode:
    """Build one plate containing its wells."""
    wells = tuple(
        build_well(f"{plate_id}-w{w}", scenes_per_well)
        for w in range(WELLS_PER_PLATE)
    )
    return ngc.CollectionNode(
        id=plate_id, name=plate_id, attributes={"role": "plate"}, nodes=wells
    )


def build_monolithic(scenes_per_well: int) -> ngc.CollectionNode:
    """Build the full, detached collection tree with every node inline."""
    plates = tuple(build_plate(f"p{p}", scenes_per_well) for p in range(PLATES))
    return ngc.CollectionNode(
        id="root", name="root", attributes={"role": "root"}, nodes=plates
    )


# --- on-disk sharding --------------------------------------------------------


async def _write_doc(
    node: ngc.CollectionNode,
    depth: int,
    boundary: int,
    resolver: Resolver,
    parent_dir: Path,
) -> tuple[str, RefNode]:
    """Write ``node`` (and its subtree) to disk, returning ``(url, stub)``.

    Above the boundary the node becomes a container document whose children are
    written first (bottom-up) and attached as ``RefNode`` stubs; at the boundary
    the whole subtree is written inline as one document.
    """
    node_dir = parent_dir / node.id
    url = str(node_dir / "collection.json")
    if depth == boundary:
        ref = await resolver.create(url, node, overwrite=True)
        return url, ref
    container: ngc.CollectionNode = node.model_copy(update={"nodes": ()})
    for child in node.nodes:
        _, child_ref = await _write_doc(child, depth + 1, boundary, resolver, node_dir)
        container = container.add_ref(parent_id=node.id, ref=child_ref)
    ref = await resolver.create(url, container, overwrite=True)
    return url, ref


async def write_sharded(
    root: ngc.CollectionNode,
    shard: ShardLevel,
    resolver: Resolver,
    workdir: str | Path,
) -> str:
    """Write ``root`` to ``workdir`` at the given sharding; return the entry URL."""
    url, _ = await _write_doc(root, 0, _BOUNDARY_DEPTH[shard], resolver, Path(workdir))
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
    """Return the entry-document URL for the dataset, generating it if needed.

    Reuses a previously generated dataset (matching ``shard`` + scale) when its
    completion marker is present. Otherwise builds the tree in memory and writes
    it to disk, returning the two setup measurements (build + disk write). On
    reuse the returned list is empty.
    """
    target_dir = dataset_dir(shard, scenes_per_well, data_root)
    marker = target_dir / _MARKER

    if rebuild and target_dir.exists():
        shutil.rmtree(target_dir)

    if not rebuild and marker.exists():
        meta = json.loads(marker.read_text())
        return meta["entry_url"], []

    register_tables()
    build_res, root = measure_value(
        "build (in-mem)", lambda: build_monolithic(scenes_per_well)
    )

    async def _write() -> str:
        resolver = Resolver(ngc.LocalStore())
        return await write_sharded(root, shard, resolver, target_dir)

    write_res, entry_url = measure_value("dataset write (disk)", lambda: asyncio.run(_write()))

    target_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "entry_url": entry_url,
                "shard": shard,
                "scenes_per_well": scenes_per_well,
                "nodes": estimate_nodes(scenes_per_well),
            },
            indent=2,
        )
    )
    return entry_url, [build_res, write_res]
