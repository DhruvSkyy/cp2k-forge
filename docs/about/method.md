# Design rationale

CP2K-FORGE is an automated pipeline that turns a general-purpose MACE foundation model
(such as MACE-MP-0) into a small, fast, **system-specific** MACE interatomic potential at
a chosen DFT level of theory. The foundation model is used **only as a structure
generator**: it proposes diverse, physically-sensible configurations, but all of the
physics in the final model comes from DFT single points computed by CP2K. The tooling lives
in [the cp2k-forge repository](https://github.com/DhruvSkyy/cp2k-forge).

The design goal is a clean provenance chain: because a fresh, compact model is trained
from scratch on nothing but DFT labels, its physics is exactly that of the labelling
functional, with no inherited bias from the foundation model.

## What it is, and is not

- **Foundation model = sampler only.** MD with the foundation model (plus D3 dispersion)
  generates structures. The structures are kept; the foundation model's energies and forces
  are discarded.
- **Labels = real DFT.** Every training structure receives a DFT single point in CP2K (the
  reference example uses revPBE-D3 for liquid water).
- **Model = trained from scratch.** A compact MACE learns only from the DFT labels.
- This is **not** distillation (the foundation model never provides labels), **not**
  fine-tuning (no weights are inherited), and **not** query-by-committee (selection is
  diversity sampling, not uncertainty sampling).

The D3 correction on the generator is mandatory for water: raw MACE-MP-0 has no dispersion,
so the simulated liquid evaporates and the density collapses.

## The loop

```
        +------------- repeat passes until converged ----------------+
        v                                                            |
 GENERATE --> SUBSAMPLE --> LABEL (DFT) --> TRAIN ------> converged? -+ --> SHOWCASE
 explorer     select        CP2K, GGA      compact MACE    (no)            density
 MD           decorrelated  or hybrid      on the labels                   isobar
 (pass 1: foundation model + D3; pass >=2: the latest promoted model)
```

Each pass explores configuration space, selects the most informative new structures,
labels them with DFT, and retrains. The explorer is the foundation model on pass 1 and the
latest trained model on later passes (once it has passed a promotion gate). The loop stops
when the held-out force error and the target property both stop improving.

## Stage-by-stage implementation

Every stage is a module in the `cp2k_forge` package; the driver (`cp2k-forge`) sequences them
and persists progress after each one.

| Stage     | Module / function                                     | What it does                                                                                                                                                                                                                        |
| --------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Generate  | `generate.build_explorer`, `generate.generate_frames` | MD over a temperature/density grid using an ASE + mace-torch engine (`engines.ASEMaceEngine`). Trajectories are decorrelated (`decorrelation`) so only time-independent frames survive.                                             |
| Subsample | `subsample.subsample` (+ `direct`)                    | Diversity selection (DIRECT: foundation-model features -> PCA -> KMeans, or farthest-point sampling) picks the minimal spanning set, so the DFT budget is spent on distinct structures.                                             |
| Label     | `label.label_frames`, `cp2k_io`, `e0s`                | Writes a CP2K single-point input per structure (`cp2k_io.write_singlepoint_input`), runs CP2K, and parses the log (`cp2k_io.parse_singlepoint_output`). Isolated-atom reference energies (E0s) are computed once at the same level. |
| Train     | `train.train_from_scratch`                            | Wraps `mace_run_train` to fit a fresh compact MACE (small `num_channels`/`max_ell`/`r_max`, the speed claim depends on this).                                                                                                      |
| Validate  | `validate.validate_model`                             | Held-out force RMSE plus RDF/VDOS self-convergence scores, and an NPT density probe.                                                                                                                                                |
| Showcase  | `showcase/run_isobar.py`, `showcase/density_tmd.py`   | Runs the 1 atm density isobar and analyses the density-maximum region.                                                                                                                                                       |

### Data flow

Structures move through the pipeline as ASE `Atoms` objects in extended-XYZ files. DFT
labels are parsed into the MACE reference-key schema: the energy under `REF_energy` and the
forces under the per-atom array `REF_forces` (with `REF_stress` available when a stress
tensor is requested). All CP2K-to-MACE unit conversions (Hartree to eV, bohr to Angstrom,
and so on) live in a single module, `cp2k_forge/units.py`, so the reference numbers are
consistent everywhere.

Run state is a JSON state machine in `<workdir>/manifest.json` (`manifest.Manifest`). Each
DFT single point is keyed by a structure hash, so a labelled frame is never recomputed: a
killed run resumes from exactly where it stopped. This makes the pipeline robust to job
interruptions and lets the CPU-bound labelling stage be split from the GPU-bound training
stage across separate jobs (`cp2k-forge --stop-after label`).

## Verification

- **Labelling correctness** is covered by a fast, torch-free regression test that feeds a
  known CP2K log to `cp2k_io.parse_singlepoint_output` and checks the recovered energy and
  forces. This is the unit-level guard on the whole labelling stage.
- **Training quality** is reported every pass as the held-out force RMSE on a fixed DFT
  test set (a constant yardstick across passes).
- **Physical fidelity** is the showcase: the 1 atm density isobar with block-statistics
  error bars, read against the labelling functional's own reference (never against
  experiment, see the claim constraints in the Showcase guide).

