"""Load and sanity-check the campaign seed structure (single authority).

The driver, cp2k_forge.validate and the showcase all need the seed box; previously each carried its
own loader, which applied `system.cell_abc` unconditionally — a wrong value silently
rescaled the density of every MD segment. This loader cross-checks the config cell against
any cell already present in the seed file and reports the seed density at startup, so a
box mismatch is caught immediately instead of surfacing as a small density bias later.
"""

from __future__ import annotations


def density_gcc(atoms) -> float:
    """Mass density of a structure in g/cm^3."""
    import numpy as np

    amu_to_g = 1.66053906660e-24
    ang3_to_cm3 = 1.0e-24
    return (float(np.sum(atoms.get_masses())) * amu_to_g) / (
        atoms.get_volume() * ang3_to_cm3
    )


def load_seed(cfg, verbose: bool = False):
    """Load the seed structure with `system.cell_abc` applied.

    If the seed file carries its own lattice (extxyz), it must agree with the config to
    within 1e-3 Angstrom — refusing to silently rescale is the point. Plain-xyz seeds
    (no lattice) take the config cell as before.
    """
    import numpy as np
    from ase.io import read

    seed_path = cfg.resolve_path(cfg.system.seed_xyz)
    atoms = read(str(seed_path), index=0)

    file_cell = atoms.get_cell()
    if file_cell.rank == 3:
        lengths = np.asarray(file_cell.lengths(), dtype=float)
        target = np.asarray(cfg.system.cell_abc, dtype=float)
        delta = float(np.max(np.abs(lengths - target)))
        if delta > 1e-3:
            raise ValueError(
                f"{seed_path}: file cell {[round(float(x), 4) for x in lengths]} A "
                f"disagrees with system.cell_abc {cfg.system.cell_abc} "
                f"(max delta {delta:.4f} A). Fix the config (paste the cell the seed "
                "generator printed) or regenerate the seed; refusing to silently rescale."
            )
    atoms.set_cell(cfg.system.cell_abc)
    atoms.set_pbc(True)
    if verbose:
        print(
            f"  seed: {len(atoms)} atoms, cell "
            f"{[round(float(c), 4) for c in cfg.system.cell_abc]} A, "
            f"density {density_gcc(atoms):.4f} g/cm^3"
        )
    return atoms
