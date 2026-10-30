# Changelog

## Unreleased

- The own-MD stability check now applies to any chemistry: `validate.stability_min_any_ang`
  (default 0.5 Å) bounds the closest approach of any two atoms. Before, a system without
  oxygen passed the check without testing anything. The O-O / O-H floors still apply
  when O and H are present.
- Loading a config now fails when `explore.decorrelation_observable` is `hbond` and the
  system has no oxygen, with a hint to use `energy`.
- New docs page, *Use it on your own system*.

## 0.1.0 (2026-10-10)

First standalone release, extracted from the `tools/mace-distill` directory of the
cp2k-mlp development fork (branch `mace-distill-pipeline`).

- Hybrid revPBE0-D3 labelling path: `dft.mode: hybrid` renders ADMM + truncated-Coulomb
  HFX inputs (two new package templates), with legality guards at config load and per
  labelled frame; the GGA default stays byte-identical, locked by golden-fixture tests.
  `configs/water_hybrid.yaml` carries the production level on the shipped
  `examples/water64.xyz` seed. The doctor's data check adds `BASIS_ADMM` + `t_c_g.dat`
  conditional on the mode.
- Documentation site (MkDocs Material, `mkdocs serve`, strict-built in CI, dispatch-gated
  Pages deploy): getting-started, full configuration reference, hybrid-DFT guide,
  validation/convergence methodology, HPC guide, troubleshooting, CLI and API reference,
  and case studies reproducing the report's water and fluoride campaigns with vendored
  figures and raw data (CC BY 4.0, `docs/assets/README.md` manifest). `CITATION.cff`
  added.
- `dft.vdw: dftd3 | none`: dispersion-free labelling levels are now expressible (the
  vdW section is stripped from all rendered inputs); the default rendering is unchanged.
- `cp2k-forge --version`, `cp2k_forge.__version__`, and the package version in the
  doctor header; `[project.urls]` in the package metadata.
- Showcase claim hygiene: the experimental 277 K overlay in `plot_tmd.py` is opt-in
  (`--mark-expt`), and `density_tmd.py` reports against the functional's own literature
  value by default.
- Release asset: `water64_pass6_stagetwo.model`, the final model of the semi-local
  `water64_tmd` campaign (see the docs' provenance page for its honest caveats).

- Renamed throughout: package `macedistill` -> `cp2k_forge`, pip name `cp2k-forge`,
  CLI `cp2k-forge` (was `python -m run`), environment variables
  `MACE_DISTILL_WORKDIR` -> `CP2K_FORGE_WORKDIR` and
  `MACE_DISTILL_SKIP_CHECK` -> `CP2K_FORGE_SKIP_CHECK`.
- Packaged as an installable Python project (src layout, `pyproject.toml`,
  console script, `.inp` templates shipped as package data).
- CP2K is now a pure runtime dependency: relative input paths resolve from the
  config file's directory instead of a surrounding CP2K source tree, and
  `CP2K_DATA_DIR` is derived from the CP2K binary's install layout when unset
  (export it to override). The preflight (`cp2k-forge --check`) reports the exact
  binary and data directory the label stage will use.
- Ships `examples/water32.xyz` (32-water cubic box) so the configs are
  self-contained; `mace-torch` is a floor (`>=0.3.16`), no longer a pin.
