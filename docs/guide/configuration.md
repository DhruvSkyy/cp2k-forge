# Configuration reference

One YAML file holds the whole campaign. The same file sets the sampling switch, pass
budget, convergence rule and plateau strictness, and the same DFT settings generate the
training and held-out labels, so fitting and scoring can never drift apart. Load-time
validation (`Config.validate`) fails fast on inconsistent combinations, and every value
can be overridden per run with `--set section.key=value` (repeatable), which is how
ablation arms stay identical by construction.

A trimmed campaign looks like this (see `configs/water.yaml`, `configs/water_hybrid.yaml`
and `configs/smoke.yaml` for complete, annotated examples):

```yaml
system:
  elements: [H, O]
  seed_xyz: ../examples/water64.xyz
  cell_abc: [12.4313, 12.4313, 12.4313]   # A, cubic
dft:
  mode: hybrid                  # revPBE0-D3 under ADMM; "gga" for semi-local
  functional: revPBE
  hf_fraction: 0.25
explore:
  temperatures_k: [300]
  ensemble: NVT
subsample:
  method: random                # the report's selector
  n_per_pass: 10
train:
  num_channels: 96              # compact by design
loop:
  max_passes: 15
  min_rel_improvement_force: 0.05
workdir: runs/water_hybrid
```

**Path resolution:** relative *input* paths in the config (`seed_xyz`,
`train.e0s_file`, reference data under `validate:`) resolve from **the config file's
directory**, so a config travels with the files it names. `workdir` resolves from the
current directory (or `CP2K_FORGE_WORKDIR` / `--workdir` overrides it). Absolute paths
pass through unchanged.

## `system`

| Key | Default | Meaning |
| --- | --- | --- |
| `name` | (required) | campaign name; prefixes model files |
| `seed_xyz` | (required) | initial structure (XYZ/extended-XYZ). If the file carries its own lattice it must agree with `cell_abc` to 1e-3 Å, and the loader refuses to silently rescale |
| `elements` | (required) | element symbols present |
| `cell_abc` | (required) | orthorhombic box lengths, Å |

## `dft`: the labelling level

| Key | Default | Meaning |
| --- | --- | --- |
| `functional` | `revPBE` | XC functional (CP2K `PARAMETRIZATION` token) |
| `vdw` | `dftd3` | `dftd3` renders the D3 pair potential; `none` strips the vdW section for a dispersion-free labelling level (the two D3 knobs below then do nothing) |
| `dispersion_ref` | `revPBE` | `REFERENCE_FUNCTIONAL` for the D3 correction. For `mode: hybrid` set this to the **hybrid** name (e.g. `revPBE0`), not the GGA base |
| `d3_damping` | `zero` | `zero` (DFTD3) or `bj`. For water/revPBE, zero damping is correct; BJ inverts the ice/water density order |
| `cutoff_ry`, `rel_cutoff_ry` | 400, 50 | plane-wave cutoffs (Ry) |
| `basis_set` | `TZV2P-MOLOPT-GTH` | orbital basis for every kind |
| `potential` | `GTH-PBE` | pseudopotential family |
| `eps_scf`, `max_scf` | 1e-6, 20 | SCF convergence; campaigns typically tighten to 1e-7 / raise max_scf (a silently non-converged frame is a poisoned label) |
| `charge` | 0 | net cell charge (e.g. −1 for a fluoride box; compensated by the GPW background). E0 atoms stay neutral regardless |
| `uks` | false | open-shell labelling (E0 atoms set UKS via their own template independently) |
| `cp2k_bin`, `cp2k_ranks` | `cp2k.psmp`, 4 | overridden by `CP2K_BIN` / `CP2K_RANKS` |
| `label_workers` | 1 | concurrent CP2K frames per node; several modest-width points beat one node-wide run |
| `backend` | `cp2k` | `mock_foundation` labels with the cached foundation calculator instead of DFT (install self-test; plumbing only, never science) |
| `mock_model`, `mock_device` | `mace-mp-0`, `cpu` | the mock backend's calculator |

