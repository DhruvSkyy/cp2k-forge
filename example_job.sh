#!/bin/bash
# Generic batch-job template for a cp2k-forge campaign. This is deliberately
# scheduler-agnostic: it contains no site-specific account, partition, module, or
# path. Adapt the marked lines to your machine (SLURM/PBS/LSF/local) and submit.
#
# The pipeline itself is portable — everything machine-specific is passed through the
# environment variables below, so the same configs/water.yaml runs unchanged anywhere.
#
# --- adapt to your scheduler (examples shown as comments) -------------------------
#   SLURM:  #SBATCH --account=<ACCOUNT>
#           #SBATCH --partition=<PARTITION>
#           #SBATCH --nodes=1
#           #SBATCH --time=24:00:00
#   then run:  sbatch example_job.sh
# ---------------------------------------------------------------------------------
set -euo pipefail

# 1. Python environment with the pipeline dependencies (see requirements.txt).
#    e.g.  source /path/to/venv/bin/activate

# 2. CP2K for DFT labelling. Point these at your build and data files. CP2K_DATA_DIR
#    may stay unset for a standard install: a data directory next to the binary's
#    install tree is derived automatically (the --check preflight reports which).
export CP2K_BIN="${CP2K_BIN:-cp2k.psmp}"          # path to the CP2K binary
#export CP2K_DATA_DIR=/path/to/cp2k/data          # BASIS_MOLOPT, GTH_POTENTIALS, dftd3.dat
export CP2K_MPI_LAUNCHER="${CP2K_MPI_LAUNCHER:-mpirun}"    # or "none" for an OMP-only build
export CP2K_RANKS="${CP2K_RANKS:-4}"              # MPI ranks per DFT single point

# 3. Where outputs land. Prefer scratch/large storage over a home quota.
export CP2K_FORGE_WORKDIR="${CP2K_FORGE_WORKDIR:-$PWD/runs/water}"

# 4. Run the campaign. It is resumable: re-running continues from the last completed
#    stage recorded in <workdir>/manifest.json. The driver runs the preflight check
#    automatically and aborts before compute if anything is missing; run it up front
#    too so a misconfigured job fails in seconds, not hours.
cd "$(dirname "$0")"
cp2k-forge --check --config configs/water.yaml
cp2k-forge --config configs/water.yaml

# Split CPU labelling from GPU training across two jobs by adding, per stage:
#   cp2k-forge --config configs/water.yaml --stop-after label   # on a CPU node
#   cp2k-forge --config configs/water.yaml                      # on a GPU node
