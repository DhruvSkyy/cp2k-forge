"""Swappable MD engines.

The explore/showcase MD is run behind one interface so the propagator can change
without touching the pipeline. Two implementations:

  ASEMaceEngine        ASE dynamics driven by a MACE model (mace-torch). The MVP path.
                       The foundation generator adds D3 dispersion (mandatory for water);
                       a trained model does NOT (revPBE-D3 physics is already in its labels).

  CP2KMetatomicEngine  MD inside CP2K via the &METATOMIC backend — the integrated/"platform"
                       path that lands the model on the optimised in-CP2K engine. Used for the
                       showcase isobar and the throughput comparison.

Both return a list of sampled ASE Atoms frames (no labels — those come from DFT later).
"""

from __future__ import annotations

import abc
import os
from pathlib import Path

# Canonical foundation-model size aliases accepted by mace.calculators.mace_mp.
_MP_ALIASES = {"mace-mp-0": "medium", "mp-0": "medium", "mace-mp": "medium"}


def _density_gcc(atoms) -> float:
    """Mass density in g/cm^3 (local copy so the engine is import-light)."""
    import numpy as np

    amu_to_g = 1.66053906660e-24
    ang3_to_cm3 = 1.0e-24
    return (float(np.sum(atoms.get_masses())) * amu_to_g) / (
        atoms.get_volume() * ang3_to_cm3
    )


def make_npt_dyn(
    atoms,
    timestep_fs: float,
    temperature_k: float,
    pressure_bar: float,
    barostat: str,
    compressibility_au: float = 4.57e-5,
    tdamp_fs: float = 100.0,
    pdamp_fs: float = 1000.0,
    bulk_modulus_gpa: float = 2.2,
):
    """Construct an NPT integrator.

    "berendsen"  NPTBerendsen: fast monotonic relaxation but non-canonical (suppressed
                 fluctuations) — use only for discarded equilibration segments.
    "mtk"        canonical isothermal-isobaric sampling: IsotropicMTKNPT (ASE >= 3.25) or,
                 when unavailable, ase.md.npt.NPT (Melchionna) with the barostat mass set
                 from the liquid bulk modulus — use wherever the harvested fluctuations or
                 the density observable matter.
    """
    from ase import units as ase_units

    if barostat == "berendsen":
        from ase.md.nptberendsen import NPTBerendsen

        return NPTBerendsen(
            atoms,
            timestep=timestep_fs * ase_units.fs,
            temperature_K=temperature_k,
            pressure_au=pressure_bar * 1e5 * ase_units.Pascal,
            compressibility_au=compressibility_au / ase_units.bar,
        )
    if barostat != "mtk":
        raise ValueError(f"unknown barostat {barostat!r} (use 'berendsen' or 'mtk')")
    if not atoms.cell.orthorhombic:
        raise ValueError("the 'mtk' barostat path requires an orthorhombic cell")
    p_ev_a3 = pressure_bar * 1e5 * ase_units.Pascal
    try:
        from ase.md.nose_hoover_chain import IsotropicMTKNPT

        return IsotropicMTKNPT(
            atoms,
            timestep_fs * ase_units.fs,
            temperature_K=temperature_k,
            pressure_au=p_ev_a3,
            tdamp=tdamp_fs * ase_units.fs,
            pdamp=pdamp_fs * ase_units.fs,
        )
    except (ImportError, TypeError) as exc:
        print(
            f"  [IsotropicMTKNPT unavailable ({exc}); falling back to ase.md.npt.NPT]"
        )
        from ase.md.npt import NPT

        b_ev_a3 = bulk_modulus_gpa * ase_units.GPa
        return NPT(
            atoms,
            timestep_fs * ase_units.fs,
            temperature_K=temperature_k,
            externalstress=p_ev_a3,
            ttime=tdamp_fs * ase_units.fs,
            pfactor=(pdamp_fs * ase_units.fs) ** 2 * b_ev_a3,
        )


def make_nvt_dyn(
    atoms,
    timestep_fs: float,
    temperature_k: float,
    thermostat: str = "langevin",
    friction: float = 0.01,
    taut_fs: float = 100.0,
):
    """Construct a canonical NVT integrator: Langevin (default) or Bussi CSVR."""
    from ase import units as ase_units

    if thermostat == "bussi":
        try:
            from ase.md.bussi import Bussi

            return Bussi(
                atoms,
                timestep_fs * ase_units.fs,
                temperature_K=temperature_k,
                taut=taut_fs * ase_units.fs,
            )
        except (ImportError, TypeError) as exc:
            print(f"  [Bussi thermostat unavailable ({exc}); falling back to Langevin]")
    from ase.md.langevin import Langevin

    return Langevin(
        atoms,
        timestep_fs * ase_units.fs,
        temperature_K=temperature_k,
        friction=friction,
    )


