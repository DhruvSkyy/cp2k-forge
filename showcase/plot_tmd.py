"""Plot the density isobar with its fitted temperature of maximum density.

Paper style: serif (Computer Modern), dashed grid, density on the y-axis in g/cm^3
(never inverted). Marks the fitted TMD; the experimental 277 K line is drawn only
with --mark-expt, because a classical-nuclei simulation at a given functional should
be read against that functional's own reference, not against experiment.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import density_tmd


def _paper_style(ax):
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["CMU Serif", "Computer Modern Roman", "DejaVu Serif"],
            "mathtext.fontset": "cm",
            "axes.linewidth": 0.8,
        }
    )
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)


def plot(isobar_tsv: str, out_path: str, window: float = 40.0, mark_expt: bool = False):
    import matplotlib.pyplot as plt
    import numpy as np

    temps, dens, errs = density_tmd.read_isobar(isobar_tsv)
    res = density_tmd.locate_tmd(isobar_tsv, window=window)

    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    _paper_style(ax)
    ax.errorbar(
        temps,
        dens,
        yerr=errs,
        fmt="o",
        ms=4,
        capsize=2.5,
        color="#1f3b66",
        label="this model",
    )

    # Smooth quadratic through the windowed points for the eye.
    i_max = int(np.argmax(dens))
    mask = np.abs(temps - temps[i_max]) <= window
    if mask.sum() >= 3:
        a, b, c = np.polyfit(temps[mask], dens[mask], 2)
        xs = np.linspace(temps[mask].min(), temps[mask].max(), 200)
        ax.plot(xs, a * xs * xs + b * xs + c, "-", color="#1f3b66", lw=1.2, alpha=0.8)

    tmd = res["tmd_k"]
    ax.axvline(tmd, ls=":", color="#b22222", lw=1.2, label=f"TMD = {tmd:.0f} K")
    if mark_expt:
        ax.axvline(
            res["experiment_tmd_k"],
            ls="--",
            color="grey",
            lw=1.0,
            label=f"experiment = {res['experiment_tmd_k']:.0f} K",
        )

    ax.set_xlabel("temperature (K)")
    ax.set_ylabel(r"density (g\,cm$^{-3}$)")
    ax.legend(frameon=False, fontsize=8, loc="best")
    fig.tight_layout()

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300)
    fig.savefig(str(Path(out_path).with_suffix(".pdf")))
    print(f"wrote {out_path} (TMD {tmd:.1f} +/- {res['tmd_k_std']:.1f} K)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("isobar_tsv")
    ap.add_argument("--out", default="runs/water/tmd.png")
    ap.add_argument("--window", type=float, default=40.0)
    ap.add_argument(
        "--mark-expt",
        action="store_true",
        help="also draw the experimental 277 K line (off by default; a classical-"
        "nuclei model is read against its functional's reference, not experiment)",
    )
    args = ap.parse_args()
    plot(args.isobar_tsv, args.out, args.window, mark_expt=args.mark_expt)


if __name__ == "__main__":
    main()
