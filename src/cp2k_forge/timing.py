"""Per-stage wall/CPU timing for the pipeline loop.

Each pass spends time in four very different places: MACE MD (generate), diversity
selection (subsample), DFT single points (label) and training (train). Which one
dominates flips as the campaign scales (DFT is cheap per node but there are many frames;
long NPT MACE-MD becomes the bottleneck once labelling is parallel). This records both
wall time and CPU time (including child processes, so CP2K's cost is captured) so the
crossover is visible in the manifest and the SLURM log rather than guessed.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager


@contextmanager
def stage_timer(name: str, sink: dict):
    """Record wall and CPU seconds for a block into ``sink[name]``.

    CPU time sums user+system for this process AND its children, so a stage that shells
    out to CP2K (the label stage) attributes that work correctly.
    """
    t0 = time.perf_counter()
    c0 = os.times()
    try:
        yield
    finally:
        wall = time.perf_counter() - t0
        c1 = os.times()
        cpu = (
            (c1.user - c0.user)
            + (c1.system - c0.system)
            + (c1.children_user - c0.children_user)
            + (c1.children_system - c0.children_system)
        )
        sink[name] = {"wall_s": round(wall, 2), "cpu_s": round(cpu, 2)}


def format_timings(timings: dict) -> str:
    """One-line human summary, e.g. 'generate 5400s  label 9600s  train 800s'."""
    order = ("generate", "subsample", "label", "train", "validate")
    keys = [k for k in order if k in timings] + [k for k in timings if k not in order]
    return "  ".join(f"{k} {timings[k]['wall_s']:.0f}s" for k in keys)
