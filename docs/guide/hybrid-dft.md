# Hybrid DFT (revPBE0-D3)

`dft.mode: hybrid` labels at a hybrid-functional level — a PBE-family GGA exchange
scaled down by the exact-exchange fraction, plus Hartree-Fock exchange evaluated under
ADMM with a truncated Coulomb operator. With the defaults this is **revPBE0-D3**
(`functional: revPBE` + `hf_fraction: 0.25`), the level of theory of both
[case-study campaigns](../case-studies/index.md). `mode: gga` (the default) keeps the
semi-local path byte-identical — locked by a golden-fixture test.

`configs/water_hybrid.yaml` carries the production level verbatim on the shipped
64-water cell.

## What the template renders

`cp2k_forge/templates/dft_singlepoint_hybrid.inp`, filled by
`cp2k_io.write_singlepoint_input`, differs from the GGA template in five places:

1. **Dual basis files.** `BASIS_SET_FILE_NAME BASIS_MOLOPT` *and*
   `BASIS_SET_FILE_NAME BASIS_ADMM` — every kind gets its orbital basis plus a
   `BASIS_SET AUX_FIT` auxiliary basis (default `cpFIT3`, per-element override via
   `admm_basis_overrides`).
2. **The ADMM section.** `&AUXILIARY_DENSITY_MATRIX_METHOD` with `BASIS_PROJECTION`,
   your `ADMM_PURIFICATION_METHOD` (default `MO_DIAG`), `EXCH_SCALING_MODEL NONE` and
   `EXCH_CORRECTION_FUNC` (default `PBEX`).
3. **Scaled GGA exchange.** `&PBE PARAMETRIZATION {functional}` with
   `SCALE_X = 1 − hf_fraction`. The scale is **always derived** — there is deliberately
   no second knob to set inconsistently.
4. **Exact exchange.** `&HF` with `FRACTION {hf_fraction}`, Schwarz screening
   (`EPS_SCHWARZ`), a per-rank memory cap (`&MEMORY MAX_MEMORY`), and
   `POTENTIAL_TYPE TRUNCATED` with `CUTOFF_RADIUS {hfx_cutoff_radius_ang}` and
   `T_C_G_DATA t_c_g.dat`.
5. **`CHARGE {charge}`** rendered directly (the GGA path injects it only when nonzero).

D3 dispersion keeps the same block as GGA but `dispersion_ref` must name the **hybrid**
functional (`revPBE0`), because the D3 damping parameters are fitted per functional —
setting the GGA base name here is the easiest mistake to make at this level.

## Truncated-Coulomb legality

A truncated Coulomb operator is only well-defined when the cutoff sphere fits inside the
minimum image: **`hfx_cutoff_radius_ang < min(cell)/2` for every frame that is ever
labelled**. The radius is part of the level of theory — never change it mid-campaign.
Three guards enforce this:

- at config load, against the seed cell (`Config.validate`);
- at config load, against the **NPT density ceiling**: at `explore.density_max_gcc` a
  cubic cell shrinks to `L_seed / density_max^(1/3)`, and frames beyond `2 × radius`
  would be unlabelable — the combination is rejected before any MD is run;
- per frame at render time (`cp2k_io._check_hfx_radius`): NPT-explored candidates carry
  their own compressed cells, and failing loud beats silently varying the interaction
  potential between training points.

This is also why the hybrid example uses the 64-water box (12.43 Å, L/2 = 6.22 Å > the
5.5 Å production radius): the 32-water box (L/2 = 4.93 Å) cannot legally carry it.

## Charged cells and E0 references

For an ionic system set `dft.charge` (e.g. −1 for one fluoride in water); the net charge
is compensated by the GPW background. The isolated-atom E0 references **stay neutral by
design** — the atom template hardcodes `CHARGE 0`. The box's net charge is a per-frame
constant absorbed into the ion's E0 up to an offset, because the solute count is fixed
across every frame. For anions, give the ion a diffuse auxiliary basis:

```yaml
dft:
  charge: -1
  admm_basis_overrides: {F: aug-cpFIT3}
```

## No stress at this level

The hybrid templates deliberately print **no stress tensor** (the HFX/ADMM stress path
is version-fragile across CP2K releases; the parser tolerates the missing block). Keep
`train.stress_weight: 0` in hybrid campaigns — and read the
[physics caveat](../about/method.md#a-physics-caveat-worth-stating) about what
force-only training does and does not pin down.

## Data files and cost

The hybrid level additionally needs `BASIS_ADMM` and `t_c_g.dat` in the CP2K data
directory; both ship with every standard CP2K distribution, and
`cp2k-forge --check --config configs/water_hybrid.yaml` verifies them
([details](../getting-started/cp2k-dependency.md)).

Budget accordingly: one hybrid single point on the 192-atom water cell costs about
**10.2 Ice Lake core-hours** (12.3 for the 193-atom fluoride cell), versus ~0.95 core-h
for the semi-local level — roughly **13× cheaper per label**. Hybrid points also want
wider runs (`cp2k_ranks: 32` in the production config) and benefit from a larger
`hfx_max_memory_mb` on fat nodes, which caches more integrals and cuts HFX
recomputation. Full cost ledger: [Cost and data efficiency](../case-studies/cost.md).
