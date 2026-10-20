"""Builds the benchmark dataset and writes it to disk at a chosen sharding.

The dataset mirrors a realistic RFC-8 revision-1 HCS collection:

    root -> 20 plates (plate trait) -> 240 wells/plate (well trait) -> n scenes/well

and every scene holds 1 image multiscale, 1 label multiscale (labels trait
pointing at the image) and 16 table nodes of an extension type, so each scene
is 19 declared nodes (scene + 18 children). Node count scales linearly with
``scenes_per_well``::

    total = 4821 + 4800 * scenes_per_well * 19

so ``scenes_per_well == 11`` yields ~1.0M nodes (see ``scenes_for_target``).
Scales and coordinate systems are declarations inside a multiscale, not nodes.

Under the revision a multiscale is always its own document, so every image and
label is written as a ``zarr.json`` of its own regardless of sharding; the
``--shard`` level only decides the *collection* document boundaries (``scene`` /
``well`` / ``plate`` / ``none``). Tables are embedded in their scene's document.
Ids are UUIDv5 of a readable key (``p3-w12-s0-img``), so datasets are
deterministic. Datasets are cached under ``benchmarks/.data/<shard>-n<scenes>/``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Literal

import ngio_collections as ngc
from benchmarks.harness import Result, measure_value
from ngio_collections.graph import ROOT, NodeRecord, TreeBuilder
from ngio_collections.io.store import AsyncWritableStore, LocalStore
from ngio_collections.models._paths import DocPath
from ngio_collections.resolve import write_document

# --- fixed layout ------------------------------------------------------------

PLATES = 20
WELLS_PER_PLATE = 240
TOTAL_WELLS = PLATES * WELLS_PER_PLATE  # 4800
IMAGES = 1
LABELS = 1
TABLES = 16
NODES_PER_SCENE = 1 + IMAGES + LABELS + TABLES  # 19 (scene node + 18 children)
FIXED_NODES = 1 + PLATES + TOTAL_WELLS  # 4821 (root + plates + wells)
SCALE_LEVELS = 3

TABLE_TYPE = "https://ngio.example/bench/table"
BENCH_EXTENSION = ngc.ExtensionManifestEntry(
    id="https://ngio.example/bench/", version="1.0"
)
NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

ShardLevel = Literal["scene", "well", "plate", "none"]

# Depth at (and above) which a *collection* becomes its own document.
# root=0, plate=1, well=2, scene=3.
_BOUNDARY_DEPTH: dict[ShardLevel, int] = {"none": 0, "plate": 1, "well": 2, "scene": 3}


def uid(key: str) -> str:
    """Deterministic UUID for a readable key."""
    return str(uuid.uuid5(NAMESPACE, key))


# --- node-count helpers ------------------------------------------------------


def estimate_nodes(scenes_per_well: int) -> int:
    """Total declared-node count for ``scenes_per_well`` scenes per well."""
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
    """Number of documents written: multiscales always, collections per shard."""
    scenes = TOTAL_WELLS * scenes_per_well
    per_depth = (1, PLATES, TOTAL_WELLS, scenes)  # collection docs at depth 0..3
    collections = sum(per_depth[: _BOUNDARY_DEPTH[shard] + 1])
    return collections + scenes * (IMAGES + LABELS)


# --- document builders -------------------------------------------------------


def _multiscale_record(
    key: str, name: str, *, labels_of: str | None = None
) -> NodeRecord:
    """The root record of one image document (3 scales, 1 coordinate system)."""
    ms_id, cs_id = uid(key), uid(key + "#cs")
    scales = []
    for level in range(SCALE_LEVELS):
        sid = uid(f"{key}#s{level}")
        scales.append(
            {
                "type": "scale",
                "id": sid,
                "path": {"type": "zarr", "format": "relative", "href": f"./s{level}"},
                "coordinate_transformations": [
                    {
                        "type": "scale",
                        "scale": [2.0**level, 2.0**level],
                        "input": {"type": "scale", "ref": sid},
                        "output": {"type": "coordinate_system", "ref": cs_id},
                    }
                ],
            }
        )
    fields = {
        "coordinate_systems": [
            {
                "type": "coordinate_system",
                "id": cs_id,
                "axes": [
                    {"name": "y", "type": "space"},
                    {"name": "x", "type": "space"},
                ],
            }
        ],
        "scales": scales,
    }
    traits = {}
    if labels_of is not None:
        traits["labels"] = {
            "type": "labels",
            "source": [
                {
                    "type": "multiscale",
                    "ref": uid(labels_of),
                    "path": {"type": "zarr", "format": "relative", "href": "../img"},
                }
            ],
        }
    return NodeRecord(
        type="multiscale", id=ms_id, name=name, traits=traits, fields=fields
    )


def _entry(record: NodeRecord, href: str) -> NodeRecord:
    """The declaring entry a parent document stores for an external node."""
    return NodeRecord(
        type=record.type,
        id=record.id,
        name=record.name,
        path=DocPath(type="zarr", format="relative", href=href),
    )


def _href(target: Path, doc_dir: Path) -> str:
    """The relative href from the document in `doc_dir` to `target`."""
    return "./" + target.relative_to(doc_dir).as_posix()


class _Writer:
    """Generates and writes the dataset document by document.

    `doc_dir` is always the directory of the document currently being filled,
    so every entry href is relative to that document, whatever the sharding.
    """

    def __init__(
        self, store: AsyncWritableStore, shard: ShardLevel, scenes: int
    ) -> None:
        self.store = store
        self.boundary = _BOUNDARY_DEPTH[shard]
        self.scenes = scenes
        self.documents = 0

    async def _put(self, url: str, builder: TreeBuilder) -> None:
        await write_document(
            self.store,
            url,
            builder.finish(),
            extension_manifest=[BENCH_EXTENSION.to_dict()],
        )
        self.documents += 1

    async def scene_children(
        self,
        tb: TreeBuilder,
        parent_key,
        scene_key: str,
        scene_dir: Path,
        doc_dir: Path,
    ) -> None:
        """Write the scene's images as documents; add their entries and the tables."""
        img = _multiscale_record(f"{scene_key}-img", "img")
        await self._put(str(scene_dir / "img" / "zarr.json"), TreeBuilder(img))
        tb.add_child(parent_key, _entry(img, _href(scene_dir / "img", doc_dir)))
        lbl = _multiscale_record(
            f"{scene_key}-lbl", "lbl", labels_of=f"{scene_key}-img"
        )
        await self._put(str(scene_dir / "lbl" / "zarr.json"), TreeBuilder(lbl))
        tb.add_child(parent_key, _entry(lbl, _href(scene_dir / "lbl", doc_dir)))
        for i in range(TABLES):
            tb.add_child(
                parent_key,
                NodeRecord(
                    type=TABLE_TYPE,
                    id=uid(f"{scene_key}-tbl{i}"),
                    name=f"tbl{i}",
                    fields={"rows": i},
                ),
            )

    async def write_level(
        self,
        tb: TreeBuilder,
        parent_key,
        depth: int,
        key: str,
        name: str,
        directory: Path,
        doc_dir: Path,
        traits: dict,
    ) -> None:
        """Add the collection `key` under `parent_key`, embedded or as its own document."""
        record = NodeRecord(
            type="collection", id=uid(key), name=name, traits=traits, children=()
        )
        if depth >= self.boundary and depth > 0:
            own = TreeBuilder(record)
            await self.fill(own, ROOT, depth, key, directory, directory)
            await self._put(str(directory / "zarr.json"), own)
            tb.add_child(parent_key, _entry(record, _href(directory, doc_dir)))
        else:
            child_key = tb.add_child(parent_key, record)
            await self.fill(tb, child_key, depth, key, directory, doc_dir)

    async def fill(
        self,
        tb: TreeBuilder,
        key,
        depth: int,
        name_key: str,
        directory: Path,
        doc_dir: Path,
    ) -> None:
        """Populate the collection at `key` (depth 0..3) with its children."""
        if depth == 0:
            plate = {
                "plate": {
                    "type": "plate",
                    "rows": [{"name": "A"}],
                    "columns": [{"name": "1"}],
                }
            }
            for p in range(PLATES):
                await self.write_level(
                    tb, key, 1, f"p{p}", f"p{p}", directory / f"p{p}", doc_dir, plate
                )
        elif depth == 1:
            well = {"well": {"type": "well", "row_index": 0, "column_index": 0}}
            for w in range(WELLS_PER_PLATE):
                await self.write_level(
                    tb,
                    key,
                    2,
                    f"{name_key}-w{w}",
                    f"w{w}",
                    directory / f"w{w}",
                    doc_dir,
                    well,
                )
        elif depth == 2:
            for s in range(self.scenes):
                await self.write_level(
                    tb,
                    key,
                    3,
                    f"{name_key}-s{s}",
                    f"s{s}",
                    directory / f"s{s}",
                    doc_dir,
                    {},
                )
        else:
            await self.scene_children(tb, key, name_key, directory, doc_dir)


