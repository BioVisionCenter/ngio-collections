"""Run every example, then validate every document tree it produced.

Each example writes under `examples/data/<example>/`; the entry document is the
`zarr.json` or `collection.json` at that directory's root. Every entry is
resolved and checked with `ALL_VALIDATORS`. The one tolerated finding is an
`http` node that cannot be resolved offline (`remote_collection`).

When `jsonschema` is installed, every node and trait of an example extension
type (see `_extensions.py`) is also checked against its schema in `schemas/`,
in every document under the example's directory.

Run with: NGC_OFFLINE=1 pixi run python examples/validate_all.py
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import ngio_collections as ngc
from _extensions import SCHEMAS_DIR, schema_file

HERE = Path(__file__).parent

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - the schema step is optional
    Draft202012Validator = None


def _ome_root(document: dict) -> dict | None:
    """The `ome` object of a `zarr.json` or standalone JSON document, if any."""
    ome = document.get("attributes", {}).get("ome") or document.get("ome")
    return ome if isinstance(ome, dict) else None


def _walk_nodes(node: dict):
    yield node
    for child in node.get("nodes", ()):
        yield from _walk_nodes(child)


def _schema_errors(instance: dict, type_uri: str, where: str) -> list[str]:
    path = schema_file(type_uri)
    if path is None or Draft202012Validator is None:
        return []
    if not path.exists():
        return [
            f"  FAIL schema {path.relative_to(HERE)} missing for {type_uri} ({where})"
        ]
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return [
        f"  FAIL schema {path.name} on {where}: {error.message}"
        for error in validator.iter_errors(instance)
    ]


def validate_schemas(example_dir: Path) -> list[str]:
    """Check every example-extension node / trait in `example_dir` against its schema."""
    findings: list[str] = []
    for file in sorted(example_dir.rglob("*.json")):
        root = _ome_root(json.loads(file.read_text()))
        if root is None:
            continue
        where = str(file.relative_to(HERE))
        for node in _walk_nodes(root):
            findings += _schema_errors(node, node.get("type", ""), where)
            for trait in node.get("traits", ()):
                findings += _schema_errors(trait, trait.get("type", ""), where)
    return findings


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
        if script.name == Path(__file__).name or script.name.startswith("_"):
            continue  # helpers (`_ids.py`, `_extensions.py`) are not examples
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
        findings = validate_schemas(example_dir)
        for line in findings:
            print(line)
        failed |= bool(findings)
    if Draft202012Validator is None:
        print(f"(jsonschema not installed: {SCHEMAS_DIR.name}/ not checked)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
