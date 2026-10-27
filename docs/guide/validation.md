# Validation and gates

Validation separates three jobs that are often conflated, and the separation is the
design: **promotion** decides whether a candidate may become the explorer, **convergence**
decides whether the campaign may stop, and **diagnostics** report physical quality
without gating anything. Different systems change thresholds in the config, not workflow
code.

## Promotion: three gates per candidate

A candidate model is promoted (deployed as the next explorer) only if it

1. **lowers held-out force RMSE** relative to the incumbent promoted model;
2. **passes a dimer-compression screen** — the dimer energy curve must stay repulsive at
   short range (the case-study campaigns used floors of −1.2 eV for water and −0.85 eV
   for fluoride); this excludes qualitatively attractive short-range behaviour that a
   tiny dataset cannot rule out;
3. **survives its own MD**: a short CP2K-validated trajectory driven by the candidate
   itself, gated on minimum-approach distances
   (`validate.stability_min_oo_ang` / `stability_min_oh_ang`).

Force error is an entry condition, not the deployment criterion, because **unstable
dynamics can hide behind a good aggregate force score**. The water case study shows this
concretely: in matched retrains, models below 40 labels score 92-93% on forces yet
collapse into unphysical near contact in their own MD, and a warm-started ablation arm
fitted the held-out forces *best* while collapsing in dynamics. Selecting on force error
alone would have promoted an unstable water model
([the stability figure](../case-studies/water.md#the-stability-gate)).

The sampler-promotion gate (`loop.promote_min_force_pct`,
`loop.promote_density_window_gcc`) adds one more protection: the explorer switches from
the foundation model to a trained model only once that model's validation clears the
bar — an undertrained model must not explore unsupervised.

## Convergence: a pre-registered plateau rule

The convergence statistic is the **improvement in held-out force RMSE between adjacent
passes**, estimated by paired bootstrap resampling of the validation frames (so the
error bar measures sensitivity to the finite validation set). The campaign is converged
only when the **upper edge** of that improvement stays below the threshold for
`loop.consecutive_passes` passes in a row.

The case-study campaigns fixed the rule **before the passes it governs**: a 2.0 meV/Å
threshold (chosen to exceed the bootstrap noise while remaining small against the final
~52-58 meV/Å force RMSE), B = 10,000 bootstrap resamples with a recorded seed, and two
consecutive passes (one noisy plateau must not stop a campaign). Freezing thresholds,
validation sets and the bootstrap seed before use is the methodological core: a stopping
rule chosen after seeing the curve proves nothing. Water stopped with final gains of
1.42 and 0.72 meV/Å (bootstrap upper edges 1.52 and 0.78 < 2.0); fluoride with upper
edges 1.86 and 1.51.

:::{admonition} Pass validity
:class: note

`subsample.min_frames` is a validity floor: a pass that labels fewer frames is never
deployed and never plotted, but it still enters the pass-to-pass improvement
sequence the rule tracks. The rule does not require the curve to be flat — it stops
when the certified improvement is smaller than the pre-set band.
:::

Two cheaper stops complement the rule: `loop.min_rel_improvement_force` (quit when a
pass buys less than a set *fraction* of improvement — extra labels are not buying
accuracy) and `loop.max_passes` / `loop.max_wall_hours` (the budget).

## Diagnostics: the scorecard

After each pass, `validate.validate_model` writes `scorecard.md` into the pass
directory: held-out force RMSE (fixed and incremental test sets), DFT spot-checks on the
model's own dynamics, RDF and VDOS scores, a density probe, stability minima, and
experimental anchors (reported, never gated — classical nuclei at a given functional
should not reproduce experiment exactly).

Scores follow the Schran-style conventions, where the reference RMS force sets the
scale:

```text
force score     S_F = (1 − F_RMSE / F_RMS,ref) × 100 %
overlap score   S_O = (1 − Σ|g_model − g_ref| / Σ|g_ref|) × 100 %   (RDF / VDOS)
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
model on an independently pre-registered ambient ruler re-fires the same convergence
verdict.
