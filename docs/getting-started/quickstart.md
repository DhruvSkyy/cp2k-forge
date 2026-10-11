# Quickstart

Three steps: verify the environment, self-test the whole loop without CP2K, then run a
real campaign.

## 1. Preflight

```bash
cp2k-forge --check
```

This prints a PASS/WARN/FAIL table covering Python, every dependency, the CP2K binary
and data files, the trainer binary, the device, and the output directory — with an exact
fix for every problem. It works even before the `[train]` extra is installed (dependency
probing uses import metadata, not imports). The driver also runs it automatically at
start-up and aborts before any compute if something is missing (`--no-check` bypasses).

Add `--config configs/smoke.yaml` to also validate a specific campaign file and its seed
structure.

## 2. Self-test the whole pipeline (no CP2K, no GPU)

```bash
cp2k-forge --config configs/smoke.yaml
```

This runs the complete loop — generate → subsample → label → train → validate — in
about two minutes on a laptop CPU. Labels come from the cached foundation calculator
(`dft.backend: mock_foundation`) instead of DFT, so it proves your install end-to-end
without CP2K. **Plumbing only, never science.** Expected outcome: one pass completes, a
tiny model trains, a held-out force RMSE prints, and `runs/smoke/manifest.json` records
the finished state.

## 3. A real campaign

```bash
export CP2K_BIN=/path/to/cp2k.psmp     # see "CP2K as a dependency" for the full story
cp2k-forge --config configs/water.yaml
```

`configs/water.yaml` is a semi-local revPBE-D3 water campaign;
`configs/water_hybrid.yaml` is the hybrid revPBE0-D3 level used by the
[case studies](../case-studies/index.md). Edit one file to retarget the pipeline — DFT
level, explore grid, model size, convergence rule
([configuration reference](../guide/configuration.md)).

The run is **resumable**: every stage transition is persisted to
`<workdir>/manifest.json`, and finished DFT single points are keyed by structure hash,
so a killed job continues where it stopped and never recomputes a label.

### Shrink a real campaign into a smoke test

Any config can be shrunk on the command line without editing it — `--set` overrides are
also how ablation arms stay "identical by construction":

```bash
cp2k-forge --config configs/water.yaml \
  --set explore.steps=4200 --set explore.target_uncorrelated=2 \
  --set loop.max_passes=1 --set subsample.n_per_pass=5 --set subsample.min_frames=1
```

## Where next

- [CP2K as a dependency](cp2k-dependency.md) — how the binary and its data files are
  found, and what to export on a cluster.
- [Campaigns on HPC](../guide/campaigns-hpc.md) — splitting CPU labelling from GPU
  training, scratch directories, the batch-job template.
- [Case studies](../case-studies/index.md) — what a finished campaign looks like.
