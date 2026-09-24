import json
import sys
from pathlib import Path
import subprocess, shlex
import ngio_collections as ngc
from ngff_rfc8.validate import validate_collection


def _validate_collection(root_url: str) -> None:
    root_node = ngc.open(root_url)
    print(root_node)

    # (1) Run validators from `ngc`
    ngc.validate(
        root_node,
        validators=(ngc.well_under_plate, ngc.scale_matches_axes),
        raise_on_error=True,
    )

    # (2) Validate each node against JSON Schemas
    validate_collection(json.loads(Path(root_url).read_text()))


for script in sorted(Path(__file__).parent.glob("*.py")):
    if script.name == Path(__file__).name:
        continue
    cmd = f"pixi run python examples/{script.name}"
    print(f"Now re-running {cmd=}")
    res = subprocess.run(
        shlex.split(cmd),
        capture_output=True,
        encoding="utf-8",
    )
    if not res.returncode == 0:
        print(f"Running {cmd=} failed.")
        print(res.stderr)
        sys.exit()
print()

for root_url in sorted((Path(__file__).parent / "data").glob("*/*.json")):
    print(root_url)
    _validate_collection(root_url.as_posix())
    print()