## A physics caveat worth stating

The equilibrium density of the final model is set by the **training objective**, not by the
sampling ensemble. Forces are derivatives of the energy at fixed cell and do not constrain
the stress that fixes the equilibrium volume. A model can therefore fit every force well and
still predict the wrong pressure, leaving the density as a free direction. If the density (or
the temperature of maximum density) must be reproduced tightly, train on the stress tensor
from the start (set `train.stress_weight > 0` and request the stress in the label template);
no change of sampling ensemble can substitute for that.

## Running on a cluster

The tooling is machine-agnostic. The CP2K binary, its data files, the MPI launcher, and the
output directory are all chosen at run time by environment variables (`CP2K_BIN`,
`CP2K_DATA_DIR`, `CP2K_MPI_LAUNCHER`, `CP2K_RANKS`, `CP2K_FORGE_WORKDIR`), so one config
runs unchanged on a laptop or any scheduler. A generic, site-free batch template is provided
in `example_job.sh`.

Three features make it robust to set up on an unfamiliar machine:

- **Install:** `./install.sh` builds an isolated virtualenv and installs the pinned
  dependencies with no sudo or module assumptions. On a GPU node, pass the CUDA wheel tag
  matching the driver (`./install.sh --cuda cu124`); the wheel is never guessed, since a
  mismatched torch/CUDA build is the most common install failure.
- **Preflight:** `cp2k-forge --check` validates the whole environment (dependencies, the
  config and seed, device availability, the CP2K binary and its data files, a writable
  workdir) and prints an exact fix for each problem. The driver runs the same check
  automatically at start-up and aborts before spending compute, so a misconfigured job
  fails in seconds instead of hours (bypass with `--no-check`).
- **Self-test:** `cp2k-forge --config configs/smoke.yaml` runs the entire loop with the
  mock backend (labels from the foundation model), needing neither CP2K nor a GPU, so an
  install can be proven end-to-end anywhere before committing to a real campaign.

For a large campaign, the CPU-bound labelling stage and the GPU-bound training stage can be
run as separate jobs on different nodes with `--stop-after label`; the manifest persists
progress between them, and the train node is not required to have CP2K. Point
`CP2K_FORGE_WORKDIR` at scratch or other large storage, not a home quota.

## The optional in-CP2K backend

By default all MD runs through generic MACE via ASE, so only a stock CP2K (for DFT
labelling) and `mace-torch` are required. The compact models are additionally designed to
run on the optimised in-CP2K MACE backend, uniting the training factory and the fastest
inference engine in one codebase; that path (`generator.engine: cp2k-backend`,
`templates/md_backend.inp`, `showcase/bench_throughput.py`) requires a metatomic-enabled
CP2K build, provided separately. Selecting it without that build raises a clear, actionable
error.
