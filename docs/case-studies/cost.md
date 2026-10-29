# Cost and data efficiency

**The efficiency claim is deliberately narrow: the repeated cost is the CP2K label, not
a parent trajectory.** The accepted models use 89 (water) and 64 (fluoride) target-level
labels against 814 and 299 structures in the published committee models, and no parent
ab initio trajectory at all.

*(Thesis §9.3.3, see [provenance](../about/provenance.md); raw data:
[`forge_cost_curve.csv`](../assets/data/cost/forge_cost_curve.csv),
[`mace_steptime_data.csv`](../assets/data/cost/mace_steptime_data.csv),
[`backends_table_data.csv`](../assets/data/cost/backends_table_data.csv).)*

```{figure} ../assets/figures/fig_cost_ledger.png
:alt: Label and trajectory counts for this work and the committee routes

Retained-label cost of this workflow and the published committee routes, log scale. The third bar per system, the parent AIMD trajectory (600,000 / 104,000 steps), is the cost this workflow removes (thesis Fig. 9.9).
```

:::{admonition} Extrapolation, clearly labelled
:class: note

The committee-route costs are **extrapolations from this work's measured
per-single-point cost**, not measurements of the original work (≈8,600 / ≈3,700
core-h for labels alone; parent AIMD of order 10⁶ core-h), order-of-magnitude
statements, not benchmarks.
:::

## Measured cost of the accepted paths

Essential compute only (development runs, diagnostic retrains and density probes
excluded; GPU rows are campaign means, labelling totals from per-frame costs):

| Stage | Water | Fluoride |
| --- | --- | --- |
| Training + validation frames labelled | 89 + 50 | 64 + 37 |
| One training-frame single point (core-h, Ice Lake) | 10.2 | 12.3 |
| One validation-frame single point (core-h) | 13.9 | 13.3 |
| **Total DFT labelling (core-h)** | **~1,600** | **~1,280** |
| GPU sampling per pass (A100-h) | 0.9 | 1.5 |
| GPU retraining per pass (A100-h) | 0.18 | 0.12 |
| GPU light validation per pass (A100-h) | 0.25 | 0.3 |
| **Essential GPU total (A100-h)** | **18.5** | **15.6** |

Two structural facts fall out of the ledger. First, **the loop machinery is cheap next
to the labels**: the whole 8-pass fluoride GPU budget is worth about 90 hybrid single
points, and sampling cost is the same whether the foundation model or the compact model
explores, so the on-policy structural recovery in the
{ref}`fluoride study <fluoride-on-policy-recovery>` came
essentially free. Second, GPU cost per pass stays roughly **flat** as the label set
grows; the operational bottleneck is deciding how many expensive target-level labels to
acquire, not retraining. A hybrid label is itself the premium: the semi-local level is
~13× cheaper per single point (~0.95 core-h), which is what makes
[`dft.mode`](../guide/hybrid-dft.md) the campaign's main cost dial.

Because the labels are independent single points, they parallelise across nodes: a
converged model arrives at far lower *wall time* than the ab initio dynamics it
replaces.

## Accuracy against cumulative cost

Two draft figures from the report's working tree are kept here because they make the
story visual (they were cut from the final report; treat them as companion material).
The cost curve plots held-out force RMSE against cumulative build cost in CPU
core-equivalent hours (labels at per-frame medians + GPU stages at 55 core-equiv per
A100-h):

```{figure} ../assets/figures/fig_forge_cost_curve.png
:alt: Force RMSE against cumulative build cost

Held-out force RMSE against cumulative build cost in CPU core-equivalent hours. Draft companion figure, not in the thesis.
```

:::{admonition} Caveat on the cost curve
:class: warning

The water series covers **passes 1-3 only** (it predates the 89-label ambient
headline campaign); the fluoride series is complete (8 passes, 86.3 → 57.7 meV/Å
over 209 → 1,640 core-equiv-h). The CSV ships with these docs.
:::

And the Schran-style scorecard collects the force / RDF / VDOS agreement bars for both
compact models and both committees against the same ab initio references:

```{figure} ../assets/figures/fig_scorecard.png
:alt: Force, RDF and VDOS scores for compact models and committees

Force, RDF and VDOS scores for both compact models and both committees against the same ab initio references. Companion figure, not in the thesis.
```

## Deployment speed

The compact recipe pays off at inference: in MD on one A100 (193-atom cell), the
accepted compact model runs at **53 ms/step (0.81 ns/day)** against **137 ms/step
(0.32 ns/day)** for the foundation sampler it replaced: **2.6× faster**, measured with
[`showcase/bench_throughput.py`](../guide/showcase-density.md#throughput). The vendored
`mace_steptime_data.csv` / `backends_table_data.csv` carry the broader backend
measurements behind the report's engine chapters (per-run uncertainty kinds included).