class MDEngine(abc.ABC):
    @abc.abstractmethod
    def run_md(
        self,
        atoms,
        temperature_k: float,
        steps: int,
        timestep_fs: float,
        sample_every: int,
        equilibration_steps: int,
        **kwargs,
    ) -> list:
        """Run MD and return sampled frames (a copy per sample, calculator stripped)."""


class ASEMaceEngine(MDEngine):
    # float32 is the default for SAMPLING MD: every kept structure is relabelled by DFT
    # (or scored by a float64 calculator), so sampler precision buys nothing — and
    # float64 measured 271 ms/step on an A100 (canary), turning one generate stage into
    # ~19 h. Force/energy SCORING paths must keep constructing their own float64
    # calculators (fixed_test_eval does).
    def __init__(
        self,
        model: str,
        dispersion: bool,
        device: str = "cpu",
        is_foundation: bool = True,
        default_dtype: str = "float32",
        enable_cueq: bool = False,
    ):
        self.model = model
        self.dispersion = dispersion and is_foundation
        self.device = device
        self.is_foundation = is_foundation
        self.default_dtype = default_dtype
        self.enable_cueq = enable_cueq
        self._calc = None

    def _cueq(self) -> bool:
        if not self.enable_cueq:
            return False
        try:
            import cuequivariance_torch  # noqa: F401

            return True
        except ImportError:
            return False

    def _calculator(self):
        if self._calc is not None:
            return self._calc
        if self.is_foundation:
            from mace.calculators import mace_mp

            model = _MP_ALIASES.get(self.model, self.model)
            self._calc = mace_mp(
                model=model,
                dispersion=self.dispersion,
                device=self.device,
                default_dtype=self.default_dtype,
                enable_cueq=self._cueq(),
            )
        else:
            from mace.calculators import MACECalculator

            self._calc = MACECalculator(
                model_paths=self.model,
                device=self.device,
                default_dtype=self.default_dtype,
                enable_cueq=self._cueq(),
            )
        return self._calc

    def run_md(
        self,
        atoms,
        temperature_k,
        steps,
        timestep_fs,
        sample_every,
        equilibration_steps,
        ensemble="NVT",
        pressure_bar=1.0,
        compressibility_au=4.57e-5,
        friction=0.01,
        density_min=None,
        density_max=None,
        clamp_patience=5,
        velocity_seed=None,
        barostat="berendsen",
        thermostat="langevin",
        tdamp_fs=100.0,
        pdamp_fs=1000.0,
    ):
        """Run NVT or NPT MD and return the raw sampled frames.

        `steps` is the TOTAL step count; the first `equilibration_steps` are run without
        sampling, then a frame is stored every `sample_every` steps (a copy with the
        calculator stripped, the MD potential energy kept in info). NPT equilibration
        always uses Berendsen (fast relaxation, and the segment is discarded); production
        uses `barostat` ("berendsen" | "mtk") so the harvested density fluctuations are
        canonical when it matters. NVT uses `thermostat` ("langevin" | "bussi").

        `velocity_seed` seeds the initial Maxwell-Boltzmann draw so replicas at identical
        (T, density) differ deterministically rather than via thermostat noise alone.

        Under NPT, if `density_min`/`density_max` are set the trajectory is aborted once
        the density leaves that window for `clamp_patience` consecutive samples, guarding
        against an under-trained model collapsing or evaporating the box; the in-window
        frames collected so far are returned. The abort verdict is exposed as
        `self.last_run_info["clamp_aborted"]` for the caller's records.
        """
        from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

        work = atoms.copy()
        work.calc = self._calculator()
        if velocity_seed is not None:
            import numpy as np

            MaxwellBoltzmannDistribution(
                work,
                temperature_K=temperature_k,
                rng=np.random.default_rng(int(velocity_seed)),
            )
        else:
            MaxwellBoltzmannDistribution(work, temperature_K=temperature_k)

        is_npt = ensemble.upper() == "NPT"
        eq_steps = int(equilibration_steps or 0)
        production_steps = max(0, steps - eq_steps)
        if is_npt:
            # Equilibration always relaxes under Berendsen (fast, and discarded anyway);
            # production switches to the requested barostat.
            eq_dyn = make_npt_dyn(
                work,
                timestep_fs,
                temperature_k,
                pressure_bar,
                "berendsen",
                compressibility_au=compressibility_au,
            )
            if eq_steps:
                eq_dyn.run(eq_steps)
            if barostat == "berendsen":
                prod_dyn = eq_dyn
            else:
                prod_dyn = make_npt_dyn(
                    work,
                    timestep_fs,
                    temperature_k,
                    pressure_bar,
                    barostat,
                    compressibility_au=compressibility_au,
                    tdamp_fs=tdamp_fs,
                    pdamp_fs=pdamp_fs,
                )
        else:
            prod_dyn = make_nvt_dyn(
                work,
                timestep_fs,
                temperature_k,
                thermostat=thermostat,
                friction=friction,
                taut_fs=tdamp_fs,
            )
            if eq_steps:
                prod_dyn.run(eq_steps)

        frames: list = []
        state = {"n": 0, "bad": 0, "stop": False}
        clamp = is_npt and density_min is not None and density_max is not None

        def maybe_sample():
            state["n"] += 1
            if state["n"] % sample_every != 0:
                return
            snap = work.copy()
            snap.calc = None
            try:
                snap.info["md_epot_ev"] = float(work.get_potential_energy())
            except Exception:
                pass
            if clamp:
                rho = _density_gcc(snap)
                if rho < density_min or rho > density_max:
                    state["bad"] += 1
                    if state["bad"] >= clamp_patience:
                        state["stop"] = True
                    return  # drop the out-of-window frame
                state["bad"] = 0
            frames.append(snap)

        prod_dyn.attach(maybe_sample, interval=1)
        # Run in chunks so a clamp violation can abort promptly.
        chunk = max(1, sample_every)
        done = 0
        while done < production_steps and not state["stop"]:
            step = min(chunk, production_steps - done)
            prod_dyn.run(step)
            done += step
        self.last_run_info = {
            "clamp_aborted": bool(state["stop"]),
            "production_steps_run": done,
        }
        return frames


