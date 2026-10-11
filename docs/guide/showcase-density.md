# Showcase and density

The `showcase/` scripts turn an accepted model into density observables: a 1 atm isobar
and its analysis. They are repo scripts (not part of the installed package) because they
are campaign deliverables, not loop stages.

| Script | What it does |
| --- | --- |
| `showcase/run_isobar.py` | one NPT trajectory per showcase temperature (ASE + MACECalculator, canonical MTK barostat), equilibration discarded, density block-averaged → TSV of `T, rho, rho_err` |
| `showcase/density_tmd.py` | fits the isobar and reports the density-maximum analysis |
| `showcase/plot_tmd.py` | plots the isobar with block-statistics error bars (`--mark-expt` opts into an experimental overlay; off by default — see below) |
| `showcase/bench_throughput.py` | times the compact model vs the foundation model in MD (and parses an in-CP2K-backend log when you have a metatomic-enabled build) |

```bash
python showcase/run_isobar.py --config configs/water.yaml \
  --model runs/water/pass6/model/water_pass6.model --out runs/water/isobar.tsv
python showcase/plot_tmd.py --isobar runs/water/isobar.tsv --out isobar.png
```

The isobar is an observable-bearing run: `showcase.barostat` defaults to `mtk`
(canonical NPT), because Berendsen suppresses the very fluctuations the error bar is
built from. The per-pass NPT **density probe** inside the loop
(`validate.density_probe_steps`) is the same physics at smoke length — 2000 steps is a
plumbing value; a campaign-grade density needs ~100 ps for a ~0.006 g/cc standard error.

## What the density probe is for — and what it is not

The probe tests whether the loop is learning a **pressure-sensitive observable**, and
feeds the convergence/promotion machinery (`loop.density_tol_gcc`,
`loop.promote_density_window_gcc`). It is **not a certified density prediction**, and
the accompanying report is deliberately strict about what may be claimed. If you build
campaign conclusions on these tools, inherit that discipline:

!!! warning "Claim constraints (from the report's audited density campaign)"
    - **Quote the density, not a TMD.** The report's semi-local probe campaign gives
      ρ(300 K) = **0.933 g/cm³** (simple 3-replica mean, replica spread 0.009) — in line
      with the published multi-code revPBE-D3 consensus. Its temperature-of-maximum-density
      fit is **UNRESOLVED (sampling-limited)**: no interior maximum is certified, and the
      only supportable sentence is *"the isobar shows a broad density-maximum region
      below ~290 K"*. The fit record ships with these docs —
      [`tmd.json`](../assets/data/density/tmd.json) — and its `verdict` field is the
      authority.
    - **Never score the density against experiment.** A classical-nuclei simulation at a
      given functional should *not* reproduce experiment; apparent agreement is error
      cancellation. The only legitimate reference band is the same functional's own DFT
      equation of state, which is exactly what
      [the isobar figure](../case-studies/water.md#density) draws. This is why
      `plot_tmd.py` hides its experimental overlay behind `--mark-expt` and the
      validation anchors (`validate.density_ref_gcc`) are reported, never gated.
    - **Forces do not pin the density.** See the
      [physics caveat](../about/method.md#a-physics-caveat-worth-stating): training on
      energies and forces at fixed cells leaves the pressure — and so the equilibrium
      density — underdetermined. Tight density targets need stress training
      (`train.stress_weight > 0`), which the **hybrid** level cannot currently provide
      (its labels carry no stress).

## Throughput

`bench_throughput.py` measures the deployment speed story: on the case-study systems the
accepted compact model runs MD about **2.6× faster than the foundation sampler** on the
same hardware (53 vs 137 ms/step on one A100 for the 193-atom cell) — numbers and raw
data in [Cost and data efficiency](../case-studies/cost.md). The optional in-CP2K
backend path (`generator.engine: cp2k-backend`) needs a metatomic-enabled CP2K build and
raises an actionable error without one.
