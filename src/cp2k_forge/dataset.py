"""The training dataset: one append-only extended-XYZ file as the single source of truth.

Frames carry the MACE reference-key schema in their `info`/`arrays`:
    info["REF_energy"]   total energy, eV
    arrays["REF_forces"] per-atom forces, eV/Angstrom  (N x 3)
    info["REF_stress"]   stress, eV/Angstrom^3, Voigt-6 (xx, yy, zz, yz, xz, xy)
    info["config_type"]  provenance tag (e.g. "explore_pass1_T270")

Structures are de-duplicated by a hash of (rounded positions, cell, symbols) so the
same snapshot is never labelled or trained on twice across passes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

# MACE-standard key names — keep these in lock-step with TrainConfig.*_key.
ENERGY_KEY = "REF_energy"
FORCES_KEY = "REF_forces"
STRESS_KEY = "REF_stress"


def structure_hash(atoms) -> str:
    """Stable content hash of a structure (positions + cell + symbols).

    Rounded to 1e-4 Angstrom so floating-point noise from different code paths does
    not defeat de-duplication.
    """
    import numpy as np

    pos = np.round(atoms.get_positions(), 4)
    cell = np.round(atoms.get_cell().array, 4)
    syms = "".join(atoms.get_chemical_symbols())
    h = hashlib.sha1()
    h.update(syms.encode())
    h.update(pos.tobytes())
    h.update(cell.tobytes())
    return h.hexdigest()[:16]


def read_frames(path: str | Path) -> list:
    """Read all frames from an extended-XYZ file (empty list if missing)."""
    from ase.io import read

    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    frames = read(str(p), index=":")
    return frames if isinstance(frames, list) else [frames]


def existing_hashes(path: str | Path) -> set[str]:
    """Hashes of every frame already in `path` (for dedup before appending)."""
    return {structure_hash(a) for a in read_frames(path)}


def append_frames(
    path: str | Path, frames: Iterable, dedup_against: set[str] | None = None
) -> int:
    """Append frames to the dataset, skipping duplicates. Returns the count written.

    `dedup_against` lets the caller pass a precomputed hash set (e.g. the whole
    dataset) so repeated appends in one pass do not re-read the file each time.
    """
    from ase.io import write

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    seen = set(dedup_against) if dedup_against is not None else existing_hashes(p)

    to_write = []
    for atoms in frames:
        h = structure_hash(atoms)
        if h in seen:
            continue
        seen.add(h)
        to_write.append(atoms)

    if to_write:
        write(str(p), to_write, format="extxyz", append=p.exists())
    return len(to_write)


def has_labels(
    atoms, energy_key: str = ENERGY_KEY, forces_key: str = FORCES_KEY
) -> bool:
    """True if a frame already carries DFT labels (energy + forces)."""
    return energy_key in atoms.info and forces_key in atoms.arrays


def split_train_valid(path: str | Path, valid_fraction: float, seed: int = 0):
    """Deterministic train/validation split of a labelled dataset.

    Returns (train_frames, valid_frames). The split is seeded so a resumed run
    reproduces the same partition.
    """
    import random

    frames = [a for a in read_frames(path) if has_labels(a)]
    rng = random.Random(seed)
    rng.shuffle(frames)
    n_valid = max(1, int(round(valid_fraction * len(frames)))) if frames else 0
    return frames[n_valid:], frames[:n_valid]
