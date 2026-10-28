# CP2K as a dependency

CP2K-FORGE treats CP2K the way a build system treats a compiler: a **runtime
dependency** that is executed, never imported or linked. Understanding this one page is
understanding how the whole integration works.

## The mechanism

For every structure that needs a label, the pipeline:

1. **renders a CP2K input file** from a template shipped inside the package
   (`cp2k_forge/templates/dft_singlepoint.inp`, or the hybrid variant when
   `dft.mode: hybrid`), the structure's coordinates and cell plus your `dft:` settings
   become a complete Quickstep `ENERGY_FORCE` input;
2. **runs the CP2K binary as a subprocess** in a per-structure scratch directory,
   normally under an MPI launcher:
   `mpirun -np <ranks> <cp2k binary> -i dft.inp -o dft.out`;
3. **parses the log** (`cp2k_forge.cp2k_io.parse_singlepoint_output`) and converts the
   energy, forces and (GGA only) stress from CP2K's Hartree / Hartree-Bohr⁻¹ units to
   the eV-based units MACE trains on; all conversions live in one module,
   `cp2k_forge/units.py`, pinned by a torch-free regression test.

Because the coupling is subprocess-plus-files, **any working CP2K binary works**: there
is no version pin, no Python bindings, no shared-library linkage. The pipeline and CP2K
can even live in different software stacks (a venv and a site module, say).

## How the binary is found

One resolution policy lives in `cp2k_forge/cp2k_env.py`, and the preflight doctor
reports exactly what the label stage will use:

1. `$CP2K_BIN`, if set (absolute path or a name on `PATH`);
2. else the config's `dft.cp2k_bin` (default `cp2k.psmp`), looked up on `PATH`.

There is deliberately **no automatic substitution between variants**: `cp2k.psmp` (MPI)
and `cp2k.ssmp` (OpenMP-only) need different launch commands, so silently swapping one
in would run the DFT incorrectly. If the configured binary is missing, the doctor
instead *reports* any variant it finds on `PATH` as the suggested fix.

## How the data directory is found

CP2K resolves bare data-file names (`BASIS_MOLOPT`, `GTH_POTENTIALS`, `dftd3.dat`)
against `CP2K_DATA_DIR`. The pipeline resolves that directory as:

1. `$CP2K_DATA_DIR`, if set;
2. else **derived from the resolved binary's location**, probing the two standard
   layouts: an installed prefix (`<prefix>/bin/cp2k.psmp` →
   `<prefix>/share/cp2k/data`) and a source tree (`<root>/exe/<arch>/cp2k.psmp` →
   `<root>/data`).

A derived directory is exported into the CP2K subprocess environment automatically, so
**a standard CP2K install needs zero environment setup**. The doctor's `cp2k:data` row
shows which path won and whether it was derived.

### Data files by labelling level

| `dft.mode` | Files required in the data directory |
| --- | --- |
| `gga` (default) | `BASIS_MOLOPT`, `GTH_POTENTIALS`, `dftd3.dat` |
| `hybrid` | the above plus `BASIS_ADMM` (auxiliary bases) and `t_c_g.dat` (truncated-Coulomb data) |

All five ship in every standard CP2K data directory; the doctor checks the set matching
your config.

## The environment variables

Everything machine-specific is passed by environment, so the same YAML runs unchanged on
a laptop or any cluster:

| Variable | Purpose | Default |
| --- | --- | --- |
| `CP2K_BIN` | the CP2K binary for DFT labelling | `dft.cp2k_bin` (`cp2k.psmp` on PATH) |
| `CP2K_DATA_DIR` | directory with the data files above | derived from the binary |
| `CP2K_MPI_LAUNCHER` | `mpirun`, or `none` for an OpenMP-only `.ssmp` build | `mpirun` |
| `CP2K_RANKS` | MPI ranks per single point | `dft.cp2k_ranks` |
| `CP2K_OMP_THREADS` | OpenMP threads per rank | auto from the allocated cores |
| `CP2K_FORGE_WORKDIR` | output directory (prefer scratch) | the config's `workdir` |
| `CP2K_FORGE_SKIP_CHECK` | set to 1 to skip the automatic preflight | unset |

Two subtleties the pipeline handles for you (see `cp2k_forge.label`):

- **Thread sanity.** The driver imports torch, which leaves the process at
  `OMP_NUM_THREADS=1` and may pin CPU affinity; inherited by CP2K that means a 4-rank
  job runs on 4 cores. The subprocess environment restores a sane per-rank thread count
  (`allocated cores / (ranks × workers)`, SLURM-aware) and widens affinity back to the
  allocation.
- **Concurrent labelling.** `dft.label_workers > 1` runs several independent CP2K single
  points side by side on one node. A 192-atom point stops scaling near ~16 cores, so a
  few modest-width frames beat one node-wide run by 3-4×.

## Installing CP2K

Any route works; pick whatever your machine prefers:

- conda-forge: `conda install -c conda-forge cp2k`
- Linux distros: `apt install cp2k` / `dnf install cp2k`
- containers: `docker pull cp2k/cp2k`
- HPC: your site's module (`module load cp2k`), or
  [build from source](https://github.com/cp2k/cp2k/blob/master/INSTALL.md)

Then `cp2k-forge --check --config <your config>` confirms the binary answers
`--version`, the data files are reachable, and (for `mode: hybrid`) the ADMM files are
present, before any compute is spent.

:::{admonition} Which stages actually need CP2K
:class: note

Only labelling does (and the isolated-atom E0 references, computed during the label
stage). A GPU train-only invocation (`--stop-after` splitting, see
[Campaigns on HPC](../guide/campaigns-hpc.md)) is not failed for lacking CP2K, and
the mock self-test never touches it.
:::
