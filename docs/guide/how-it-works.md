# How it works

One YAML file defines the system, sampler, DFT labelling level, training recipe,
validation gates and convergence rule. From that file the pipeline repeats a compact
sequence (sample, select, label, train, validate) until a convergence or budget stop
fires. This page walks the loop stage by stage and names the module that owns each one.

<div class="pipeline-diagram" role="img" aria-label="The CP2K-FORGE campaign samples configurations, selects decorrelated frames, labels them with CP2K DFT, trains a compact model, validates it, and repeats until a plateau or budget stop is reached.">
  <div><strong>Sample</strong><span>foundation or promoted model</span></div>
  <i aria-hidden="true">→</i>
  <div><strong>Select</strong><span>decorrelated frames</span></div>
  <i aria-hidden="true">→</i>
  <div><strong>Label</strong><span>CP2K DFT</span></div>
  <i aria-hidden="true">→</i>
  <div><strong>Train</strong><span>compact MACE</span></div>
  <i aria-hidden="true">→</i>
  <div><strong>Validate</strong><span>force and stability</span></div>
  <i aria-hidden="true">→</i>
  <div class="pipeline-diagram__decision"><strong>Stop?</strong><span>plateau or budget</span></div>
  <p><b>No:</b> sample again with the promoted model. <b>Yes:</b> retain the accepted model.</p>
</div>

## Sample

*Code:* `cp2k_forge.generate` + `cp2k_forge.engines`

Sampling produces the pool from which expensive DFT labels are drawn. Early passes use
the foundation model (with D3 dispersion where the system needs it; raw MACE-MP-0 has
none and liquid water evaporates without it). Later passes sample with the newest
compact model, which keeps labels close to the region where the final model will
actually run. With the promotion gate on (`loop.promote_min_force_pct > 0`), only a
model that passed it may sample; until one does, the foundation model keeps sampling.
In the thesis campaigns this **sampling switch** came at pass 5 (water) and pass 6
(fluoride). The explored grid is
a list of state points (temperatures × density scales, or explicit pressures), each cell
a short MD trajectory with deterministic per-cell velocity seeds.

Two guards keep the pool honest: a density clamp aborts any trajectory whose box leaves
the physical window (an under-trained explorer can collapse or evaporate the cell), and
accepted trajectories are **thinned by autocorrelation time**
(`cp2k_forge.decorrelation`, default observable: hydrogen-bond count) so near-duplicate
frames never reach the selector. A static feasibility check at config load catches
sampling arithmetic that could never yield the requested number of uncorrelated frames.

## Select

*Code:* `cp2k_forge.subsample` (+ `cp2k_forge.direct`)

The selector chooses the DFT batch from the decorrelated pool through
`subsample.method`: `fps` (farthest-point sampling, the package default), `direct`
(foundation-model features → PCA → KMeans), `random` or `none`. The thesis campaigns and
the shipped `water_hybrid.yaml` use **`random`**, so those results test the sampler and
the gates rather than a separate active-learning rule. No selector comparison has been
run at a matched label budget.

## Label

*Code:* `cp2k_forge.label` + `cp2k_forge.cp2k_io` + `cp2k_forge.e0s`

Each selected configuration becomes one CP2K Quickstep single point: an energy-and-force
evaluation at fixed geometry, rendered from a packaged template and executed as a
subprocess ([the full mechanism](../getting-started/cp2k-dependency.md)). Labelling
parallelises directly: the points are independent, so they fan out across workers on a
node (`dft.label_workers`) and across jobs. Every finished point is keyed by a
**structure hash** in the manifest, so failed jobs are retried without invalidating a
pass and nothing is ever recomputed.

Isolated-atom reference energies (E0s) are computed once per campaign at the exact
labelling level (spin-polarised neutral atoms via their own template) and cached in
the workdir, so the energy baseline never silently shifts as the dataset grows.

## Train

*Code:* `cp2k_forge.train`

Training fits a compact MACE through `mace_run_train` (optionally accelerated by
cuEquivariance kernels) on the accumulated labels, and exports each checkpoint in the
formats the CP2K backends need. The compact recipe (small `num_channels`, `max_ell`,
`num_interactions`) is the point: the deployed model's speed depends on it. Pass 1
trains from scratch; later passes can warm-start from the previous checkpoint to save
compute, which is safe only because the own-MD gate screens every promotion (a collapsed
warm start is rejected, not deployed).

The training stage is deliberately **a replaceable module behind the configuration
file**: the loop's data contract is DFT energies and forces in extended-XYZ
(`REF_energy` / `REF_forces` keys), and its gates test forces and dynamics, so another
model family could be trained by swapping this module while keeping the loop unchanged.

## Validate

*Code:* `cp2k_forge.validate`

Validation separates three different jobs, and keeping them separate is the design:

- **Promotion** (may this candidate sample the next pass?) is the optional sampler
  gate: force score, density window and a short MD trajectory driven by the candidate
  itself. Force error alone is not enough, because unstable dynamics can hide behind a
  good aggregate force score.
- **Stopping** (may the campaign end?) is a plateau or diminishing-returns rule on
  held-out force RMSE, or the pass budget. The thesis results additionally used a
  dimer screen and a paired-bootstrap rule; see [Validation and gates](validation.md).
- **Diagnostics** (how good is it, physically?) are RDF and VDOS comparisons, reported
  after deployment but never used as gates.

Different systems therefore change configuration, not workflow code.

## State, resumability, and the manifest

Run state is a JSON state machine in `<workdir>/manifest.json`
(`cp2k_forge.manifest.Manifest`): the current pass, the stage within it, every finished
label hash, per-pass records (explorer used, RMSE, validation scores), and the
convergence verdict. Every stage transition is persisted, so an interrupted job resumes
instead of restarting, and the CPU-bound label stage can run as a separate job from the
GPU-bound train stage (`--stop-after label`).

Structures move through the pipeline as ASE `Atoms` in extended-XYZ files; all
CP2K-to-MACE unit conversions live in a single module (`cp2k_forge/units.py`) pinned by
a torch-free regression test, so the reference numbers are consistent everywhere.

## Seeding

Every campaign starts from one structure, `system.seed_xyz` (extended XYZ, orthorhombic
cell). Each state point then runs its own short trajectory from that seed, so the seed
only needs to be roughly right. The shipped examples are `examples/water32.xyz` and
`examples/water64.xyz`; the fluoride worked example used the published 193-atom cell.
For other systems, see [Use it on your own system](../getting-started/your-system.md).
