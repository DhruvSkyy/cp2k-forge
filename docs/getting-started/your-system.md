# Use it on your own system

The shipped configs build water potentials, but the loop itself does not care what the
atoms are. To retarget it you write one new YAML file. This page goes through that file
block by block and points out the defaults that were tuned for water.

Start from a copy:

```bash
cp configs/water.yaml configs/my_system.yaml
```

## What you need

- **A seed structure** in extended XYZ (`system.seed_xyz`). It is required. A short
  equilibrated snapshot at roughly the right density is ideal; it does not have to be
  perfect, because the sampler moves away from it.
- **An orthorhombic cell** (`system.cell_abc`, in Å). Non-orthorhombic cells are not
  supported in v0.1.0.
- **A CP2K level of theory** you trust for the system: functional, dispersion,
  basis set, pseudopotentials and cutoff.
- **A foundation model** that can run sensible MD for the system. Its energies are
  never used for training, so it only has to keep the structure physical.

## The config, block by block

The example below is illustrative (aqueous NaCl). It has not been run as a campaign, so
treat every number as a starting point.

```yaml
system:
  name: nacl_water
  seed_xyz: nacl_water.xyz          # resolved relative to this YAML file
  elements: [Na, Cl, H, O]
  cell_abc: [15.6, 15.6, 15.6]      # orthorhombic, Å

dft:
  mode: gga                         # or hybrid (about 13x more expensive per label)
  functional: revPBE
  vdw: dftd3
  dispersion_ref: revPBE
  basis_set: TZV2P-MOLOPT-GTH       # check every element exists in your basis file
  potential: GTH-PBE
  cutoff_ry: 400.0
  charge: 0                         # net cell charge; lives in dft, not system

generator:
  model: mace-mp-0                  # sampler only
  dispersion: true                  # MP-0 has no dispersion of its own

explore:
  ensemble: NVT
  temperatures_k: [300]
  density_scales: [1.0]
  decorrelation_observable: energy  # hbond only makes sense for water
  density_min_gcc: 0.8              # clamp window: set it around YOUR density
  density_max_gcc: 1.4

subsample:
  method: random
  n_per_pass: 10

validate:
  rdf_pairs: [[O, O], [Na, O], [Cl, O]]
  stability_min_any_ang: 0.5        # closest approach of any two atoms

loop:
  max_passes: 10
  min_rel_improvement_force: 0.05
```

Every key, with its default, is in the [configuration reference](../guide/configuration.md).

### `system`

`elements` must list every element in the seed. `cell_abc` must match the seed's box.
Relative paths resolve from the YAML file's folder, so keep the seed next to the config.

### `dft`

This block is your level of theory and the only source of training data, so choose it
before anything else and do not change it mid-campaign. Things to check:

- the basis set and pseudopotential names exist for every element in your CP2K data
  directory (`cp2k-forge --check` reports missing files);
- `charge` is the net cell charge; a charged cell is neutralised by the GPW background;
- for hybrid labels, `hfx_cutoff_radius_ang` must stay below half the shortest cell
  length, and anions usually want a diffuse ADMM basis
  (`admm_basis_overrides: {F: aug-cpFIT3}`). See [Hybrid DFT](../guide/hybrid-dft.md).

Run one label by hand before a campaign and look at the SCF convergence and the cost per
point. That number sets your whole budget.

### `generator`

Pick a foundation model that covers your chemistry. MACE-MP-0 (with D3) is a reasonable
default for inorganic, ionic and aqueous systems. MACE-OFF is built for neutral organic
molecules and should not be used for charged species. A model path (`.model`) also works.

### `explore`

Three defaults were set for water and need attention:

- `decorrelation_observable` defaults to `hbond`, which counts water hydrogen bonds.
  For any system without oxygen the config refuses to load until you choose `energy`
  (or `density` with NPT).
- `min_sample_every_fs` (1 ps) reflects the water hydrogen-bond lifetime. Lower it if
  your system decorrelates faster.
- `density_min_gcc` / `density_max_gcc` abort trajectories that leave a physical
  density window. The defaults (0.6 to 1.3 g/cm³) suit water; set them around your
  system's density, or an NPT run of a dense material will be aborted on the first frame.
  `compressibility_au` is also water's value.

### `validate`

- `rdf_pairs` defaults to O-O, O-H, H-H. Name the pairs that matter for your system.
- The stability check always applies `stability_min_any_ang` (default 0.5 Å) to the
  closest approach of any two atoms. Systems containing O and H are also held to the
  water floors `stability_min_oo_ang` and `stability_min_oh_ang`; raise or lower those if
  your system has shorter physical O-O contacts.
- RDF and VDOS scores against a reference need a reference trajectory
  (`rdf_ref_xyz`, `vdos_ref_npy`). Without one they are skipped, which is fine.

### `loop`

`min_rel_improvement_force` stops the campaign when a pass improves the held-out force
error by less than that fraction. `max_passes` caps the budget. See
[Validation and gates](../guide/validation.md) for all stop rules and the optional
promotion gate.

## Check before you spend compute

```bash
cp2k-forge --check --config configs/my_system.yaml
cp2k-forge --config configs/my_system.yaml \
  --set explore.steps=4200 --set explore.target_uncorrelated=2 \
  --set loop.max_passes=1 --set subsample.n_per_pass=5 --set subsample.min_frames=1
```

The second command runs one tiny pass with real CP2K labels. If it finishes and the
scorecard in the pass directory looks sane, launch the full campaign
([Campaigns on HPC](../guide/campaigns-hpc.md)).

## What is still water-specific

- The `showcase/` scripts (density isobar and density maximum) assume water.
- The worked examples on the [Results](../case-studies/index.md) pages are both aqueous.
  They show the method works there; your system needs its own validation against data
  you trust.
