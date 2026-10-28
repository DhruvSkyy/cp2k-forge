# Troubleshooting

Start every diagnosis with the doctor:

```bash
cp2k-forge --check --config <your config>
```

It prints one row per check with an exact fix for every FAIL, works before the heavy
dependencies are installed, and is run automatically at campaign start-up (abort on any
FAIL; bypass with `--no-check` or `CP2K_FORGE_SKIP_CHECK=1`).

## The checks, row by row

| Row | What it verifies | On FAIL |
| --- | --- | --- |
| `python` | Python ≥ 3.9 | upgrade the interpreter |
| `dep:*` | each dependency importable (numpy, pyyaml, ase, mace-torch, torch, scikit-learn; matplotlib is WARN-only) | `pip install -e ".[train,plot]"` or `./install.sh` |
| `config` | the YAML loads and passes `Config.validate()` | the row shows the exact validation error verbatim |
| `seed` | `system.seed_xyz` exists (resolved from the config file's directory) | fix the path; relative paths anchor at the config |
| `device` | cuda actually available when requested | run on a GPU node or set the devices to `cpu` |
| `workdir` | the nearest existing ancestor is writable (probed *without* creating anything) | point `CP2K_FORGE_WORKDIR` at writable scratch |
| `train:binary` | `mace_run_train` launchable **before** compute is spent | WARN when only the module fallback (`python -m mace.cli.run_train`) is available; FAIL → activate the right venv or set `train.mace_run_train_bin` |
| `cp2k:binary` | the configured binary resolves and answers `--version` | export `CP2K_BIN`; the fix hint lists any CP2K variants found on PATH |
| `cp2k:data` | the data files for your `dft.mode` are reachable | export `CP2K_DATA_DIR`; hybrid additionally needs `BASIS_ADMM` + `t_c_g.dat` |
| `cp2k` (SKIP) | mock backend or a train-only invocation; CP2K correctly not required | none |

## Common failures and their causes

**"cuda requested but torch.cuda.is_available() is False".** Wrong torch wheel for the
driver. Reinstall explicitly: `./install.sh --cuda cu124` (never guess the tag;
`--gpu` probes nvidia-smi and prints the right one).

**`device: gpu` in the config.** Accepted and silently normalised to `cuda`: torch's
name. If you see "don't know how to restore data location … tagged with gpu" you are on
an old checkout; any current version normalises this at load.

**CP2K runs but every data file is "not found".** CP2K resolves bare file names against
`CP2K_DATA_DIR`, and the subprocess runs in a per-frame scratch directory. Either export
it, or rely on derivation from the binary's install layout; the doctor's `cp2k:data`
row tells you which one is in effect.

**An `.ssmp` (OpenMP-only) CP2K.** Set `CP2K_MPI_LAUNCHER=none`: running an ssmp binary
under `mpirun -np N` launches N duplicate calculations. The pipeline never swaps binary
variants for you for exactly this reason.

**Hybrid config rejected at load.** The truncated-Coulomb radius must satisfy
`hfx_cutoff_radius_ang < min(cell)/2`, for the seed cell *and* at the NPT density
ceiling (`explore.density_max_gcc`). The error message names the offending number; lower
the radius or the ceiling, or use a bigger box
([why](hybrid-dft.md#truncated-coulomb-legality)).

**"explore.steps cannot yield target_uncorrelated frames".** The static feasibility
check: your trajectory is too short to produce the requested number of decorrelated
frames at the configured floor. The message prints the required step count; raise
`explore.steps`, lower `target_uncorrelated`, or (knowingly) set
`on_undersample: warn`.

**Training loss climbs after ~100 epochs.** Keep `train.ema: true`: EMA is the standard
MACE stabiliser and force training without it plateaus far short of convergence.

**A pass "succeeded" but validation shows garbage.** Validation failures never crash the
pass (a crash would leave the stage machine retraining forever); the pass advances with
an empty scorecard and a printed warning, and convergence simply cannot fire that pass.
Check the stability gate output first: an unstable model NaN-ing its own MD is the
usual cause, and more labels are the usual cure
([why force scores alone mislead](validation.md#promotion-three-gates-per-candidate)).

**Box collapse or evaporation during exploration.** The density clamp
(`explore.density_min_gcc` / `density_max_gcc` / `clamp_patience`) aborts such cells
loudly. For early passes on tiny datasets, `train.pair_repulsion: true` (ZBL) guarantees
the short-range repulsion the data cannot teach; for water, make sure the foundation
sampler has dispersion (`generator.dispersion: true`) or the liquid evaporates.

**Every D3 run segfaults immediately (signal 11, right after the Quickstep banner).**
Some source builds ship a broken DFTD3 module while everything else works; the input
even passes `cp2k.psmp --check`. Confirm with a 3-atom single point: it will run clean,
then crash the moment a `&VDW_POTENTIAL ... TYPE DFTD3` block is added. The fix is a
CP2K build/packaged binary with a working D3 (this is a CP2K build defect, not an input
problem). To keep working at a dispersion-free level in the meantime, set
`dft.vdw: none`, and remember that for water the *generator* still needs its
dispersion (`generator.dispersion: true` is torch-side D3, unaffected).

**Resume did not resume.** The manifest lives in the workdir: the same `--workdir` /
`CP2K_FORGE_WORKDIR` must be passed again. Labels are keyed by structure hash, so even a
deleted manifest only costs bookkeeping, never finished DFT.
