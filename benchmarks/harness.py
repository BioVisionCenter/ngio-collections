"""Tiny measurement harness: average wall time + peak memory, no dependencies.

Timing and memory are measured in separate passes on purpose: ``tracemalloc``
roughly doubles allocation cost, so timing runs without it for clean numbers and
peak memory is captured in one extra, untimed run. All measurement uses the
standard library (``time.perf_counter`` + ``tracemalloc``).
"""

from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass
class Result:
    """One operation's measured cost."""

    name: str
    avg_s: float
    min_s: float
    repeats: int
    peak_bytes: int


def _peak_of(fn: Callable[[], object]) -> int:
    """Run ``fn`` once and return the peak traced memory (bytes) of that run."""
    tracemalloc.start()
    try:
        fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def measure(name: str, fn: Callable[[], object], repeats: int) -> Result:
    """Time ``fn`` over ``repeats`` runs, then measure its peak memory once."""
    times: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    peak = _peak_of(fn)
    return Result(name, sum(times) / len(times), min(times), repeats, peak)


def measure_value(name: str, fn: Callable[[], T]) -> tuple[Result, T]:
    """Run ``fn`` once, capturing time and peak memory, returning its value too.

    Used for setup steps (building / writing the dataset) where the produced
    value is needed and a second run would be wasteful.
    """
    tracemalloc.start()
    start = time.perf_counter()
    value = fn()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return Result(name, elapsed, elapsed, 1, peak), value


# --- formatting --------------------------------------------------------------


def human_time(seconds: float) -> str:
    """Format a duration with a sensible unit."""
    if seconds < 1e-3:
        return f"{seconds * 1e6:.1f} us"
    if seconds < 1.0:
        return f"{seconds * 1e3:.2f} ms"
    return f"{seconds:.3f} s"


def human_bytes(n: int) -> str:
    """Format a byte count with a binary unit."""
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GiB"


def format_table(results: list[Result]) -> str:
    """Render results as an aligned text table."""
    headers = ("operation", "avg", "min", "peak mem", "runs")
    rows = [
        (
            r.name,
            human_time(r.avg_s),
            human_time(r.min_s),
            human_bytes(r.peak_bytes),
            str(r.repeats),
        )
        for r in results
    ]
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))
    ]

    def fmt(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    sep = "  ".join("-" * w for w in widths)
    lines = [fmt(headers), sep, *(fmt(row) for row in rows)]
    return "\n".join(lines)
