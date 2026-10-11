#!/usr/bin/env python3
"""Render-path regression tests: the hybrid templates emit the right CP2K tokens and
the GGA path stays byte-identical to the golden fixtures rendered before the hybrid
port. Needs ase + pyyaml only (no torch), so it runs anywhere and in CI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from ase import Atoms
from ase.io import read

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cp2k_forge import cp2k_io  # noqa: E402
from cp2k_forge.config import Config, DFTConfig  # noqa: E402


def _water32():
    atoms = read(str(REPO_ROOT / "examples" / "water32.xyz"), index=0)
    atoms.set_cell([9.8528, 9.8528, 9.8528])
    atoms.set_pbc(True)
    return atoms


def _water64():
    return read(str(REPO_ROOT / "examples" / "water64.xyz"), index=0)


def _hybrid_dft(**overrides):
    base = dict(mode="hybrid", hfx_cutoff_radius_ang=5.5, dispersion_ref="revPBE0")
    base.update(overrides)
    return DFTConfig(**base)


def test_gga_singlepoint_byte_identical(tmp_path):
    out = cp2k_io.write_singlepoint_input(
        _water32(), DFTConfig(), "golden", tmp_path / "sp.inp"
    )
    ref = REPO_ROOT / "tests" / "data" / "singlepoint_water32_gga.inp.ref"
    assert out.read_bytes() == ref.read_bytes()


def test_gga_atom_byte_identical(tmp_path):
    o_atom = Atoms("O", positions=[[6.0, 6.0, 6.0]], cell=[12.0, 12.0, 12.0], pbc=True)
    out = cp2k_io.write_atom_input(
        o_atom, DFTConfig(), 3, "golden_atom", tmp_path / "atom.inp"
    )
    ref = REPO_ROOT / "tests" / "data" / "atom_o_gga.inp.ref"
    assert out.read_bytes() == ref.read_bytes()


def test_hybrid_singlepoint_tokens(tmp_path):
    text = cp2k_io.write_singlepoint_input(
        _water64(), _hybrid_dft(), "hyb", tmp_path / "sp.inp"
    ).read_text()
    for token in (
        "&AUXILIARY_DENSITY_MATRIX_METHOD",
        "FRACTION 0.2500",
        "SCALE_X 0.7500",
        "POTENTIAL_TYPE TRUNCATED",
        "CUTOFF_RADIUS 5.50",
        "T_C_G_DATA t_c_g.dat",
        "BASIS_SET_FILE_NAME BASIS_ADMM",
        "BASIS_SET AUX_FIT cpFIT3",
        "REFERENCE_FUNCTIONAL revPBE0",
        "ADMM_PURIFICATION_METHOD MO_DIAG",
    ):
        assert token in text, token


def test_hybrid_admm_override(tmp_path):
    fluoride = Atoms(
        "FOH2",
        positions=[[6, 6, 6], [3, 3, 3], [3.8, 3, 3], [3, 3.8, 3]],
        cell=[12.4313, 12.4313, 12.4313],
        pbc=True,
    )
    dft = _hybrid_dft(admm_basis_overrides={"F": "aug-cpFIT3"}, charge=-1)
    text = cp2k_io.write_singlepoint_input(
        fluoride, dft, "fhyb", tmp_path / "sp.inp"
    ).read_text()
    assert "CHARGE -1" in text
    f_kind = text.split("&KIND F")[1].split("&END KIND")[0]
    o_kind = text.split("&KIND O")[1].split("&END KIND")[0]
    assert "BASIS_SET AUX_FIT aug-cpFIT3" in f_kind
    assert "BASIS_SET AUX_FIT cpFIT3" in o_kind


def test_hybrid_atom_stays_neutral(tmp_path):
    o_atom = Atoms("O", positions=[[6, 6, 6]], cell=[12.4313] * 3, pbc=True)
    text = cp2k_io.write_atom_input(
        o_atom, _hybrid_dft(charge=-1), 3, "e0", tmp_path / "atom.inp"
    ).read_text()
    assert "CHARGE 0" in text
    assert "CHARGE -1" not in text


def test_hfx_radius_guard_per_frame(tmp_path):
    with pytest.raises(ValueError, match="truncated Coulomb"):
        cp2k_io.write_singlepoint_input(
            _water32(), _hybrid_dft(), "bad", tmp_path / "sp.inp"
        )


def test_hfx_radius_guard_config_level():
    cfg = Config.from_yaml(str(REPO_ROOT / "configs" / "water_hybrid.yaml"))
    cfg.system.cell_abc = [9.8528, 9.8528, 9.8528]
    with pytest.raises(ValueError, match="truncated Coulomb"):
        cfg.validate()


def test_water_hybrid_config_loads():
    cfg = Config.from_yaml(str(REPO_ROOT / "configs" / "water_hybrid.yaml"))
    assert cfg.dft.mode == "hybrid"
    assert cfg.dft.hf_fraction == 0.25
    assert cfg.train.stress_weight == 0.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
