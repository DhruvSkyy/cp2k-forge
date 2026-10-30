#!/usr/bin/env python3
"""Stability-check and config-guard tests for systems with and without water.
Needs ase + numpy + pyyaml only (no torch), so it runs anywhere and in CI."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from ase import Atoms

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cp2k_forge.config import Config  # noqa: E402
from cp2k_forge.validate import stability_metrics  # noqa: E402


def _water_dimer() -> Atoms:
    return Atoms(
        "OH2OH2",
        positions=[
            (0.0, 0.0, 0.0),
            (0.96, 0.0, 0.0),
            (-0.24, 0.93, 0.0),
            (2.9, 0.0, 0.0),
            (3.86, 0.0, 0.0),
            (2.66, 0.93, 0.0),
        ],
        cell=[10.0, 10.0, 10.0],
        pbc=True,
    )


def test_water_frame_passes_with_water_checks():
    stab = stability_metrics([_water_dimer()])
    assert stab["ok"]
    assert stab["species_checks"] == "O-O,O-H"
    assert stab["min_any_ang"] == pytest.approx(0.96, abs=1e-3)


def test_fused_pair_fails_without_oxygen():
    frame = Atoms("SiC", positions=[(0, 0, 0), (0.3, 0, 0)], cell=[8, 8, 8], pbc=True)
    stab = stability_metrics([frame])
    assert not stab["ok"]
    assert stab["species_checks"] == "none"
    assert stab["min_any_ang"] == pytest.approx(0.3, abs=1e-3)


def test_non_water_system_at_normal_spacing_passes():
    frame = Atoms("SiC", positions=[(0, 0, 0), (1.89, 0, 0)], cell=[8, 8, 8], pbc=True)
    stab = stability_metrics([frame])
    assert stab["ok"]
    assert stab["min_oo_ang"] is None and stab["min_oh_ang"] is None


def test_hbond_decorrelation_requires_oxygen():
    cfg = Config.from_yaml(str(REPO_ROOT / "configs" / "water.yaml"))
    cfg.validate()
    other = copy.deepcopy(cfg)
    other.system.elements = ["Si", "C"]
    with pytest.raises(ValueError, match="decorrelation_observable"):
        other.validate()
    other.explore.decorrelation_observable = "energy"
    other.validate()
