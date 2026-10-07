"""One-time isolated-atom reference energies (E0s) at the exact labelling level.

`--E0s=average` least-squares-fits the atomic baseline from the dataset every pass, so
the energy scale silently shifts as the dataset grows — and for a fixed-composition water
box the fit is degenerate (any (eH, eO) with 2*eH + eO = const fits equally well). Fixed
isolated-atom E0s make atomization energies well-defined, keep the scale invariant across
passes, and transfer directly to future multi-element systems (ions add F/S/... where
"average" is ill-conditioned).

Each element is computed spin-polarized (ground-state multiplicity) in the campaign box
at the campaign DFT settings via templates/dft_atom.inp. The periodic-atom finite-size
offset at ~12 A is a constant shift far below the force-training scale. Results are
cached in <workdir>/e0s.json and NEVER recomputed for that workdir (recomputing
mid-campaign would silently change the energy baseline between passes).

Runs inside the LABEL stage, so in a node-split campaign it lands on the CP2K-capable
node; the GPU train job only reads the JSON.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Ground-state multiplicities for the isolated-atom calculations. Extend as systems grow.
ATOM_MULTIPLICITY = {
    "H": 2,
    "C": 3,
    "N": 4,
    "O": 3,
    "F": 2,
    "Na": 2,
    "S": 3,
    "Cl": 2,
    "K": 2,
}


def _atom_energy_cp2k(element: str, cfg, run_dir: Path) -> float:
    from ase import Atoms

    from . import cp2k_io, label

    mult = ATOM_MULTIPLICITY.get(element)
    if mult is None:
        raise ValueError(
            f"no ground-state multiplicity known for {element!r}; extend "
            "cp2k_forge.e0s.ATOM_MULTIPLICITY"
        )
    centre = [0.5 * c for c in cfg.system.cell_abc]
    atoms = Atoms(element, positions=[centre], cell=cfg.system.cell_abc, pbc=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    inp = cp2k_io.write_atom_input(
        atoms,
        cfg.dft,
        multiplicity=mult,
        project=f"e0_{element}",
        out_path=run_dir / "dft.inp",
    )
    out = run_dir / "dft.out"
    parsed = label._try_parse_existing(run_dir)  # resume-reuse (incl. mainLog.out)
    if parsed is None:
        cmd = label._cp2k_command(inp, out, cfg.dft)
        with open(out, "w") as fh:
            subprocess.run(
                cmd,
                cwd=str(run_dir),
                stdout=fh,
                stderr=subprocess.STDOUT,
                check=True,
                env=label._cp2k_subprocess_env(cfg.dft),
            )
        parsed = label._try_parse_existing(run_dir)
    if parsed is None:
        raise RuntimeError(
            f"E0 calculation for {element} did not converge or finish — inspect {out} "
            "(single-atom UKS SCF can need more OUTER_SCF iterations)"
        )
    return float(parsed["energy_ev"])


def _atom_energy_mock(element: str, cfg) -> float:
    """Foundation-model atomic energy for the mock backend (plumbing tests only)."""
    from ase import Atoms

    from .direct import _foundation_calc

    calc = _foundation_calc(
        getattr(cfg.dft, "mock_model", "mace-mp-0"),
        getattr(cfg.dft, "mock_device", "cpu"),
    )
    centre = [0.5 * c for c in cfg.system.cell_abc]
    atoms = Atoms(element, positions=[centre], cell=cfg.system.cell_abc, pbc=True)
    atoms.calc = calc
    return float(atoms.get_potential_energy())


def ensure_e0s(cfg, workdir: str | Path) -> dict[int, float]:
    """Return the campaign E0s, computing and caching them on first call."""
    from ase.data import atomic_numbers

    workdir = Path(workdir)
    path = workdir / "e0s.json"
    if path.exists():
        data = json.loads(path.read_text())
        return {int(z): float(e) for z, e in data.items() if str(z).isdigit()}

    mock = getattr(cfg.dft, "backend", "cp2k") == "mock_foundation"
    result: dict[int, float] = {}
    for el in cfg.system.elements:
        if mock:
            e_ev = _atom_energy_mock(el, cfg)
        else:
            e_ev = _atom_energy_cp2k(el, cfg, workdir / "e0s" / el)
        result[atomic_numbers[el]] = e_ev
        print(f"  E0[{el}] = {e_ev:.6f} eV")

    payload: dict = {str(z): e for z, e in result.items()}
    payload["meta"] = {
        "functional": cfg.dft.functional,
        "d3_damping": cfg.dft.d3_damping,
        "basis_set": cfg.dft.basis_set,
        "cutoff_ry": cfg.dft.cutoff_ry,
        "cell_abc": cfg.system.cell_abc,
        "backend": getattr(cfg.dft, "backend", "cp2k"),
        "multiplicities": {el: ATOM_MULTIPLICITY.get(el) for el in cfg.system.elements},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return result