### `dft`: hybrid block (`mode: hybrid`)

Renders `dft_singlepoint_hybrid.inp` instead of the GGA template; `mode: gga` keeps the
GGA path byte-identical. Full walk-through: [Hybrid DFT](hybrid-dft.md).

| Key | Default | Meaning |
| --- | --- | --- |
| `mode` | `gga` | `gga` \| `hybrid` |
| `hf_fraction` | 0.25 | `&HF FRACTION`; the GGA exchange `SCALE_X` is always derived as `1 − hf_fraction`, never a second knob |
| `hfx_cutoff_radius_ang` | 6.0 | truncated-Coulomb radius. **Must be < min(cell)/2 for every labelled frame** (guarded at config load and per frame) and must never change mid-campaign, it is part of the level of theory |
| `eps_schwarz` | 1e-6 | `&HF &SCREENING EPS_SCHWARZ` |
| `hfx_max_memory_mb` | 2400 | `&HF &MEMORY MAX_MEMORY` per MPI rank; raise on fat nodes to cut HFX recomputation |
| `admm_basis` | `cpFIT3` | `AUX_FIT` basis for every kind (from `BASIS_ADMM`) |
| `admm_basis_overrides` | `{}` | per-element `AUX_FIT` override, e.g. `{F: aug-cpFIT3}`: anions want diffuse auxiliary functions |
| `admm_purification` | `MO_DIAG` | `ADMM_PURIFICATION_METHOD` |
| `admm_exch_correction_func` | `PBEX` | `EXCH_CORRECTION_FUNC` (with `EXCH_SCALING_MODEL NONE`) |

## `generator`: the explorer

| Key | Default | Meaning |
| --- | --- | --- |
| `model` | `mace-mp-0` | foundation model name or a path to a `.model` file |
| `dispersion` | true | add D3 to the foundation calculator; mandatory for water with MP-0 (no dispersion of its own → the liquid evaporates) |
| `device` | `cpu` | `cuda` on a GPU node (`gpu` is accepted and normalised) |
| `engine` | `ase` | `ase` runs anywhere with mace-torch; `cp2k-backend` runs trained-model MD inside CP2K (needs a metatomic-enabled build; raises an actionable error without one) |
| `enable_cueq` | false | cuEquivariance kernels for torch-side MD; silently off if the packages are missing |

## `explore`: the sampling grid

| Key | Default | Meaning |
| --- | --- | --- |
| `temperatures_k` | [250, 270, 290, 310] | exploration temperatures |
| `density_scales` | [0.95, 1.0, 1.05] | initial box scalings (bracket the equilibrium) |
| `pressures_bar` | null | when set, the grid becomes temperatures × pressures and `density_scales` is ignored; explicit pressures pin the *ensemble* so sampled densities genuinely bracket |
| `ensemble` | `NPT` | `NPT` samples density too; `NVT` keeps the (scaled) seed box |
| `steps`, `timestep_fs` | 10000, 0.5 | per-cell MD length |
| `sample_every` | 50 | raw probe stride (frames stored every N steps) |
| `equilibration_steps` | 200 | discarded before sampling |
| `warm_start_cells` | false | start each cell from *its* final frame of the previous pass (fresh velocities); the cache updates only from gate-passing explorers |
| `warm_equilibration_steps` | null | shorter equilibration from a warm start |
| `md_workers` | 1 | run grid cells in worker processes, round-robin over GPUs (identical output; deterministic per-cell seeds) |
| `pressure_bar`, `compressibility_au` | 1.0, 4.57e-5 | NPT barostat settings |
| `barostat` | `berendsen` | production barostat: `berendsen` or `mtk` (canonical). Berendsen relaxes fast but suppresses the fluctuations NPT sampling exists for, so it is only ever used for discarded equilibration in observable-bearing runs |
| `nvt_thermostat` | `langevin` | `langevin` or `bussi` (CSVR) for NVT segments |
| `tdamp_fs`, `pdamp_fs` | 100, 1000 | thermostat / barostat time constants |
| `friction` | 0.01 | Langevin friction (NVT only) |
| `deuterium_masses` | false | opt-in D masses (pair with a 1 fs step) |
| `density_min_gcc`, `density_max_gcc`, `clamp_patience` | 0.6, 1.3, 5 | stability clamp: abort a trajectory whose density leaves the window (guards explorer collapse). With `dft.mode: hybrid`, `density_max_gcc` is also checked against HFX-radius legality at load |
| `sample_mode` | `decorrelation` | `decorrelation` (thin each trajectory at its measured autocorrelation time) or `fixed` |
| `decorrelation_observable` | `hbond` | `hbond` (water only; needs O) \| `energy` \| `density` |
| `target_uncorrelated` | 100 | per-trajectory cap on uncorrelated frames |
| `min_sample_every_fs` | 1000 | 1 ps floor (the H-bond-lifetime argument) |
| `on_undersample` | `warn` | `fail` aborts generate when a cell cannot yield the target at the demanded stride; a static feasibility check at load catches the arithmetic version before any MD |
| `n_replicas`, `velocity_seed_base` | 1, 0 | extra per-cell trajectories differing only in deterministic velocity seed |