async def write_dataset(
    shard: ShardLevel,
    scenes_per_well: int,
    store: AsyncWritableStore,
    workdir: str | Path,
) -> tuple[str, int]:
    """Generate and write the dataset; return the entry URL and document count."""
    root_dir = Path(workdir)
    writer = _Writer(store, shard, scenes_per_well)
    root = TreeBuilder(
        NodeRecord(type="collection", id=uid("root"), name="root", children=())
    )
    await writer.fill(root, ROOT, 0, "root", root_dir, root_dir)
    url = str(root_dir / "zarr.json")
    await writer._put(url, root)
    return url, writer.documents


# --- local dataset cache -----------------------------------------------------

DATA_ROOT = Path(__file__).parent / ".data"
_MARKER = ".benchmark.json"


def dataset_dir(
    shard: ShardLevel, scenes_per_well: int, data_root: Path | None = None
) -> Path:
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

    write_res, (entry_url, documents) = measure_value(
        "dataset write (disk)",
        lambda: asyncio.run(
            write_dataset(shard, scenes_per_well, LocalStore(), target_dir)
        ),
    )
    marker.write_text(
        json.dumps(
            {
                "entry_url": entry_url,
                "shard": shard,
                "scenes_per_well": scenes_per_well,
                "nodes": estimate_nodes(scenes_per_well),
                "documents": documents,
            },
            indent=2,
        )
    )
    return entry_url, [write_res]
