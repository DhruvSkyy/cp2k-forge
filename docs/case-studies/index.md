# Summary

These pages document the two validation campaigns from the accompanying MPhil report
(*Machine-Learned Interatomic Potentials in CP2K*, University of Cambridge, 2026,
Section 9.3), with the report's figures and the raw data files vendored into this repository
([provenance manifest](../assets/README.md), CC BY 4.0).

Both campaigns ran **the same code and promotion logic**, differing only in
system-specific thresholds and sampling settings, and both were labelled at hybrid
**revPBE0-D3** (ADMM, truncated Coulomb; the level now shipped as
`configs/water_hybrid.yaml` via [`dft.mode: hybrid`](../guide/hybrid-dft.md)). In both,
the campaign stopped by a **convergence rule fixed before use**, not by the available
compute budget: gates, validation sets, thresholds and the bootstrap seed were fixed
before use.

```{figure} ../assets/figures/fig_systems.png
:alt: Bulk water and fluoride-in-water simulation cells

Bulk water (64 H₂O, 192 atoms) and fluoride in water (one F⁻ in 64 H₂O, 193 atoms) at a common scale (thesis Fig. 9.3).
```

**Water** offers a neutral hydrogen-bond network with a strong published reference: the
committee potential trained on 814 structures selected from a 300 ps parent ab initio
trajectory. **Fluoride** is the stringent test: one charged atom in 193 controls the F-O
and F-H solvation-shell structure yet contributes little to aggregate force scores.

## How to read these numbers

:::{admonition} Scope and claim discipline
:class: note

- The comparison with the committee is **intentionally scoped**: the published
  models span broader aqueous conditions; the relevant target is the shared ambient
  regime, not universal transferability.
- **Committee route costs are extrapolations** from this work's per-single-point
  cost, not measurements of the original work.
- The default selector in these campaigns was **random decorrelated frames** (FPS/uncertainty selectors are drop-in options, *not benchmarked* at matched budget.
- Each system is **one campaign**: the pass sequence cannot isolate sampler, label
  count and retraining as separate variables.
- What a forged model *enables* in CP2K (mixed DFT/MLP, QM/MM, path integrals,
  enhanced sampling) is **enabled, not measured**: no such production run is
  claimed.
- Density and TMD claims follow the audited language described in
  [Density probe](../guide/showcase-density.md).
:::

| Page | What it covers |
| --- | --- |
| [Bulk liquid water](water.md) | the 89-label ambient campaign: learning curve, head-to-head vs the 814-label committee, RDFs vs experiment, the stability gate |
| [Fluoride in water](fluoride.md) | the 64-label charged-cell campaign: the sampling switch and its structural recovery, VDOS, honest limits |
| [Cost and data efficiency](cost.md) | the cost ledger, per-label costs, GPU loop costs, deployment throughput |
