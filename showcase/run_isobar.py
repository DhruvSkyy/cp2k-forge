"""Run the 1 atm density isobar with a trained model and write density(T).

For each showcase temperature, an NPT trajectory is run, equilibration is discarded,
and the density is block-averaged to give a mean and a block-statistics error bar.
Output is a TSV  (T_K  density_gcc  density_err_gcc)  consumed by density_tmd.py and
plot_tmd.py.

Default engine is ASE NPT (runnable anywhere). For the integrated/"platform" run, point
--engine cp2k at a metatomic-enabled CP2K binary (the same model, on the optimised
backend) — this is also what bench_throughput.py times for the throughput claim.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cp2k_forge.config import Config


def _density_gcc(atoms) -> float:
    import numpy as np

    amu_to_g = 1.66053906660e-24
    ang3_to_cm3 = 1.0e-24
    return (float(np.sum(atoms.get_masses())) * amu_to_g) / (
        atoms.get_volume() * ang3_to_cm3
    )


def _block_stats(values, n_blocks: int = 5):
    """Mean and block-standard-error of a time series."""
    import numpy as np

    x = np.asarray(values, dtype=float)
    if x.size < n_blocks:
        return float(x.mean()), (
            float(x.std(ddof=1) / max(1, x.size) ** 0.5) if x.size > 1 else 0.0
        )
    blocks = np.array_split(x, n_blocks)
    means = np.array([b.mean() for b in blocks])
    return float(x.mean()), float(means.std(ddof=1) / n_blocks**0.5)


def run_npt_ase(cfg, model_path: str, seed_atoms, temperature_k: float):
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
    from mace.calculators import MACECalculator

    from cp2k_forge.engines import make_npt_dyn

    atoms = seed_atoms.copy()
    atoms.calc = MACECalculator(
        model_paths=model_path, device=cfg.train.device, default_dtype="float32"
    )
    MaxwellBoltzmannDistribution(atoms, temperature_K=temperature_k)
    # The isobar is an observable-bearing run: cfg.showcase.barostat defaults to "mtk"
    # (canonical NPT) — Berendsen would suppress the very fluctuations the error bar
    # is built from.
    dyn = make_npt_dyn(
        atoms,
        cfg.showcase.timestep_fs,
        temperature_k,
        cfg.showcase.pressure_bar,
        cfg.showcase.barostat,
        tdamp_fs=cfg.explore.tdamp_fs,
        pdamp_fs=cfg.explore.pdamp_fs,
    )

    densities = []
    eq = cfg.showcase.equilibration_steps

    def sample(counter=[0]):
        counter[0] += 1
        if counter[0] > eq and counter[0] % 100 == 0:
            densities.append(_density_gcc(atoms))

    dyn.attach(sample, interval=1)
    dyn.run(cfg.showcase.steps)
    return _block_stats(densities)


def run_isobar(config_path: str, model_path: str, out_tsv: str, engine: str = "ase"):
    from cp2k_forge.seed import load_seed

    cfg = Config.from_yaml(config_path)
    seed = load_seed(cfg, verbose=True)

    if engine != "ase":
        raise NotImplementedError(
            "the in-CP2K-backend isobar is driven via the md_backend.inp template "
            "on a metatomic-enabled CP2K build; the ASE engine is the portable "
            "default here and runs anywhere with mace-torch."
        )

    lines = ["# T_K\tdensity_gcc\tdensity_err_gcc"]
    for temp in cfg.showcase.temperatures_k:
        mean, err = run_npt_ase(cfg, model_path, seed, temp)
        print(f"  T={temp:5.1f} K  rho={mean:.4f} +/- {err:.4f} g/cm^3")
        lines.append(f"{temp:.1f}\t{mean:.5f}\t{err:.5f}")

    Path(out_tsv).parent.mkdir(parents=True, exist_ok=True)
    Path(out_tsv).write_text("\n".join(lines) + "\n")
    print(f"wrote {out_tsv}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--model", required=True, help="trained .model file")
    ap.add_argument("--out", required=True, help="output isobar TSV")
    ap.add_argument("--engine", default="ase", choices=["ase", "cp2k"])
    args = ap.parse_args()
    run_isobar(args.config, args.model, args.out, args.engine)


if __name__ == "__main__":
    main()
