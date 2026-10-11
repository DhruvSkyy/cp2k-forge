# CLI

The console script `cp2k-forge` (equivalently `python -m cp2k_forge`) is the resumable
campaign driver: it runs generate → subsample → label → train → validate passes until
the convergence rule or budget stops the run, persisting every stage transition to
`<workdir>/manifest.json`.

```text
cp2k-forge --config CONFIG [--check] [--no-check]
           [--stop-after {generate,subsample,label,train}]
           [--workdir WORKDIR] [--set SECTION.KEY=VALUE ...]
```

| Flag | Meaning |
| --- | --- |
| `--config` | the campaign YAML ([reference](../guide/configuration.md)). Required except with `--check` |
| `--check` | run the environment preflight and exit (exit code 0 = no FAILs). Without `--config` it checks the environment only; with it, also the config, seed, device, workdir and CP2K reachability. A manual `--check` always reports full CP2K reachability; the automatic start-up preflight scopes it to the stages the invocation will reach |
| `--no-check` | skip the automatic start-up preflight (also `CP2K_FORGE_SKIP_CHECK=1`) |
| `--stop-after` | run up to this stage then exit, persisting the manifest — the CPU/GPU [job-splitting mechanism](../guide/campaigns-hpc.md#splitting-cpu-labelling-from-gpu-training) |
| `--workdir` | override the config `workdir` (also `CP2K_FORGE_WORKDIR`); point at scratch on clusters |
| `--set` | repeatable `section.key=value` override; values parse as YAML and the full config validation reruns afterwards — the [ablation-arm mechanism](../guide/campaigns-hpc.md#ablation-arms-without-config-drift) |

Behaviour worth knowing:

- The preflight aborts on any FAIL **before compute is spent**; each FAIL row prints an
  exact fix ([the full table](../guide/troubleshooting.md)).
- Re-running the same command resumes: finished stages are skipped, finished DFT labels
  (hash-keyed) are never recomputed.
- The loop ends with one of: converged (the plateau rule fired), stopped
  (`diminishing_returns` / `max_wall_hours`, recorded in the manifest), or the
  `max_passes` budget. The final model path prints last.
- Environment variables: the complete table lives in
  [CP2K as a dependency](../getting-started/cp2k-dependency.md#the-environment-variables).
