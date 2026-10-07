"""Single source of truth for unit conversions at the CP2K <-> MACE boundary.

CP2K reports energies in Hartree, forces in Hartree/Bohr, and the analytical
stress tensor in GPa. MACE training data uses eV, eV/Angstrom, and eV/Angstrom^3.
Every conversion in the pipeline goes through the constants and helpers here so a
factor is never duplicated (and a round-trip test in the labelling stage pins them).

CODATA 2018 values.
"""

from __future__ import annotations

# Base constants
HARTREE_TO_EV: float = 27.211386245988
BOHR_TO_ANGSTROM: float = 0.529177210903

# Derived
EV_PER_ANGSTROM_TO_HARTREE_PER_BOHR: float = BOHR_TO_ANGSTROM / HARTREE_TO_EV
HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM: float = HARTREE_TO_EV / BOHR_TO_ANGSTROM

# 1 eV/Angstrom^3 = 160.21766208 GPa  (= e * 1e21 / 1.0 ... CODATA)
EV_PER_ANGSTROM3_TO_GPA: float = 160.21766208
GPA_TO_EV_PER_ANGSTROM3: float = 1.0 / EV_PER_ANGSTROM3_TO_GPA


def hartree_to_ev(e_hartree: float) -> float:
    """Total energy: Hartree -> eV."""
    return e_hartree * HARTREE_TO_EV


def force_au_to_ev_per_angstrom(f_au: float) -> float:
    """Force component: Hartree/Bohr -> eV/Angstrom."""
    return f_au * HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM


def stress_gpa_to_ev_per_angstrom3(s_gpa: float) -> float:
    """Stress component: GPa (CP2K analytical stress) -> eV/Angstrom^3."""
    return s_gpa * GPA_TO_EV_PER_ANGSTROM3
