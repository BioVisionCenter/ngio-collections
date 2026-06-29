"""Performance benchmarks for ngio-collections.

Run as a module from the repo root::

    pixi run --environment dev python -m benchmarks                      # fast default
    pixi run --environment dev python -m benchmarks --target 1000000     # ~1M nodes

See ``benchmarks/README.md`` for the full set of knobs.
"""