## `subsample`: the selector

| Key | Default | Meaning |
| --- | --- | --- |
| `method` | `fps` | `random` \| `fps` \| `direct` (features → PCA → KMeans) \| `none`. **The report's campaigns used `random`**; no selector comparison has been run at matched budget |
| `n_per_pass` | 200 | labels per pass (campaigns typically 10-15) |
| `n_first_pass` | null | larger first batch (a from-scratch model needs more to be MD-stable); null → `n_per_pass` |
| `min_frames` | 50 | pass-validity floor: a pass that labels fewer frames is invalid (never deployed, still counted by the plateau rule) |
| `enabled` | true | false skips selection and labels the decorrelated frames directly |
| `dataset_aware` | false | condition selection on the cumulative labelled set; never re-cover owned regions |
| `selection_seed` | 0 | RNG seed for `random` (varied per pass) |

## `train`: the compact recipe

| Key | Default | Meaning |
| --- | --- | --- |
| `num_channels`, `max_ell`, `num_interactions`, `r_max` | 64, 2, 2, 5.0 | the compact-model knobs, small by design; the deployment-speed claim depends on this |
| `mace_run_train_bin` | `mace_run_train` | trainer entry point (module fallback `python -m mace.cli.run_train` when not on PATH) |
| `device`, `seed` | `cpu`, 1 | training device and seed |
| `batch_size`, `max_num_epochs`, `valid_fraction` | 5, 200, 0.1 | optimiser basics |
| `stress_weight` | 0.0 | >0 trains on the stress; it **must stay 0 for `mode: hybrid`** (hybrid labels carry no stress). See the [physics caveat](../about/method.md#a-physics-caveat-worth-stating) |
| `energy_key`, `forces_key`, `stress_key` | `REF_*` | extended-XYZ label keys |
| `pair_repulsion`, `pair_repulsion_until_pass` | false, 0 | ZBL short-range repulsion a tiny early dataset cannot teach (guards box collapse); 0 = every pass |
| `e0s_mode` | `average` | `isolated` = one-time spin-polarised atoms at the exact labelling level (recommended; cached per workdir); `average` least-squares-fits and silently shifts as data grows; `file` reads a prepared `e0s.json` |
| `e0s_file` | null | path for `e0s_mode: file` |
| `lr`, `ema`, `ema_decay` | 0.01, true, 0.99 | EMA is required for stable force training |
| `swa`, `start_swa`, `swa_energy_weight` | false, null, 1000 | optional stage-two (energy-reweighted averaging) |
| `patience`, `eval_interval` | null, null | early stop / validation cadence |
| `warm_start`, `warm_lr`, `cold_epochs` | false, null, null | continue from the previous pass's checkpoint (pass 1 stays cold); safe only because the own-MD gate screens every promotion |
| `enable_cueq` | false | cuEquivariance-accelerated training |

## `loop`: budget, convergence, promotion

| Key | Default | Meaning |
| --- | --- | --- |
| `max_passes` | 5 | the budget cap |
| `force_rmse_tol_mev_ang` | 40.0 | held-out force-RMSE plateau target |
| `min_rel_improvement_force` | 0.0 | data-efficiency stop: quit when a pass improves force RMSE by less than this fraction (0 = off) |
| `consecutive_passes` | 1 | the plateau must hold this many passes in a row (the report's campaigns used 2) |
| `density_tol_gcc` | 0.005 | target-property movement between passes (used when the density probe runs) |
| `force_score_converged_pct`, `rdf_converged_pct`, `vdos_converged_pct` | null | optional extra gates (Schran-style score conventions) |
| `density_anchor_gcc`, `density_anchor_tol_gcc` | null | optional density anchor |
| `promote_min_force_pct` | 0.0 | sampler promotion gate: the explorer switches from foundation to a trained model only once validation clears this bar (0 disables; an undertrained model must not explore unsupervised) |
| `promote_density_window_gcc` | [0.87, 1.10] | promotion density window |
| `max_wall_hours` | null | portable wall-clock bound for the whole loop (scheduler-agnostic) |

## `validate`: scorecard and probes

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | true | run the scorecard after each pass |
| `n_dft_spotcheck` | 10 | DFT single points on the model's *own* dynamics → force score |
| `spotcheck_md_steps`, `spotcheck_temperature_k` | 2000, 300 | doubles as the stability MD (raise to ~20000 = 10 ps for a meaningful blow-up check) |
| `validate_previous_model` | true | also score the prior model, so progress is visible pass to pass |
| `fixed_test_xyz` | null | frozen held-out DFT test set: the constant yardstick for cross-pass and cross-arm comparisons |
| `testset_mode`, `testset_increment`, `testset_pool_xyz` | `fixed`, 5, null | incremental mode grows the ruler each pass from a never-trained-on pool |
| `nvt_cell_abc` | null | observables MD cell (e.g. the experimental density), decoupling structure scores from the model's density error |
| `rdf_ref_xyz`, `vdos_ref_npy` | null | external references; the corresponding score is skipped with a note when unset |
| `rdf_pairs`, `rdf_r_max`, `rdf_nbins` | O-O/O-H/H-H, 6.0, 120 | RDF scoring grid |
| `vdos_enabled`, `vdos_md_steps`, `vdos_temperature_k`, `vdos_rdf_stride` | false, 20000, 300, 100 | the NVE leg (also yields the RDF trajectory + an energy-conservation check) |
| `density_probe_steps`, `density_probe_temperature_k` | 2000, null | NPT density probe; 2000 steps is a smoke value; a campaign needs ~100 ps for a ~0.006 g/cc standard error |
| `density_ref_gcc`, `goo_peak_r_ref`, `goo_peak_h_ref` | null | experimental anchors, **reported next to scores, never gated** (classical nuclei at a given functional should not reproduce experiment exactly) |
| `stability_min_oo_ang`, `stability_min_oh_ang` | 2.0, 0.7 | the own-MD stability gate's minimum approach distances |
| `stability_min_any_ang` | 0.5 | floor on the closest approach of any two atoms; applies to every system |
| `published_reference` | null | literature overlay for the per-pass figure suite |

## `showcase`

| Key | Default | Meaning |
| --- | --- | --- |
| `temperatures_k` | [250 … 320] | the density-isobar grid |
| `pressure_bar`, `timestep_fs` | 1.0, 0.5 | isobar conditions |
| `steps`, `equilibration_steps` | 100000, 20000 | per-temperature trajectory |
| `barostat` | `mtk` | observable-bearing runs need the canonical integrator, not Berendsen |

## Top level

| Key | Default | Meaning |
| --- | --- | --- |
| `workdir` | `runs/water_tmd` | output directory; overridden by `--workdir` or `CP2K_FORGE_WORKDIR` (point it at scratch on a cluster) |
