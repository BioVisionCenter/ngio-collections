"""Build a small collection in memory and write it to disk.

    root (collection)
    ├── image  (multiscale, 2 scales)
    └── labels (collection)
        └── nuclei (multiscale label, 2 scales)

Trees are built handle-rooted and fluent: `new_node(...)` seeds a detached root
(taking `children=[...]` up front) and `add(*children)` grafts further subtrees.
Every node declares a UUID `id` (`new_node` mints one when none is given; here
they are fixed so the written fixture is stable). A multiscale is a leaf: its
coordinate system and scales live in its body (`coordinate_systems`, `scales`)
in the Fall 2026 proposal shape, and references inside a body (`input` /
`output`, labels `source`) are `{type, ref}` objects. Edits return the new tree
root, so `node.find(id).set_attr(...)` round-trips into `create`.

Run with: pixi run python examples/basic_creation.py
"""

from pathlib import Path

import ngio_collections as ngc

ROOT = "0192f3a0-e000-7000-8000-000000000001"
IMAGE = "0192f3a0-e000-7000-8000-000000000002"
IMAGE_SPACE = "0192f3a0-e000-7000-8000-000000000003"
IMAGE_SCALES = (
    "0192f3a0-e000-7000-8000-000000000004",
    "0192f3a0-e000-7000-8000-000000000005",
)
LABELS = "0192f3a0-e000-7000-8000-000000000006"
NUCLEI = "0192f3a0-e000-7000-8000-000000000007"
NUCLEI_SPACE = "0192f3a0-e000-7000-8000-000000000008"
NUCLEI_SCALES = (
    "0192f3a0-e000-7000-8000-000000000009",
    "0192f3a0-e000-7000-8000-00000000000a",
)


def multiscale_body(space_id: str, scale_ids: tuple[str, ...]) -> dict:
    """The body of a multiscale: one coordinate system and one scale per level.

    Each scale's array lives at `./<level>` inside the multiscale's own group,
    and its `scale` transform maps the array onto the shared coordinate system.
    """
    return {
        "coordinate_systems": [
            {
                "id": space_id,
                "name": "physical",
                "axes": [
                    {"name": "y", "type": "space", "unit": "micrometer"},
                    {"name": "x", "type": "space", "unit": "micrometer"},
                ],
            }
        ],
        "scales": [
            {
                "id": scale_id,
                "path": {"type": "zarr", "format": "relative", "href": f"./{level}"},
                "coordinate_transformations": [
                    {
                        "type": "scale",
                        "scale": [factor, factor],
                        "input": {"type": "scale", "ref": scale_id},
                        "output": {"type": "coordinate_system", "ref": space_id},
                    }
                ],
            }
            for level, (scale_id, factor) in enumerate(zip(scale_ids, (1.0, 2.0)))
        ],
    }


def build_multiscale(
    id: str,
    name: str,
    space_id: str,
    scale_ids: tuple[str, ...],
    extra_attr: ngc.AnyAttribute | None = None,
) -> ngc.Node:
    node = ngc.new_node(
        "multiscale", id=id, name=name, attributes=multiscale_body(space_id, scale_ids)
    )
    if extra_attr is not None:
        node = node.set_attr(extra_attr)
    return node


def build_collection() -> ngc.Node:
    """The in-memory tree, detached until `create` writes it."""
    # The labels multiscale records, via a typed attribute, the image it segments.
    nuclei = build_multiscale(
        NUCLEI,
        "nuclei",
        NUCLEI_SPACE,
        NUCLEI_SCALES,
        extra_attr=ngc.LabelsAttribute(
            label_attributes=[ngc.LabelObj(label_value=1, color=[255, 0, 0, 255])],
            source=[ngc.ReferenceObj(type="multiscale", ref=IMAGE)],
        ),
    )
    labels = ngc.new_node("collection", id=LABELS, name="labels").add(nuclei)
    return (
        ngc.new_node("collection", id=ROOT, name="root")
        .add(build_multiscale(IMAGE, "image", IMAGE_SPACE, IMAGE_SCALES))
        .add(labels)
    )


def main() -> None:
    base_path = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base_path / "collection.json")
    ngc.create(url, build_collection(), overwrite=True)

    print(f"wrote {url}\n")
    print(Path(url).read_text())


if __name__ == "__main__":
    main()