_SYMMETRIX_MD_DECK = """&GLOBAL
  PROJECT {project}
  RUN_TYPE MD
  PRINT_LEVEL LOW
  SEED {seed}
&END GLOBAL
&MOTION
  &MD
    ENSEMBLE {ensemble}
    STEPS {steps}
    TEMPERATURE {temperature}
    TIMESTEP {timestep}
{ensemble_block}
    &THERMOSTAT
      &CSVR
        TIMECON [fs] {tdamp}
      &END CSVR
    &END THERMOSTAT
  &END MD
  &PRINT
    &TRAJECTORY
      &EACH
        MD {sample_every}
      &END EACH
    &END TRAJECTORY
    &CELL
      &EACH
        MD {sample_every}
      &END EACH
    &END CELL
    &RESTART OFF
    &END RESTART
    &RESTART_HISTORY OFF
    &END RESTART_HISTORY
  &END PRINT
&END MOTION
&FORCE_EVAL
  METHOD FIST
{stress_tensor}
  &MM
    &FORCEFIELD
      &NONBONDED
        &SYMMETRIX
          ATOMS {species}
          POT_FILE_NAME {model_json}
        &END SYMMETRIX
      &END NONBONDED
    &END FORCEFIELD
    &POISSON
      &EWALD
        EWALD_TYPE none
      &END EWALD
    &END POISSON
  &END MM
  &SUBSYS
    &CELL
      ABC [angstrom] {abc}
      PERIODIC XYZ
    &END CELL
    &TOPOLOGY
      COORD_FILE_FORMAT XYZ
      COORD_FILE_NAME {coord_file}
    &END TOPOLOGY
  &END SUBSYS
&END FORCE_EVAL
"""

_NPT_BLOCK = """    &BAROSTAT
      PRESSURE [bar] {pressure_bar}
      TIMECON [fs] {pdamp}
    &END BAROSTAT"""


