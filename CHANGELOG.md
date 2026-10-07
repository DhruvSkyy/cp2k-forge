# Changelog

## 0.1.0 (2026-10-06)

First standalone release, extracted from the `tools/mace-distill` directory of the
cp2k-mlp development fork (branch `mace-distill-pipeline`).

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
