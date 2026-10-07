#!/usr/bin/env python3
"""Round-trip test for the DFT-label parser (the labelling stage's verification gate).

Feeds a known CP2K single-point log to cp2k_forge.cp2k_io.parse_singlepoint_output and
checks that the recovered energy, forces and stress match the expected values in MACE
units. This pins the unit conversions in cp2k_forge/units.py and the two supported CP2K
force-block formats. It needs neither mace-torch, a GPU, nor network access, so it runs
anywhere and in CI. Run directly (`python test_cp2k_io.py`) or under pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Prefer the checkout's sources so the test also runs directly from a clone
# (`python tests/test_cp2k_io.py`) without an installed package.
sys.path.insert(0, str(REPO_ROOT / "src"))

from cp2k_forge.cp2k_io import parse_singlepoint_output  # noqa: E402

# Independent CODATA constants (deliberately duplicated here so the test fails if the
# constants in cp2k_forge/units.py ever drift).
HARTREE_TO_EV = 27.211386245988
BOHR_TO_ANGSTROM = 0.529177210903
FORCE_AU_TO_EV_ANG = HARTREE_TO_EV / BOHR_TO_ANGSTROM
GPA_TO_EV_ANG3 = 1.0 / 160.21766208

# Reference CP2K logs, stored with a .out.ref suffix so no ignore rule for
# *.out/*.log scratch files can ever drop the fixtures.
LOG = REPO_ROOT / "tests" / "data" / "singlepoint_h2.out.ref"  # new FORCES|/[bar]
LOG_OLD = (
    REPO_ROOT / "tests" / "data" / "singlepoint_old_format.out.ref"
)  # old ATOMIC FORCES/[GPa]


def _close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(b))


def test_parse_singlepoint_output() -> None:
    result = parse_singlepoint_output(LOG)

    # Energy: Hartree -> eV.
    expected_energy = -17.123456789012 * HARTREE_TO_EV
    assert _close(result["energy_ev"], expected_energy), result["energy_ev"]

    # Forces: two atoms, Hartree/Bohr -> eV/Angstrom, equal and opposite.
    assert len(result["forces"]) == 2, result["forces"]
    f0 = [c * FORCE_AU_TO_EV_ANG for c in (0.001, 0.002, -0.003)]
    for got, exp in zip(result["forces"][0], f0):
        assert _close(got, exp), (got, exp)
    for got, exp in zip(result["forces"][1], f0):
        assert _close(got, -exp), (got, exp)

    # Stress: 1e4 bar = 1 GPa on the diagonal, sign-flipped to the ASE/MACE convention.
    stress = result["stress"]
    assert stress is not None and len(stress) == 6, stress
    diag = -1.0 * GPA_TO_EV_ANG3
    for got in stress[:3]:
        assert _close(got, diag), (got, diag)
    for got in stress[3:]:
        assert _close(got, 0.0), got


def test_parse_old_format() -> None:
    """The older 'ATOMIC FORCES in [a.u.]' force block and the [GPa] stress header path."""
    result = parse_singlepoint_output(LOG_OLD)

    assert _close(result["energy_ev"], -34.246913578024 * HARTREE_TO_EV), result[
        "energy_ev"
    ]

    assert len(result["forces"]) == 2, result["forces"]
    f0 = [c * FORCE_AU_TO_EV_ANG for c in (0.001, 0.002, -0.003)]
    for got, exp in zip(result["forces"][0], f0):
        assert _close(got, exp), (got, exp)
    for got, exp in zip(result["forces"][1], f0):
        assert _close(got, -exp), (got, exp)

    # Stress header is [GPa] here (to_gpa=1.0): 1 GPa diagonal, sign-flipped.
    stress = result["stress"]
    assert stress is not None and len(stress) == 6, stress
    diag = -1.0 * GPA_TO_EV_ANG3
    for got in stress[:3]:
        assert _close(got, diag), (got, diag)
    for got in stress[3:]:
        assert _close(got, 0.0), got


if __name__ == "__main__":
    test_parse_singlepoint_output()
    test_parse_old_format()
    print(
        "OK: parse_singlepoint_output round-trips energy, forces and stress "
        "(new FORCES|/[bar] and old ATOMIC FORCES/[GPa] formats)"
    )
