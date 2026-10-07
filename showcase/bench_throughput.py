"""Throughput comparison — the pipeline's headline deliverable.

Times MD throughput three ways on the same box and hardware to isolate the two speedups:

  1. compact bespoke model on the optimised in-CP2K backend            (us; the moat)
  2. the SAME compact model in a generic engine (ASE + mace-torch)     -> backend speedup
  3. the MACE-MP-0 foundation model in a generic engine                -> model-compactness speedup

Result: "domain-specific small model + optimised CP2K backend runs N x faster than the
foundation model in a standard engine." (1) requires a metatomic-enabled CP2K binary; (2)
and (3) run anywhere. Output is a JSON report of steps/s, ns/day, and ms/step.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _throughput(n_steps: int, wall_s: float, timestep_fs: float) -> dict:
    return {
        "steps_per_s": n_steps / wall_s,
        "ms_per_step": 1000.0 * wall_s / n_steps,
        "ns_per_day": (n_steps * timestep_fs * 1e-6) / wall_s * 86400.0,
        "n_steps": n_steps,
        "wall_s": wall_s,
    }


def bench_ase(calc, atoms, n_steps: int, timestep_fs: float, warmup: int = 10) -> dict:
    from ase import units as ase_units
    from ase.md.verlet import VelocityVerlet
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    work = atoms.copy()
    work.calc = calc
    MaxwellBoltzmannDistribution(work, temperature_K=300)
    dyn = VelocityVerlet(work, timestep_fs * ase_units.fs)
    dyn.run(warmup)  # exclude graph build / JIT from the timing
    t0 = time.perf_counter()
    dyn.run(n_steps)
    return _throughput(n_steps, time.perf_counter() - t0, timestep_fs)


def bench_compact_ase(
    model_path: str, atoms, n_steps: int, timestep_fs: float, device: str = "cpu"
) -> dict:
    from mace.calculators import MACECalculator

    calc = MACECalculator(
        model_paths=model_path, device=device, default_dtype="float64"
    )
    return bench_ase(calc, atoms, n_steps, timestep_fs)


def bench_foundation_ase(
    model: str,
    atoms,
    n_steps: int,
    timestep_fs: float,
    device: str = "cpu",
    dispersion: bool = True,
) -> dict:
    from mace.calculators import mace_mp
    from cp2k_forge.engines import _MP_ALIASES

    calc = mace_mp(
        model=_MP_ALIASES.get(model, model),
        dispersion=dispersion,
        device=device,
        default_dtype="float64",
    )
    return bench_ase(calc, atoms, n_steps, timestep_fs)


def bench_cp2k_metatomic(
    out_path: str | Path, n_steps: int, timestep_fs: float
) -> dict | None:
    """Parse MD timing from a completed CP2K &METATOMIC MD log.

    Run the MD on a metatomic-enabled CP2K build (via the md_backend.inp
    template), then point this at the resulting .out. Returns None if the timing line
    is absent. This path requires that build; the two ASE benches above run anywhere.
    """
    text = Path(out_path).read_text()
    # CP2K prints "MD| Time per MD step [s] = <value>" in the MD banner each step.
    per_step = None
    for ln in text.splitlines():
        if "Time per MD step" in ln:
            try:
                per_step = float(ln.split("=")[-1].split()[0])
            except (ValueError, IndexError):
                continue
    if per_step is None:
        return None
    return _throughput(n_steps, per_step * n_steps, timestep_fs)


def run(
    config_path: str,
    model_path: str,
    out_json: str,
    n_steps: int = 200,
    cp2k_out: str | None = None,
) -> dict:
    from ase.io import read
    from cp2k_forge.config import Config

    cfg = Config.from_yaml(config_path)
    seed_path = cfg.resolve_path(cfg.system.seed_xyz)
    atoms = read(str(seed_path), index=0)
    atoms.set_cell(cfg.system.cell_abc)
    atoms.set_pbc(True)
    dt = cfg.showcase.timestep_fs

    report = {
        "compact_ase": bench_compact_ase(
            model_path, atoms, n_steps, dt, cfg.train.device
        ),
        "foundation_ase": bench_foundation_ase(
            cfg.generator.model,
            atoms,
            n_steps,
            dt,
            cfg.generator.device,
            cfg.generator.dispersion,
        ),
    }
    if cp2k_out:
        cp = bench_cp2k_metatomic(cp2k_out, n_steps, dt)
        if cp:
            report["compact_cp2k_backend"] = cp

    # Headline ratios (ns/day): backend speedup and total speedup vs the foundation model.
    f = report["foundation_ase"]["ns_per_day"]
    report["model_compactness_speedup"] = report["compact_ase"]["ns_per_day"] / f
    if "compact_cp2k_backend" in report:
        report["backend_speedup_over_ase"] = (
            report["compact_cp2k_backend"]["ns_per_day"]
            / report["compact_ase"]["ns_per_day"]
        )
        report["total_speedup_vs_foundation"] = (
            report["compact_cp2k_backend"]["ns_per_day"] / f
        )

    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--model", required=True, help="compact .model file")
    ap.add_argument("--out", required=True, help="output JSON report")
    ap.add_argument("--n-steps", type=int, default=200)
    ap.add_argument(
        "--cp2k-out",
        default=None,
        help="optional CP2K &METATOMIC MD .out for the in-backend timing",
    )
    args = ap.parse_args()
    run(args.config, args.model, args.out, args.n_steps, args.cp2k_out)


if __name__ == "__main__":
    main()
