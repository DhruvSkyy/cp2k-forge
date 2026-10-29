# Validation and gates

Validation separates three jobs that are often conflated: **promotion** decides whether
a candidate may sample the next pass, **stopping** decides whether the campaign may end,
and **diagnostics** report physical quality without gating anything. Different systems
change thresholds in the config, not workflow code.

This page first states what the packaged v0.1.0 code does, then the stricter protocol
used for the thesis results.

## What v0.1.0 implements

### Per-pass checks

After training, every candidate is scored on held-out frames and run in a short MD
trajectory driven by its own forces. The stability check fails when the closest O-O or
O-H approach drops below `validate.stability_min_oo_ang` (default 2.0 Å) or
`validate.stability_min_oh_ang` (default 0.7 Å).

### Sampler promotion gate

`loop.promote_min_force_pct` controls which model samples the next pass. It is **off by
default** (`0`), in which case the previous pass's model always samples. When set, a
trained model may sample only if

1. its spot-check force score is at least `loop.promote_min_force_pct`;
2. its density probe lies inside `loop.promote_density_window_gcc`;
3. its stability MD passed;
4. it caused no density-clamp aborts in a pass it already sampled.

The newest model meeting all four is used; if none does, the foundation model keeps
sampling. An undertrained model must not explore unsupervised.

### Stop rules

`cp2k_forge.manifest.Manifest.check_convergence` stops a campaign on either of two rules:

- **Plateau** (`converged`): held-out force RMSE below `loop.force_rmse_tol_mev_ang`
  and density moving less than `loop.density_tol_gcc` between passes, plus any optional
  score thresholds that are set (`force_score_converged_pct`, `rdf_converged_pct`,
  `vdos_converged_pct`, `density_anchor_gcc`), holding for `loop.consecutive_passes`
  adjacent pass pairs.
- **Diminishing returns** (`stopped`): a pass improves force RMSE by less than the
  fraction `loop.min_rel_improvement_force` (fixed-test RMSE when available). This is
  recorded as a stop, not as convergence.

`loop.max_passes` and `loop.max_wall_hours` bound the budget.

## Protocol used in the thesis campaigns

The water and fluoride results were produced with the report's research pipeline, which
added two checks that are **not yet in the packaged release**:

- **Dimer-compression screen.** The O-H dimer energy at 2.0 Å must stay above a
  per-system floor (−1.2 eV for water, −0.85 eV for fluoride), excluding qualitatively
  attractive short-range behaviour that a small dataset cannot rule out. Borderline
  candidates were decided by the stability MD.
- **Paired-bootstrap convergence rule.** The statistic is the improvement in held-out
  force RMSE between adjacent passes, estimated by paired bootstrap resampling of the
  frozen validation frames (B = 10,000, recorded seed). A campaign is converged when the
  one-sigma upper edge of that improvement stays below 2.0 meV/Å for two consecutive
  passes. The threshold exceeds the bootstrap noise while staying small against the final
  ~52-58 meV/Å force RMSE.

Thresholds, validation sets and the bootstrap seed were fixed before the passes they
govern; a stopping rule chosen after seeing the curve proves nothing. Water stopped with
final gains of 1.42 and 0.72 meV/Å (upper edges 1.52 and 0.78); fluoride with upper
edges 1.86 and 1.51 (thesis Table B.5).

Force error is an entry condition, not the deployment criterion, because **unstable
dynamics can hide behind a good aggregate force score**. In matched water retrains,
models below 40 labels score 92-93% on forces yet collapse into unphysical contact in
their own MD, and a warm-started ablation arm fitted held-out forces *best* while
collapsing ([the stability figure](../case-studies/water.md#the-stability-gate)).

:::{admonition} Pass validity
:class: note

`subsample.min_frames` is a validity floor: a pass that labels fewer frames is never
deployed and never plotted, but it still enters the pass-to-pass improvement sequence
the thesis rule tracks. The rule does not require the curve to be flat; it stops when
the certified improvement is smaller than the pre-set band.
:::

## Diagnostics: the scorecard

After each pass, `validate.validate_model` writes `scorecard.md` into the pass
directory: held-out force RMSE (fixed and incremental test sets), DFT spot-checks on the
model's own dynamics, RDF and VDOS scores, a density probe, stability minima, and
experimental anchors (reported, never gated unless a loop threshold is set; classical nuclei at a given functional
should not reproduce experiment exactly).

Scores follow the Schran-style conventions, where the reference RMS force sets the
scale:

```text
force score     S_F = (1 − F_RMSE / F_RMS,ref) × 100 %
overlap score   S_O = (1 − Σ|y_ref − y_test| / Σ(y_ref + y_test)) × 100 %   (RDF / VDOS)
```

RDF and VDOS comparisons are **diagnostics after deployment, not gates**: they need a
reference trajectory or spectrum (`validate.rdf_ref_xyz`, `validate.vdos_ref_npy`) and
are skipped with a note when none is configured.

## Why the frozen ruler matters

Per-pass spot-check frames change every pass, so cross-pass and cross-arm comparisons
need a **constant yardstick**: a frozen, DFT-labelled test set
(`validate.fixed_test_xyz`), ideally registered before pass 1. The incremental mode
(`testset_mode: incremental`) grows the ruler each pass from a dedicated,
never-trained-on pool and reports the accumulated-set score alongside the
newest-increment score (the unbiased-on-new-data check). The water case study's
second-ruler audit shows why this is worth the discipline: re-scoring every deployed
model on an independently fixed ambient ruler re-fires the same convergence
verdict.
