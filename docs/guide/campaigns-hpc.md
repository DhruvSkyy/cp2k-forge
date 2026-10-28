# Campaigns on HPC

The pipeline is machine-agnostic by construction: everything site-specific travels
through [environment variables](../getting-started/cp2k-dependency.md#the-environment-variables),
so one config runs unchanged on a laptop or any scheduler. `example_job.sh` in the repo
root is a deliberately scheduler-free batch template; adapt the marked lines
(SLURM/PBS/LSF/local) and submit.

## Resumability is the default

Every stage transition persists to `<workdir>/manifest.json`, and every finished DFT
single point is keyed by a structure hash. Re-running the same command therefore
continues from the last completed stage and **never recomputes a finished label**: a
walltime kill costs you nothing but the stage in flight. Run the preflight up front so a
misconfigured job fails in seconds, not hours:

```bash
cp2k-forge --check --config configs/water.yaml
cp2k-forge --config configs/water.yaml
```

## Splitting CPU labelling from GPU training

The label stage is CPU-bound (CP2K), the train stage GPU-bound (mace-torch). Run them as
separate jobs on different nodes; the manifest hands over state between them:

```bash
# CPU node (needs CP2K; also computes the isolated-atom E0s)
cp2k-forge --config configs/water.yaml --stop-after label

# GPU node (does NOT need CP2K; the preflight knows this and will not fail it)
cp2k-forge --config configs/water.yaml
```

`--stop-after` accepts `generate`, `subsample`, `label` or `train`, so any stage
boundary can be a job boundary.

## Output placement

Point the workdir at scratch or other large storage, never a home quota:

```bash
export CP2K_FORGE_WORKDIR=/scratch/$USER/forge/water   # or: --workdir ...
```

Inside it you get `manifest.json`, `dataset.xyz` (the accumulated labels),
`e0s.json`, and one `passN/` directory per pass (trajectories, candidates, DFT run
directories keyed by hash, the trained model, and the validation scorecard).

## Sizing the label stage

DFT single points are independent, so they parallelise two ways:

- **within a node**: `dft.label_workers` runs several CP2K subprocesses side by side.
  One ~190-atom point stops scaling near ~16 cores, so on a 76-core node four
  modest-width frames beat one node-wide run by 3-4×. Threads per rank are sized
  automatically from the allocation (`SLURM_CPUS_PER_TASK`-aware);
- **across jobs**: because labels are hash-keyed and resumable, several label jobs can
  chew through the same pass.

Because the labels parallelise, a converged model arrives with far lower wall time than
the ab initio trajectory it replaces: the case-study campaigns each cost roughly a
thousand core-hours of DFT plus tens of A100-hours for the whole loop
([cost ledger](../case-studies/cost.md)).

## Ablation arms without config drift

`--set` overrides make arms identical by construction: one config file, each arm
differing only in its command line:

```bash
cp2k-forge --config configs/water.yaml \
  --set subsample.method=random --workdir runs/water_random
cp2k-forge --config configs/water.yaml \
  --set subsample.method=fps    --workdir runs/water_fps
```

Values parse as YAML (ints/floats/bools/lists/null all work) and the full validation
re-runs after the overrides, so an inconsistent combination still fails fast.

## Wall-clock discipline

`loop.max_wall_hours` is a portable, scheduler-agnostic bound on the whole loop: the
driver stops cleanly (recorded in the manifest) before starting a pass that would exceed
it, instead of being killed mid-stage. Combine with `loop.max_passes` as the budget cap.
