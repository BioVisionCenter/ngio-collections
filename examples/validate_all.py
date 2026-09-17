from pathlib import Path
import subprocess, shlex
import ngio_collections as ngc


def validate_collection(root_url: str) -> None:
    root_node = ngc.open(root_url)
    print(root_node)

    # (1) Run validators from `ngc`
    ngc.validate(
        root_node,
        validators=(ngc.well_under_plate, ngc.scale_matches_axes),
        raise_on_error=True,
    )

    # (2) Validate each node against JSON Schemas
    # ... (TODO)


for script in sorted(Path(__file__).parent.glob("*.py")):
    if script.name == Path(__file__).name:
        continue
    cmd = f"pixi run python examples/{script.name}"
    print(f"Now re-running {cmd=}")
    subprocess.run(shlex.split(cmd), capture_output=True, check=True)
print()

for root_url in sorted((Path(__file__).parent / "data").glob("*/*.json")):
    print(root_url)
    validate_collection(root_url.as_posix())
    print()
