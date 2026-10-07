"""Locate the temperature of maximum density (TMD) from a density isobar.

Input: a TSV with columns  T_K  density_gcc  density_err_gcc  (one row per temperature,
written by run_isobar.py). Output: the fitted TMD and maximum density, with an
uncertainty from a Monte-Carlo resample over the per-point error bars.

A low-order polynomial is fitted to the points within a window around the densest
sample; the maximum of the fit is the TMD. This matches how the isobar is analysed in
the water-MLP literature (the curvature near the maximum is gentle, so a local quadratic
is appropriate).
"""

from __future__ import annotations

import argparse
from pathlib import Path


def read_isobar(path: str | Path):
    import numpy as np

    rows = []
    for ln in Path(path).read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        t, d, e = ln.split()[:3]
        rows.append((float(t), float(d), float(e)))
    rows.sort()
    arr = np.asarray(rows, dtype=float)
    return arr[:, 0], arr[:, 1], arr[:, 2]


def _fit_tmd(temps, densities, window: float = 40.0):
    """Quadratic fit in a window around the densest point; return (tmd, rho_max)."""
    import numpy as np

    i_max = int(np.argmax(densities))
    t0 = temps[i_max]
    mask = np.abs(temps - t0) <= window
    if mask.sum() < 3:  # widen if too few points in the window
        mask = np.ones_like(temps, dtype=bool)
    a, b, c = np.polyfit(temps[mask], densities[mask], 2)
    if a >= 0:  # no interior maximum -> report the sample peak
        return float(t0), float(densities[i_max])
    tmd = -b / (2.0 * a)
    rho_max = a * tmd * tmd + b * tmd + c
    return float(tmd), float(rho_max)


def locate_tmd(
    path: str | Path, window: float = 40.0, n_resamples: int = 2000, seed: int = 0
):
    """Return a dict with the TMD, max density, and their MC uncertainties."""
    import numpy as np

    temps, dens, errs = read_isobar(path)
    tmd, rho_max = _fit_tmd(temps, dens, window)

    rng = np.random.default_rng(seed)
    tmds = []
    for _ in range(n_resamples):
        noisy = dens + rng.normal(0.0, np.maximum(errs, 1e-9))
        try:
            t, _r = _fit_tmd(temps, noisy, window)
            tmds.append(t)
        except Exception:
            continue
    tmds = np.asarray(tmds)
    return {
        "tmd_k": tmd,
        "tmd_k_std": float(tmds.std()) if tmds.size else float("nan"),
        "rho_max_gcc": rho_max,
        "n_points": int(len(temps)),
        "experiment_tmd_k": 277.13,
        "revpbe_d3_literature_tmd_k": "~299-308",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("isobar_tsv", help="TSV: T_K density_gcc density_err_gcc")
    ap.add_argument("--window", type=float, default=40.0)
    args = ap.parse_args()
    res = locate_tmd(args.isobar_tsv, window=args.window)
    print(f"TMD            : {res['tmd_k']:.1f} +/- {res['tmd_k_std']:.1f} K")
    print(f"max density    : {res['rho_max_gcc']:.4f} g/cm^3")
    print(f"experiment     : {res['experiment_tmd_k']} K")
    print(f"revPBE-D3 lit. : {res['revpbe_d3_literature_tmd_k']} K")


if __name__ == "__main__":
    main()
