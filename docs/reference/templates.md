# Input templates

The `.inp` files under `src/cp2k_forge/templates/` are complete CP2K inputs with
`{placeholder}` fields, shipped as package data and rendered by `cp2k_forge.cp2k_io`
(`str.format`, no templating engine). Users can read exactly what every DFT label ran:
the rendered input sits next to each log in the per-frame run directory
(`<workdir>/dft/<hash>/dft.inp`).

Placeholders common to the DFT templates, filled from the structure and `dft:` config:
`{project}`, `{abc}` (cell lengths), `{coord_block}`, `{kind_blocks}` (per-element
`&KIND` sections: orbital basis + pseudopotential, plus an `AUX_FIT` line in hybrid
mode), `{cutoff}`, `{rel_cutoff}`, `{eps_scf}`, `{max_scf}`, `{functional}`,
`{dispersion_ref}`, `{d3_suffix}` (empty for zero damping, `(BJ)` for Becke-Johnson).

## `dft_singlepoint.inp` — the GGA labelling workhorse

Rendered by `write_singlepoint_input` for `dft.mode: gga`. A Quickstep `ENERGY_FORCE`
single point with `STRESS_TENSOR ANALYTICAL` (the stress feeds `REF_stress` when
present), OT SCF, and D3 dispersion referenced to `{dispersion_ref}`. A nonzero
`dft.charge` is post-injected as a `CHARGE` line; `charge: 0` leaves the rendered text
byte-identical to the chargeless original (locked by a golden-fixture test).

## `dft_singlepoint_hybrid.inp` — the ADMM/HFX labelling input

Rendered for `dft.mode: hybrid`. Adds, over the GGA template: the dual basis files
(`BASIS_MOLOPT` + `BASIS_ADMM`), the `&AUXILIARY_DENSITY_MATRIX_METHOD` section
(`{admm_purification}`, `{admm_exch_correction_func}`, `EXCH_SCALING_MODEL NONE`),
scaled GGA exchange (`SCALE_X {gga_x_scale}` = 1 − hf_fraction), the `&HF` section
(`FRACTION {hf_fraction}`, `EPS_SCHWARZ {eps_schwarz}`,
`MAX_MEMORY {hfx_max_memory}`, `POTENTIAL_TYPE TRUNCATED` with
`CUTOFF_RADIUS {hfx_cutoff_radius}` and `T_C_G_DATA t_c_g.dat`), and a directly rendered
`CHARGE {charge}`. **No stress print** — the HFX/ADMM stress path is version-fragile
across CP2K releases, and the parser tolerates the missing block
([consequences](../guide/hybrid-dft.md#no-stress-at-this-level)). The render is guarded
by the per-frame truncated-Coulomb legality check.

## `dft_atom.inp` / `dft_atom_hybrid.inp` — isolated-atom E0 references

Rendered by `write_atom_input` once per element and campaign. Siblings of the
single-point templates rather than edits of them: they add `UKS` +
`MULTIPLICITY {multiplicity}` (open-shell atoms: H doublet, O triplet, F doublet) and
drop the stress, while functional, D3, basis and cutoffs stay at the **exact labelling
level**, so the E0s are consistent with the dataset energies. Both hardcode `CHARGE 0`:
E0 references stay neutral even for a charged box
([why](../guide/hybrid-dft.md#charged-cells-and-e0-references)).

## `aimd_reference.inp` — the optional AIMD validation reference

Rendered by `write_aimd_input` when you want an in-house ab initio RDF/VDOS reference:
Born-Oppenheimer NVT MD at the labelling level with a Nosé-Hoover thermostat, ASPC
wavefunction extrapolation and an MD-appropriate looser SCF; positions/velocities
printed every `{sample_every}` steps (→ RDF / VDOS references), with an optional
`&EXT_RESTART` block so a multi-day AIMD survives walltime caps as a restart chain.

## `md_backend.inp` — the optional in-CP2K MD path

The template for running trained-model MD *inside* CP2K
(`generator.engine: cp2k-backend`). It requires a metatomic-enabled CP2K build, which is
a separate contribution; selecting the engine without one raises an actionable error,
and no code in this package renders this template in the default configuration.
