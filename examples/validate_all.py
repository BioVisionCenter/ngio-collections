from pathlib import Path
import subprocess, shlex
import ngio_collections as ngc


VALIDATORS = (ngc.well_under_plate, ngc.scale_matches_axes)


def validate_collection(root_url: str) -> None:
    root_node = ngc.open(root_url)
    print(root_node)
    # Relational validation
    ngc.validate(root_node, validators=VALIDATORS, raise_on_error=True)
    # Per-object validation
    # TODO


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