class CP2KSymmetrixEngine(MDEngine):
    """Drive MD inside CP2K through the &SYMMETRIX backend (the project's fast engine).

    The model is a symmetrix JSON produced by extract_mace (cp2k_forge.train auto-exports
    one next to every trained .model). Feature parity with ASEMaceEngine for the
    explore loop: NVT (CSVR) / NPT_I (CSVR + isotropic barostat), deterministic
    velocity seed (GLOBAL/SEED), frames sampled every `sample_every` steps with
    per-frame cells (parsed from the .cell file), equilibration discarded, and a
    post-hoc density-window filter standing in for ASE's in-flight clamp.
    """

    def __init__(
        self,
        model_json: str,
        cp2k_bin: str | None = None,
        run_root: str | Path | None = None,
        device: str = "cuda",
        omp_threads: int | None = None,
        extra_env: dict | None = None,
    ):
        self.model_json = str(model_json)
        # The metatomic/&SYMMETRIX-enabled CP2K binary. There is no portable default:
        # point CP2K_BACKEND_BIN (or pass cp2k_bin) at a CP2K built with the MACE
        # backend. A missing build is an actionable error rather than a silent
        # fallback.
        self.cp2k_bin = (
            cp2k_bin
            or os.environ.get("CP2K_BACKEND_BIN")
            or os.environ.get("SYMMETRIX_CP2K_BIN")
        )
        if not self.cp2k_bin or not Path(self.cp2k_bin).exists():
            raise RuntimeError(
                "generator.engine='cp2k-backend' needs a metatomic/&SYMMETRIX-enabled "
                "CP2K build, which ships as a separate contribution (see the MACE backend "
                "PR). Set CP2K_BACKEND_BIN to that binary, or use the default ASE engine "
                "(generator.engine: ase), which runs anywhere with mace-torch."
            )
        self.run_root = Path(run_root) if run_root else None
        self.device = device
        self.omp_threads = omp_threads
        self.extra_env = dict(extra_env or {})
        self.last_run_info: dict = {}

    def _env(self) -> dict:
        env = dict(os.environ)
        # Backend-specific shared libraries (torch, CUDA, BLAS) come from the caller's
        # environment; append SYMMETRIX_LD_LIBRARY_PATH if set rather than hardcoding
        # any site-specific paths.
        extra = os.environ.get("SYMMETRIX_LD_LIBRARY_PATH")
        if extra:
            env["LD_LIBRARY_PATH"] = ":".join([extra, env.get("LD_LIBRARY_PATH", "")])
        if self.omp_threads:
            env["OMP_NUM_THREADS"] = str(self.omp_threads)
        # "cuda:1"-style device pins the subprocess to one GPU (worker round-robin).
        if str(self.device).startswith("cuda:"):
            env["CUDA_VISIBLE_DEVICES"] = str(self.device).split(":", 1)[1]
        env.update(self.extra_env)
        return env

    def run_md(
        self,
        atoms,
        temperature_k,
        steps,
        timestep_fs,
        sample_every,
        equilibration_steps,
        ensemble="NVT",
        pressure_bar=1.0,
        compressibility_au=4.57e-5,
        friction=0.01,
        density_min=None,
        density_max=None,
        clamp_patience=5,
        velocity_seed=None,
        barostat="mtk",
        thermostat="bussi",
        tdamp_fs=100.0,
        pdamp_fs=1000.0,
    ):
        import shutil
        import subprocess
        import tempfile

        import numpy as np
        from ase.io import read, write

        self.last_run_info = {}
        is_npt = str(ensemble).upper() == "NPT"
        base = self.run_root if self.run_root else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        rundir = Path(tempfile.mkdtemp(prefix="symmd_", dir=str(base)))

        write(str(rundir / "coord.xyz"), atoms, format="xyz")
        abc = " ".join(f"{x:.6f}" for x in atoms.cell.lengths())
        species = " ".join(sorted(set(atoms.get_chemical_symbols())))
        deck = _SYMMETRIX_MD_DECK.format(
            project="symmd",
            seed=int(velocity_seed or 1),
            ensemble="NPT_I" if is_npt else "NVT",
            steps=int(steps),
            temperature=float(temperature_k),
            timestep=float(timestep_fs),
            ensemble_block=(
                _NPT_BLOCK.format(
                    pressure_bar=float(pressure_bar), pdamp=float(pdamp_fs)
                )
                if is_npt
                else ""
            ),
            stress_tensor=("  STRESS_TENSOR ANALYTICAL" if is_npt else ""),
            tdamp=float(tdamp_fs),
            sample_every=max(1, int(sample_every)),
            species=species,
            model_json=self.model_json,
            abc=abc,
            coord_file=str(rundir / "coord.xyz"),
        )
        (rundir / "md.inp").write_text(deck)

        out = rundir / "md.out"
        md_crashed = False
        with open(out, "w") as fh:
            try:
                subprocess.run(
                    [self.cp2k_bin, "-i", "md.inp", "-o", str(out)],
                    cwd=str(rundir),
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    check=True,
                    env=self._env(),
                )
            except subprocess.CalledProcessError:
                # A mid-MD physics blow-up (e.g. FIST's EMAX_SPLINE abort when an
                # extrapolating model collapses a cell) is a CLAMP event, not a
                # pipeline crash: salvage the frames written so far and flag the
                # cell — mirroring the ASE engine's in-flight clamp behaviour.
                md_crashed = True

        traj = rundir / "symmd-pos-1.xyz"
        if not traj.exists():
            self.last_run_info = {
                "clamp_aborted": True,
                "n_traj_frames": 0,
                "rundir": str(rundir),
            }
            return []
        frames = read(str(traj), index=":")
        frames = frames if isinstance(frames, list) else [frames]
        cells = self._parse_cells(rundir / "symmd-1.cell")
        steps_idx = self._parse_traj_steps(rundir / "symmd-pos-1.xyz")

        # Confirmed failure mode (2026-07-15 canary): exported forces match mace-torch
        # to 0.01 meV/A, but negative-pressure legs cavitate (metastable stretched
        # liquid; stronger tension = earlier nucleation), the NPT cell runs away and
        # CP2K aborts in get_nhc_energies. The filter below drops those frames; the
        # clamp event is the caller's signal that the leg ended early by physics.
        kept = []
        consecutive_out = 0
        clamp_aborted = False
        for i, f in enumerate(frames):
            # True MD step from the trajectory comment ("i = N, time = ..."); CP2K
            # includes step 0, so inferring i*sample_every would be off by one.
            step = (
                steps_idx[i]
                if steps_idx and i < len(steps_idx)
                else i * max(1, int(sample_every))
            )
            if cells is not None and i < len(cells):
                f.set_cell(cells[i])
                f.set_pbc(True)
            else:
                f.set_cell(atoms.get_cell())
                f.set_pbc(True)
            if step <= int(equilibration_steps):
                continue
            if is_npt and (density_min or density_max):
                rho = _density_gcc(f)
                lo = density_min or 0.0
                hi = density_max or 1e9
                if not (lo <= rho <= hi):
                    consecutive_out += 1
                    if consecutive_out >= int(clamp_patience):
                        clamp_aborted = True
                    continue
                consecutive_out = 0
            kept.append(f)

        clamp_aborted = clamp_aborted or md_crashed
        self.last_run_info = {
            "clamp_aborted": clamp_aborted,
            "n_traj_frames": len(frames),
            "rundir": str(rundir),
        }
        if kept and not clamp_aborted:
            shutil.rmtree(rundir, ignore_errors=True)  # keep dir only for post-mortem
            self.last_run_info["rundir"] = None
        return kept

    @staticmethod
    def _parse_traj_steps(pos_file: Path):
        """MD step numbers from the xyz comment lines: ' i =  N, time = ...'."""
        steps = []
        try:
            with open(pos_file) as fh:
                first = fh.readline()
                while first:
                    nat = int(first.split()[0])
                    comment = fh.readline()
                    try:
                        steps.append(int(comment.split("i =")[1].split(",")[0]))
                    except (IndexError, ValueError):
                        steps.append(len(steps))
                    for _ in range(nat):
                        fh.readline()
                    first = fh.readline()
        except (OSError, ValueError):
            return None
        return steps or None

    @staticmethod
    def _parse_cells(cell_file: Path):
        """PROJECT-1.cell rows: step time ax ay az bx by bz cx cy cz volume."""
        import numpy as np

        if not Path(cell_file).exists():
            return None
        rows = []
        for ln in Path(cell_file).read_text().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            p = ln.split()
            if len(p) >= 11:
                rows.append(
                    [
                        [float(p[2]), float(p[3]), float(p[4])],
                        [float(p[5]), float(p[6]), float(p[7])],
                        [float(p[8]), float(p[9]), float(p[10])],
                    ]
                )
        return np.asarray(rows) if rows else None


# Backward-compatible alias: the old stub's name (dead code path) now points at the
# working engine; showcase code referring to CP2KMetatomicEngine keeps importing.
CP2KMetatomicEngine = CP2KSymmetrixEngine
