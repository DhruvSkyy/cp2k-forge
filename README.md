# CP2K-FORGE

Forge a small, fast, **system-specific** [MACE](https://github.com/ACEsuit/mace)
potential from a MACE foundation model, with [CP2K](https://www.cp2k.org) as the DFT
labelling engine. The foundation model is used **only as a structure generator**; the
physics comes entirely from DFT single points computed by CP2K.

```
        +------------ repeat ~4-5 passes until converged ------------+
        v                                                            |
 GENERATE --> SUBSAMPLE --> LABEL (DFT) --> TRAIN ------> converged? -+ --> SHOWCASE
 explorer     diversity     CP2K           fresh MACE      (no)            density
 MD           pick          revPBE-D3      from scratch                    isobar -> TMD
 (pass 1: MACE-MP-0+D3; pass >=2: the latest trained model)
```

First showcase: liquid water's **temperature of maximum density** (TMD, experiment ~277 K).

## What this is — and is not

- **Foundation model = sampler only.** Run MD with MACE-MP-0+D3 to generate diverse,
  physically-sensible structures. Keep the structures, discard its energies.
- **Labels = real DFT.** Every training structure gets a revPBE-D3 single point in CP2K.
- **Model = trained from scratch.** A fresh, compact MACE learns only from the DFT labels,
  so its physics is purely the labelling functional (clean revPBE-D3 provenance).
- **NOT distillation** (the foundation model never labels), **NOT fine-tuning** (no
  inherited weights), **NOT query-by-committee** (selection is diversity sampling).

The D3 correction on the generator is **mandatory for water** — raw MACE-MP-0 has no
dispersion and the liquid evaporates (density collapses to ~0.72 g/cm^3).

## Install

```
git clone https://github.com/DhruvSkyy/cp2k-forge.git
cd cp2k-forge
./install.sh            # venv + pip install -e ".[train,plot]"
. venv/bin/activate
```

or directly into an environment of your own:

```
pip install -e ".[train,plot]"
```

On a GPU node, install the torch wheel matching your driver explicitly (never guessed):
`./install.sh --cuda cu124`, or see the torch note in `install.sh`. The core package
(config handling, CP2K I/O, the preflight doctor, the parser tests) is torch-free; the
`[train]` extra adds `mace-torch` + `torch-dftd` for MD generation and training.

## CP2K is the labelling engine (a runtime dependency)

CP2K is never imported or linked — it is executed as a subprocess on generated input
files, so any working CP2K binary (>= 2023.x, with libdftd3 support compiled in, as all
standard builds have) works. Install it however you prefer:

- conda-forge: `conda install -c conda-forge cp2k`
- Linux distros: `apt install cp2k` / `dnf install cp2k`
- containers: `docker pull cp2k/cp2k`
- HPC: your site's module, or [build from source](https://github.com/cp2k/cp2k/blob/master/INSTALL.md)

Everything machine-specific is passed by environment variable, so the same config runs
on a laptop or any cluster:

| variable             | purpose                                                                                                                                             |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CP2K_BIN`           | path to the CP2K binary used for DFT labelling (default: `dft.cp2k_bin`, i.e. `cp2k.psmp` on PATH)                                                 |
| `CP2K_DATA_DIR`      | directory with `BASIS_MOLOPT`, `GTH_POTENTIALS`, `dftd3.dat`; may stay **unset** for a standard install — it is derived from the binary's location |
| `CP2K_MPI_LAUNCHER`  | `mpirun` (default) or `none` for an OMP-only (`.ssmp`) build                                                                                        |
| `CP2K_RANKS`         | MPI ranks per DFT single point                                                                                                                      |
| `CP2K_OMP_THREADS`   | OMP threads per rank (default: auto from the allocated cores)                                                                                       |
| `CP2K_FORGE_WORKDIR` | output directory (prefer scratch over a home quota)                                                                                                |

`cp2k-forge --check` prints exactly which binary and data directory the run will use.

## Quickstart

```
# 1. Verify the environment before spending any compute. Prints a PASS/WARN/FAIL
#    table with an exact fix for every problem (deps, config, CP2K, device, workdir).
cp2k-forge --check

# 2. Self-test the whole pipeline with NO CP2K and NO GPU (labels come from the
#    foundation model). Proves your install end-to-end in ~2 minutes.
cp2k-forge --config configs/smoke.yaml

# 3. Run the real water campaign (needs a CP2K binary for DFT labelling).
export CP2K_BIN=/path/to/cp2k.psmp
cp2k-forge --config configs/water.yaml
```

The driver runs the `--check` preflight automatically at start-up and aborts before any
compute if something is missing (bypass with `--no-check`). See `example_job.sh` for a
generic, scheduler-agnostic batch template.

## Running

The run is a state machine in `<workdir>/manifest.json`; re-running continues from the
last completed stage. DFT single points are keyed by structure hash, so finished labels
are never recomputed. Split CPU labelling from GPU training across nodes with
`--stop-after label` (the GPU train node is not required to have CP2K).

For a quick end-to-end smoke test of a real campaign, shrink it on the command line:

```
cp2k-forge --config configs/water.yaml \
  --set explore.steps=4200 --set explore.target_uncorrelated=2 \
  --set loop.max_passes=1 --set subsample.n_per_pass=5 --set subsample.min_frames=1
```

## Layout

```
src/cp2k_forge/     core library: units, config, dataset, manifest, seed, cp2k_env,
                    cp2k_io, label, e0s, generate, subsample, direct, decorrelation,
                    train, engines, validate, report, doctor, cli
  templates/        dft_singlepoint.inp (DFT labelling), dft_atom.inp (E0s),
                    aimd_reference.inp, md_backend.inp (optional in-CP2K-backend MD)
configs/water.yaml  the one file to edit to retarget a campaign
configs/smoke.yaml  no-CP2K, no-GPU install self-test
examples/           water32.xyz seed structure for the example configs
showcase/           run_isobar.py, density_tmd.py, plot_tmd.py, bench_throughput.py
tests/              torch-free parser round-trip regression test
docs/method.md      design rationale, stage-by-stage data flow, physics caveats
example_job.sh      generic, scheduler-agnostic batch-job template
```

## Config knobs (configs/water.yaml)

DFT functional + basis/pseudo/cutoff, the explore temperature/density grid, the compact
model size (`num_channels`, `max_ell`, `r_max`, `num_interactions`), frames per pass, and
the convergence tolerances (force-RMSE plateau + density movement). Swap `dft.functional`
to `revPBE0`/`SCAN` to relabel at a different level. Relative input paths in a config
resolve from the config file's directory, so a config travels with the files it names.

## Verification gates

- **Labelling:** `cp2k_forge.cp2k_io.parse_singlepoint_output` round-trips a known CP2K
  log to the right energy/forces; unit conversions live solely in `cp2k_forge/units.py`.
  A fast, torch-free regression test covers this parser.
- **Training:** held-out force RMSE reported each pass (target < ~40 meV/Angstrom).
- **Showcase:** density(T) shows a maximum; the TMD lands in the revPBE-D3 window with
  block-statistics error bars.

## Optional: the in-CP2K MACE backend (throughput showcase)

By default the pipeline is backend-agnostic: MD (explore, validate, showcase) runs through
generic MACE via ASE, so it needs only a stock CP2K (for labelling) plus `mace-torch`.

The trained compact models are also designed to run on the **optimised in-CP2K MACE
backend**, so the training factory and the fastest inference engine are one codebase. That
path (`generator.engine: cp2k-backend`, the `md_backend.inp` template,
`showcase/bench_throughput.py`) requires a metatomic-enabled CP2K build, which is a
separate contribution. Selecting it without that build raises a clear, actionable error
rather than failing obscurely. It adds `CP2K_BACKEND_BIN` (the metatomic-enabled CP2K
binary) and `SYMMETRIX_EXTRACT_SRC` (the model-to-JSON exporter).

## Method and implementation notes

See [docs/method.md](docs/method.md) for the design rationale, the stage-by-stage data
flow (which module owns which stage), and the known physics caveats.

## Provenance

Developed as part of an MPhil project at the University of Cambridge; extracted from the
`tools/mace-distill` directory of the author's CP2K development fork, where the pipeline
was built alongside optimised in-CP2K MLP backends.
