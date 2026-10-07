"""CP2K input templating and output parsing for the DFT labelling stage.

`write_singlepoint_input` fills `templates/dft_singlepoint.inp` from an ASE Atoms
object + the campaign DFT config. `parse_singlepoint_output` reads the resulting
CP2K log and returns energy/forces/stress already converted to MACE units (eV,
eV/Angstrom, eV/Angstrom^3) via `units`.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from . import units

# The .inp templates ship inside the package (cp2k_forge/templates/), so a pip
# install carries them; importlib.resources finds them for any install layout.
_TEMPLATE_DIR = resources.files(__package__) / "templates"
TEMPLATE = _TEMPLATE_DIR / "dft_singlepoint.inp"
ATOM_TEMPLATE = _TEMPLATE_DIR / "dft_atom.inp"
AIMD_TEMPLATE = _TEMPLATE_DIR / "aimd_reference.inp"


def _coord_block(atoms) -> str:
    lines = []
    for sym, (x, y, z) in zip(atoms.get_chemical_symbols(), atoms.get_positions()):
        lines.append(f"      {sym:<2s} {x:18.10f} {y:18.10f} {z:18.10f}")
    return "\n".join(lines)


def _kind_blocks(elements, basis: str, potential: str) -> str:
    """Per-element &KIND blocks (BASIS_SET + POTENTIAL for each element)."""
    blocks = []
    for el in elements:
        blocks.append(
            "\n".join(
                [
                    f"    &KIND {el}",
                    f"      BASIS_SET {basis}",
                    f"      POTENTIAL {potential}",
                    "    &END KIND",
                ]
            )
        )
    return "\n".join(blocks)


def _inject_charge(text: str, charge: int) -> str:
    """Post-process CHARGE into a rendered input (for a charged box).
    charge == 0 returns the text unchanged."""
    if not charge:
        return text
    return text.replace("  &DFT\n", f"  &DFT\n    CHARGE {charge}\n", 1)


def write_singlepoint_input(atoms, dft, project: str, out_path: str | Path) -> Path:
    """Render a GGA DFT single-point input for one structure. Returns the written path."""
    cell = atoms.get_cell().lengths()
    elements = sorted(set(atoms.get_chemical_symbols()))
    # CP2K D3 damping: "DFTD3" = zero damping; "DFTD3(BJ)" = Becke-Johnson.
    d3_suffix = (
        "(BJ)"
        if str(getattr(dft, "d3_damping", "zero")).lower() in ("bj", "becke-johnson")
        else ""
    )
    common = dict(
        project=project,
        cutoff=dft.cutoff_ry,
        rel_cutoff=dft.rel_cutoff_ry,
        eps_scf=dft.eps_scf,
        max_scf=dft.max_scf,
        functional=dft.functional.upper(),  # CP2K PARAMETRIZATION token, e.g. REVPBE
        dispersion_ref=dft.dispersion_ref,
        d3_suffix=d3_suffix,
        abc=f"{cell[0]:.6f} {cell[1]:.6f} {cell[2]:.6f}",
        coord_block=_coord_block(atoms),
    )
    text = TEMPLATE.read_text().format(
        **common,
        kind_blocks=_kind_blocks(elements, dft.basis_set, dft.potential),
    )
    text = _inject_charge(text, int(getattr(dft, "charge", 0)))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return out


def write_atom_input(
    atoms, dft, multiplicity: int, project: str, out_path: str | Path
) -> Path:
    """Render a spin-polarized isolated-atom input (for the E0 reference energies).

    A sibling template (dft_atom.inp) rather than an edit of the production single-point
    template: it adds UKS + MULTIPLICITY (open-shell H doublet / O triplet) and drops the
    stress tensor, everything else — functional, D3, basis, cutoffs, SCF — stays at the
    exact labelling level so the E0s are consistent with the dataset energies.
    """
    cell = atoms.get_cell().lengths()
    elements = sorted(set(atoms.get_chemical_symbols()))
    d3_suffix = (
        "(BJ)"
        if str(getattr(dft, "d3_damping", "zero")).lower() in ("bj", "becke-johnson")
        else ""
    )
    common = dict(
        project=project,
        multiplicity=multiplicity,
        cutoff=dft.cutoff_ry,
        rel_cutoff=dft.rel_cutoff_ry,
        eps_scf=dft.eps_scf,
        max_scf=dft.max_scf,
        functional=dft.functional.upper(),
        dispersion_ref=dft.dispersion_ref,
        d3_suffix=d3_suffix,
        abc=f"{cell[0]:.6f} {cell[1]:.6f} {cell[2]:.6f}",
        coord_block=_coord_block(atoms),
    )
    text = ATOM_TEMPLATE.read_text().format(
        **common,
        kind_blocks=_kind_blocks(elements, dft.basis_set, dft.potential),
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return out


def write_aimd_input(
    atoms,
    dft,
    project: str,
    out_path: str | Path,
    *,
    steps: int,
    timestep_fs: float,
    temperature_k: float,
    sample_every: int,
    eps_scf: float = 1.0e-6,
    restart_file: str | None = None,
) -> Path:
    """Render a revPBE-D3 Born-Oppenheimer NVT-MD input (the AIMD validation reference).

    Same XC/D3/basis/cutoffs as the labelling single point, but RUN_TYPE MD with a
    Nose-Hoover thermostat and ASPC wavefunction extrapolation + a looser eps_scf (1e-6 is
    MD-appropriate, ~4 SCF iters/step vs a cold single point). Positions and velocities are
    printed every `sample_every` steps (positions -> RDF reference, velocities -> VDOS
    reference). With `restart_file`, an &EXT_RESTART block continues a prior run's MD state
    (positions, velocities, thermostat, step counter) so a multi-day AIMD survives the
    walltime cap as a restart chain.
    """
    cell = atoms.get_cell().lengths()
    elements = sorted(set(atoms.get_chemical_symbols()))
    d3_suffix = (
        "(BJ)"
        if str(getattr(dft, "d3_damping", "zero")).lower() in ("bj", "becke-johnson")
        else ""
    )
    ext_restart = ""
    if restart_file:
        ext_restart = (
            f"&EXT_RESTART\n  RESTART_FILE_NAME {restart_file}\n"
            "  RESTART_COUNTERS .TRUE.\n&END EXT_RESTART\n"
        )
    text = AIMD_TEMPLATE.read_text().format(
        project=project,
        steps=steps,
        timestep_fs=timestep_fs,
        temperature=temperature_k,
        sample_every=sample_every,
        cutoff=dft.cutoff_ry,
        rel_cutoff=dft.rel_cutoff_ry,
        eps_scf=eps_scf,
        max_scf=dft.max_scf,
        functional=dft.functional.upper(),
        dispersion_ref=dft.dispersion_ref,
        d3_suffix=d3_suffix,
        abc=f"{cell[0]:.6f} {cell[1]:.6f} {cell[2]:.6f}",
        coord_block=_coord_block(atoms),
        kind_blocks=_kind_blocks(elements, dft.basis_set, dft.potential),
        ext_restart=ext_restart,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return out


def parse_singlepoint_output(out_path: str | Path):
    """Parse a CP2K ENERGY_FORCE log.

    Returns a dict with keys:
        energy_ev    float
        forces       list[[fx, fy, fz]] in eV/Angstrom
        stress       list of 6 floats (Voigt xx,yy,zz,yz,xz,xy) in eV/Angstrom^3,
                     or None if no stress block was printed
    Raises ValueError if energy or forces are absent (i.e. the job did not finish).
    """
    lines = Path(out_path).read_text().splitlines()

    energy_ev = _parse_energy(lines)
    forces = _parse_forces(lines)
    stress = _parse_stress(lines)

    if energy_ev is None or not forces:
        raise ValueError(f"{out_path}: missing energy or forces (job incomplete?)")
    return {"energy_ev": energy_ev, "forces": forces, "stress": stress}


def _parse_energy(lines) -> float | None:
    val = None
    for ln in lines:
        if "ENERGY| Total FORCE_EVAL" in ln:
            val = float(ln.split()[-1])  # Hartree; last occurrence wins
    return None if val is None else units.hartree_to_ev(val)


def _parse_forces(lines):
    """Atomic forces (a.u.) -> eV/Angstrom. Handles both CP2K output formats:

    CP2K 2023.x: ``FORCES| Atomic forces [hartree/bohr]`` then rows
        ``FORCES| <idx> <fx> <fy> <fz> <|f|>``
    Older CP2K:  ``ATOMIC FORCES in [a.u.]`` then rows
        ``<idx> <kind> <element> <fx> <fy> <fz>``
    """
    f2e = units.force_au_to_ev_per_angstrom
    forces = []
    in_new = in_old = False
    for ln in lines:
        if "FORCES| Atomic forces" in ln:
            in_new, in_old, forces = True, False, []
            continue
        if "ATOMIC FORCES in [a.u.]" in ln:
            in_old, in_new, forces = True, False, []
            continue
        if in_new:
            if not ln.lstrip().startswith("FORCES|"):
                break  # block ended
            parts = ln.split()
            # data rows: FORCES| <idx> fx fy fz |f|  (skip "Atom"/"Sum" header rows)
            if len(parts) >= 6 and parts[1].isdigit():
                fx, fy, fz = float(parts[2]), float(parts[3]), float(parts[4])
                forces.append([f2e(fx), f2e(fy), f2e(fz)])
        elif in_old:
            if "SUM OF ATOMIC FORCES" in ln:
                break
            parts = ln.split()
            if len(parts) >= 6 and parts[0].isdigit():
                fx, fy, fz = (float(parts[-3]), float(parts[-2]), float(parts[-1]))
                forces.append([f2e(fx), f2e(fy), f2e(fz)])
    return forces


def _parse_stress(lines):
    """Parse the analytical stress tensor -> Voigt-6 in eV/Angstrom^3.

    CP2K 2023.x prints the tensor in **bar** (``STRESS| Analytical stress tensor [bar]``);
    older builds used GPa. The unit is auto-detected from the header line. Rows look like
    ``STRESS|   x   <xx> <xy> <xz>``. We take the first 3 (x,y,z) rows and stop before the
    Trace/Determinant/eigenvector lines that also start with ``STRESS|``.
    """
    rows = {}
    in_block = False
    to_gpa = 1.0
    for ln in lines:
        if "STRESS| Analytical stress tensor" in ln:
            in_block = True
            rows = {}
            to_gpa = 1.0e-4 if "[bar]" in ln else 1.0  # bar->GPa, else assume GPa
            continue
        if in_block:
            parts = ln.split()
            if (
                len(parts) >= 5
                and parts[0] == "STRESS|"
                and parts[1] in ("x", "y", "z")
            ):
                rows[parts[1]] = [float(parts[2]), float(parts[3]), float(parts[4])]
                if len(rows) == 3:
                    break
            elif rows and not ln.lstrip().startswith("STRESS|"):
                break
    if len(rows) != 3:
        return None
    # Sign: CP2K prints the physics convention (positive trace = system under positive
    # pressure); ASE/MACE use sigma = +(1/V) dE/deps, where that same state has a
    # NEGATIVE diagonal. Negate so REF_stress trains with the right sign if
    # stress_weight is ever enabled.
    g = lambda s: -units.stress_gpa_to_ev_per_angstrom3(s * to_gpa)
    xx, xy, xz = rows["x"]
    yx, yy, yz = rows["y"]
    zx, zy, zz = rows["z"]
    # Voigt: xx, yy, zz, yz, xz, xy (symmetric tensor)
    return [g(xx), g(yy), g(zz), g(yz), g(xz), g(xy)]
