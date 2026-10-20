"""Run every example, then validate every document tree it produced.

Each example writes under `examples/data/<example>/`; the entry document is the
`zarr.json` or `collection.json` at that directory's root. Every entry is
resolved and checked with `ALL_VALIDATORS`. The one tolerated finding is an
`http` node that cannot be resolved offline (`remote_collection`).

Run with: NGC_OFFLINE=1 pixi run python examples/validate_all.py
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import ngio_collections as ngc

HERE = Path(__file__).parent


def validate_entry(url: str) -> list[str]:
    view = ngc.open_resolved(url)
    findings = []
    for error in view.validate(ngc.ALL_VALIDATORS):
        node = view.find(error.node_uuid) if error.node_uuid else None
        if (
            error.validator == "external_unresolved"
            and node is not None
            and node.path is not None
            and node.path.format == "http"
        ):
            findings.append(
                f"  (tolerated) remote node {node.name!r} not resolved offline"
            )
            continue
        findings.append(f"  FAIL {error.validator} on {error.node_uuid}: {error}")
    return findings


def main() -> int:
    env = {**os.environ}
    for script in sorted(HERE.glob("*.py")):
        if script.name in (Path(__file__).name, "_ids.py"):
            continue
        cmd = f"{sys.executable} {script}"
        print(f"running {script.name}")
        result = subprocess.run(
            shlex.split(cmd), capture_output=True, encoding="utf-8", env=env
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return 1

    failed = False
    for example_dir in sorted((HERE / "data").iterdir()):
        for name in ("zarr.json", "collection.json"):
            entry = example_dir / name
            if entry.exists():
                findings = validate_entry(str(entry))
                print(f"{entry.relative_to(HERE)}: {'ok' if not findings else ''}")
                for line in findings:
                    print(line)
                failed |= any(line.startswith("  FAIL") for line in findings)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
