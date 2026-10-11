# Installation

CP2K-FORGE is a pure-Python package. Two installs are involved: the Python side (this
page) and a CP2K binary for DFT labelling
([CP2K as a dependency](cp2k-dependency.md) — not needed for the mock self-test or for a
GPU train-only node).

## The short version

```bash
git clone https://github.com/DhruvSkyy/cp2k-forge.git
cd cp2k-forge
./install.sh            # venv + pip install -e ".[train,plot]"
. venv/bin/activate
cp2k-forge --check      # verify everything before spending compute
```

`install.sh` is safe on an HPC login node: no sudo, no module assumptions, idempotent
(it reuses an existing `venv/`).

## Into your own environment

```bash
pip install -e ".[train,plot]"
```

## Extras

The core package is deliberately **torch-free** so the preflight doctor, config
validation, CP2K input rendering and the parser tests run anywhere, even before the
heavy dependencies are installed.

| Extra | Pulls in | Needed for |
| --- | --- | --- |
| *(core)* | numpy, pyyaml, ase, scikit-learn | config load, `--check`, CP2K I/O, tests |
| `[train]` | mace-torch (and torch), torch-dftd | MD generation, training, validation, the mock self-test |
| `[plot]` | matplotlib | validation and showcase figures (skipped with a note if absent) |
| `[docs]` | mkdocs-material, mkdocstrings | building this documentation site |

## GPU nodes: pick the torch wheel explicitly

A mismatched torch/CUDA wheel is the most common GPU install failure, so the CUDA build
is **explicit, never guessed**:

```bash
./install.sh --cuda cu124     # CUDA 12.4 wheel, pick the tag matching your driver
./install.sh --gpu            # probes nvidia-smi and prints the matching --cuda hint
./install.sh --cpu            # force the CPU-only wheel
```

Tags are listed at [pytorch.org/get-started](https://pytorch.org/get-started/locally/).
The chosen torch wheel is installed *last* so the requirements resolution cannot clobber
it.

## Python version

Python 3.9 or newer. The doctor (`cp2k-forge --check`) verifies this along with every
other prerequisite and prints an exact fix for anything missing.
