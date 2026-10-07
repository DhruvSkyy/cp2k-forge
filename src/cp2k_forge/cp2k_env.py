"""Locate the CP2K installation that the labelling stage will invoke.

CP2K is a runtime dependency of this package: it is never imported or linked, only
executed as a subprocess on the generated input files. One resolution policy lives
here so the preflight (`cp2k_forge.doctor`) reports exactly the binary and data
directory that the label stage (`cp2k_forge.label`) will use.

Binary:   $CP2K_BIN if set, else the configured `dft.cp2k_bin` (default `cp2k.psmp`),
          looked up on PATH. There is deliberately no automatic substitution between
          variants — `cp2k.psmp` (MPI) and `cp2k.ssmp` (OMP-only) need different launch
          commands, so swapping one in silently would run the DFT incorrectly. The
          doctor instead reports any variant it finds on PATH as the suggested fix.

Data dir: $CP2K_DATA_DIR if set, else derived from the resolved binary's location.
          Two standard layouts are probed: an installed prefix
          (`<prefix>/bin/cp2k.psmp` -> `<prefix>/share/cp2k/data`) and a source tree
          (`<root>/exe/<arch>/cp2k.psmp` -> `<root>/data`). A derived directory is
          exported to the CP2K subprocess, which otherwise resolves bare data-file
          names (BASIS_MOLOPT, GTH_POTENTIALS, dftd3.dat) against its temporary cwd.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

CP2K_DATA_FILES = ("BASIS_MOLOPT", "GTH_POTENTIALS", "dftd3.dat")

# Well-known binary names, used only for the doctor's fix hints (never auto-selected).
KNOWN_BINARY_NAMES = ("cp2k.psmp", "cp2k.ssmp", "cp2k", "cp2k.popt", "cp2k.sopt")


def configured_binary(dft=None) -> str:
    """The binary name/path the run is configured to use ($CP2K_BIN wins)."""
    env = os.environ.get("CP2K_BIN")
    if env:
        return env
    return getattr(dft, "cp2k_bin", None) or "cp2k.psmp"


def resolve_binary(dft=None) -> str | None:
    """Resolve the configured binary to an executable path, or None if not found."""
    configured = configured_binary(dft)
    found = shutil.which(configured)
    if found:
        return found
    p = Path(configured)
    return str(p) if p.exists() else None


def binaries_on_path() -> list[str]:
    """Any well-known CP2K binaries present on PATH (for actionable FAIL hints)."""
    return [name for name in KNOWN_BINARY_NAMES if shutil.which(name)]


def _looks_like_data_dir(p: Path) -> bool:
    return p.is_dir() and all((p / f).exists() for f in CP2K_DATA_FILES)


def derive_data_dir(binary: str | None) -> Path | None:
    """Derive the CP2K data directory from the binary's install location, if possible."""
    if not binary:
        return None
    resolved = shutil.which(binary) or binary
    try:
        bin_dir = Path(resolved).resolve().parent
    except OSError:
        return None
    candidates = (
        bin_dir.parent / "share" / "cp2k" / "data",  # <prefix>/bin + <prefix>/share
        bin_dir.parent.parent / "data",  # <root>/exe/<arch> + <root>/data
    )
    for cand in candidates:
        if _looks_like_data_dir(cand):
            return cand
    return None


def resolve_data_dir(dft=None) -> tuple[Path | None, str]:
    """Resolve the data directory: ($CP2K_DATA_DIR | derived-from-binary | None).

    Returns (path, source) with source one of "env", "derived", "". An "env" path is
    returned even if it does not exist, so the caller can report the bad setting
    instead of silently falling back.
    """
    env = os.environ.get("CP2K_DATA_DIR")
    if env:
        p = Path(env)
        return (p.resolve() if p.exists() else p), "env"
    derived = derive_data_dir(resolve_binary(dft))
    if derived is not None:
        return derived, "derived"
    return None, ""
