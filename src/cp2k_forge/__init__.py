"""cp2k_forge — building blocks for the domain-specific MACE pipeline.

The pipeline turns a MACE foundation model into a small, system-specific MACE by
using the foundation model only as a structure generator: it runs MD to explore
configuration space, labels selected snapshots with CP2K DFT, and trains a fresh
MACE from scratch on those labels. The loop repeats for a few passes (with the
latest trained model as the explorer) until the held-out error and the target
property stop moving.

Modules:
    units      unit conversions (CP2K <-> MACE)
    config     YAML campaign-config loader + validation
    dataset    extended-XYZ dataset with the MACE reference-key schema
    manifest   resumable run-state machine
    cp2k_env   locates the CP2K binary + data directory (the runtime dependency)
    cp2k_io    CP2K input templating + output parsing
    label      DFT single-point labelling stage
    engines    swappable MD engines (ASE+mace-torch by default; optional
               in-CP2K MACE backend, gated behind a metatomic-enabled build)
    generate   structure generation (MD over the T/density grid)
    subsample  diversity-based frame selection
    train      mace-torch from-scratch training wrapper
"""

from importlib.metadata import PackageNotFoundError, version as _dist_version

try:
    __version__ = _dist_version("cp2k-forge")
except PackageNotFoundError:  # a bare checkout on sys.path without an install
    __version__ = "0+unknown"
