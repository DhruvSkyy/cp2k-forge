# CP2K-FORGE

[![ci](https://github.com/DhruvSkyy/cp2k-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/DhruvSkyy/cp2k-forge/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

Train a small, fast [MACE](https://github.com/ACEsuit/mace) potential for your own
system, using only [CP2K](https://www.cp2k.org) DFT labels.

You describe the system in one YAML file. A foundation model (such as MACE-MP-0) runs
short MD to propose structures, CP2K computes a DFT single point on a few of them, and a
compact MACE is trained from scratch on those labels. The loop repeats until extra labels
stop improving the model. The foundation model's own energies are never used, so the
final potential matches the DFT level you chose, and no ab initio MD is needed.

**Documentation: https://www.dhruvs.com/cp2k-forge/**

```
   +---------------------- next pass -----------------------+
   v                                                        |
 SAMPLE ----> SELECT ----> LABEL -----> TRAIN ----> VALIDATE --+--> done
 short MD     decorrelated  CP2K single  compact     held-out forces,
 (foundation  frames        points       MACE        own-MD stability,
  model, then                                        stop rule
  your model)
```

## Install

```bash
git clone https://github.com/DhruvSkyy/cp2k-forge.git
cd cp2k-forge
./install.sh              # creates venv/ and installs ".[train,plot]"
. venv/bin/activate
```

Or into your own environment: `pip install -e ".[train,plot]"`. On a GPU node pass the
CUDA wheel tag for your driver, e.g. `./install.sh --cuda cu124`. The package is not on
PyPI yet.

## Try it in two minutes

No CP2K or GPU needed. The smoke config replaces DFT with mock labels so you can check
the whole loop runs:

```bash
cp2k-forge --check                         # environment preflight, with fixes
cp2k-forge --config configs/smoke.yaml     # one tiny pass, mock labels
```

Mock labels test the plumbing only, never the science.

## Run a real campaign

```bash
export CP2K_BIN=/path/to/cp2k.psmp
cp2k-forge --config configs/water.yaml          # semi-local revPBE-D3 water
cp2k-forge --config configs/water_hybrid.yaml   # hybrid revPBE0-D3 water
```

For any other system, copy a config and follow
[Use it on your own system](https://www.dhruvs.com/cp2k-forge/getting-started/your-system/).
You will change the `system` and `dft` blocks and a few defaults that were tuned for
water.

Runs are resumable: state lives in `<workdir>/manifest.json`, and finished DFT points are
keyed by structure hash, so a killed job continues where it stopped. Use
`--stop-after label` to run CPU labelling and GPU training as separate jobs;
`example_job.sh` is a scheduler-neutral batch template.

## CP2K

CP2K is run as a subprocess on generated input files and is never linked. Any recent
build with libdftd3 works (conda-forge, distro packages, the official container, or your
cluster's module). Machine-specific settings come from environment variables, so one
config runs anywhere:

| Variable | Purpose |
| --- | --- |
| `CP2K_BIN` | CP2K binary for labelling (default `cp2k.psmp` on `PATH`) |
| `CP2K_DATA_DIR` | basis and potential files; usually derived from the binary |
| `CP2K_MPI_LAUNCHER` | `mpirun` (default) or `none` for an `.ssmp` build |
| `CP2K_RANKS`, `CP2K_OMP_THREADS` | MPI ranks and threads per single point |
| `CP2K_FORGE_WORKDIR` | output directory; use scratch, not a home quota |

`cp2k-forge --check` prints the binary and data directory a run will use.

## Results

Tested on two aqueous systems at hybrid revPBE0-D3 against a published committee
potential at the same level: bulk water with 89 labels (committee: 814; force RMSE 53.3
vs 64.6 meV/Å on shared frames) and fluoride in water with 64 labels (committee: 299;
57.7 vs 69.4 meV/Å). These are worked examples, not a transferability claim. Details,
figures and raw data are on the
[Results pages](https://www.dhruvs.com/cp2k-forge/case-studies/).

## Citing

Use the "Cite this repository" button (from `CITATION.cff`). The method and results are
described in D. Sharma, *Machine-Learned Interatomic Potentials in CP2K*, MPhil thesis,
University of Cambridge, 2026.

## Development

```bash
pip install -e ".[train,plot,docs]" pytest black
pytest                    # torch-free unit tests
black --check .
sphinx-build -M dirhtml docs docs/_build -W --keep-going
```

CI runs the tests on Python 3.10 and 3.12 and a strict docs build on every push.

## License

Code: MIT. Figures and data under `docs/assets/`: CC BY 4.0.
