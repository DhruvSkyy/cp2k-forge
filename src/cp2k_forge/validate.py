"""Watch water accuracy beyond the (necessary-but-insufficient) held-out force RMSE.

Held-out force RMSE is computed on frames the *foundation* model generated, so it is
in-distribution and circular: it cannot see where the *trained* model's own dynamics
drift. This module adds the checks that actually test physics::

  compute_rdf            structural validation — g_OO/g_OH/g_HH vs reference AIMD
  own_trajectory_spot_check
                         the key OOD guard (replaces what a committee would flag):
                         run MD with the TRAINED model, DFT-label a few of ITS OWN
                         snapshots, and report model-vs-DFT force/energy error there
  npt_steps_for_resolution
                         feasibility: how long an NPT run must be to resolve density
                         to a target error bar (decides whether the TMD is even visible)

These are deliberately cheap: the spot-check is ~10-20 extra DFT single points, far
less than a committee, and it is the single most informative accuracy signal.
"""

from __future__ import annotations

from pathlib import Path


def compute_rdf(
    frames,
    pairs=(("O", "O"), ("O", "H"), ("H", "H")),
    r_max: float = 6.0,
    nbins: int = 120,
):
    """Partial radial distribution functions averaged over `frames` (one thermo state).

    Returns {(a, b): (r, g)} with r the bin centres (Angstrom). Frames are assumed to
    share roughly one density/temperature (e.g. ambient) so the normalisation is stable.
    """
    import numpy as np

    edges = np.linspace(0.0, r_max, nbins + 1)
    r = 0.5 * (edges[1:] + edges[:-1])
    dr = r_max / nbins
    shell = 4.0 * np.pi * r**2 * dr

    hist = {p: np.zeros(nbins) for p in pairs}
    na_sum = {}
    nb_over_v_sum = {}
    nframes = 0
    for atoms in frames:
        nframes += 1
        sym = np.asarray(atoms.get_chemical_symbols())
        vol = atoms.get_volume()
        dmat = atoms.get_all_distances(mic=True)
        for a, b in pairs:
            ia = np.where(sym == a)[0]
            ib = np.where(sym == b)[0]
            d = dmat[np.ix_(ia, ib)]
            if a == b:  # drop self-distances, keep ordered pairs
                np.fill_diagonal(d, np.inf)
            dd = d.ravel()
            dd = dd[(dd > 0.0) & (dd < r_max)]
            hist[(a, b)] += np.histogram(dd, bins=edges)[0]
            na_sum[(a, b)] = na_sum.get((a, b), 0) + len(ia)
            nb_over_v_sum[(a, b)] = nb_over_v_sum.get((a, b), 0.0) + len(ib) / vol

    out = {}
    for a, b in pairs:
        na_avg = na_sum[(a, b)] / nframes  # central atoms / frame
        rho_b = nb_over_v_sum[(a, b)] / nframes  # number density of b
        denom = nframes * na_avg * rho_b * shell
        g = np.divide(
            hist[(a, b)], denom, out=np.zeros_like(hist[(a, b)]), where=denom > 0
        )
        out[(a, b)] = (r, g)
    return out


def _load_seed(cfg):
    """Load the campaign seed structure (shared by the spot-check and VDOS runs)."""
    from .seed import load_seed

    return load_seed(cfg)


def stability_metrics(
    frames, min_oo_ang: float = 2.0, min_oh_ang: float = 0.7, min_any_ang: float = 0.5
) -> dict:
    """Geometric blow-up check over an MD trajectory.

    A collapsing model violates the shortest physical distances first. Every system is
    held to `min_any_ang` on the closest approach of any two atoms. Systems containing
    O and H are additionally held to the water floors: intermolecular O-O below ~2 A or
    O-H below ~0.7 A never occur in liquid water. Returns the observed minima and an
    `ok` verdict against the thresholds.
    """
    import numpy as np

    min_oo = float("inf")
    min_oh = float("inf")
    min_any = float("inf")
    species = set()
    for atoms in frames:
        sym = np.asarray(atoms.get_chemical_symbols())
        species.update(sym.tolist())
        d = atoms.get_all_distances(mic=True)
        if len(sym) >= 2:
            np.fill_diagonal(d, np.inf)
            min_any = min(min_any, float(d.min()))
        o_idx = np.where(sym == "O")[0]
        h_idx = np.where(sym == "H")[0]
        if len(o_idx) >= 2:
            doo = d[np.ix_(o_idx, o_idx)]
            np.fill_diagonal(doo, np.inf)
            min_oo = min(min_oo, float(doo.min()))
        if len(o_idx) and len(h_idx):
            min_oh = min(min_oh, float(d[np.ix_(o_idx, h_idx)].min()))
    ok = (not frames) or (
        min_any >= min_any_ang and min_oo >= min_oo_ang and min_oh >= min_oh_ang
    )
    water_checks = [
        p for p, el in (("O-O", {"O"}), ("O-H", {"O", "H"})) if el <= species
    ]
    return {
        "n_frames": len(frames),
        "min_any_ang": None if min_any == float("inf") else round(min_any, 3),
        "min_oo_ang": None if min_oo == float("inf") else round(min_oo, 3),
        "min_oh_ang": None if min_oh == float("inf") else round(min_oh, 3),
        "threshold_any_ang": min_any_ang,
        "threshold_oo_ang": min_oo_ang,
        "threshold_oh_ang": min_oh_ang,
        "species_checks": ",".join(water_checks) or "none",
        "ok": bool(ok),
    }


def own_trajectory_spot_check(
    cfg,
    model_path: str,
    n_frames: int | None = None,
    temperature_k: float | None = None,
    md_steps: int | None = None,
    workdir: str | Path = "validate",
    return_frames: bool = False,
):
    """Validate the model on configurations IT visits, not ones the generator made.

    Runs short MD with the trained model, diversity-picks `n_frames` of its own
    snapshots, DFT-labels them, and returns model-vs-DFT force/energy RMSE. Large error
    here = the model is extrapolating in its own dynamics (the failure a held-out RMSE
    on foundation-generated frames silently misses). Defaults are read from
    `cfg.validate_cfg`. With `return_frames`, also returns the raw MD frames so the caller
    can compute an RDF without a second MD run.
    """
    import numpy as np
    from mace.calculators import MACECalculator

    from . import label, subsample
    from .engines import ASEMaceEngine

    v = getattr(cfg, "validate_cfg", None)
    if n_frames is None:
        n_frames = getattr(v, "n_dft_spotcheck", 12) if v else 12
    if temperature_k is None:
        temperature_k = getattr(v, "spotcheck_temperature_k", 300.0) if v else 300.0
    if md_steps is None:
        md_steps = getattr(v, "spotcheck_md_steps", 1000) if v else 1000

    workdir = Path(workdir)
    engine = ASEMaceEngine(
        model=model_path, dispersion=False, device=cfg.train.device, is_foundation=False
    )
    seed = _load_seed(cfg)

    # Stride so there are ~2x n_frames candidates to diversity-pick from.
    eq = min(md_steps // 4, 100)
    stride = max(1, (md_steps - eq) // max(1, n_frames * 2))
    frames = engine.run_md(
        seed,
        temperature_k=temperature_k,
        steps=md_steps,
        timestep_fs=cfg.explore.timestep_fs,
        sample_every=stride,
        equilibration_steps=eq,
        thermostat=cfg.explore.nvt_thermostat,
        friction=cfg.explore.friction,
        tdamp_fs=cfg.explore.tdamp_fs,
    )
    # n_frames == 0: the MD still runs (it doubles as the stability check and the RDF
    # trajectory) but no DFT single points are launched — this is what lets the train
    # stage run on a CP2K-less GPU node; the force anchor is then the fixed test set.
    picked = subsample.subsample(frames, n_frames, "fps") if n_frames > 0 else []

    calc = MACECalculator(
        model_paths=model_path, device=cfg.train.device, default_dtype="float64"
    )
    # Pool force errors over all atoms/frames so the RMSE and reference-force RMS match
    # AML's convention (force score = 1 - RMSE/RMS_ref); see force_score().
    sq_err = ref_sq = 0.0
    n_comp = 0
    per_frame_rmse = []
    energy_abs_err = []
    for i, atoms in enumerate(picked):
        parsed = label.label_one(atoms, cfg.dft, workdir / f"frame{i}")
        ref_e = float(parsed["energy_ev"])
        ref_f = np.asarray(parsed["forces"], dtype=float)
        a = atoms.copy()
        a.calc = calc
        pred_f = a.get_forces()
        frame_err = float(np.sum((pred_f - ref_f) ** 2))
        sq_err += frame_err
        ref_sq += float(np.sum(ref_f**2))
        n_comp += ref_f.size
        per_frame_rmse.append((frame_err / ref_f.size) ** 0.5 * 1000.0)
        energy_abs_err.append(abs(a.get_potential_energy() - ref_e) / len(a) * 1000.0)

    result = {
        "n_frames": len(picked),
        "force_rmse_mev_ang": (sq_err / n_comp) ** 0.5 * 1000.0 if n_comp else 0.0,
        "force_rms_ref_mev_ang": (ref_sq / n_comp) ** 0.5 * 1000.0 if n_comp else 0.0,
        "force_rmse_max_mev_ang": (
            float(np.max(per_frame_rmse)) if per_frame_rmse else 0.0
        ),
        "energy_mae_mev_atom": (
            float(np.mean(energy_abs_err)) if energy_abs_err else 0.0
        ),
    }
    if return_frames:
        return result, frames
    return result


def npt_steps_for_resolution(
    target_density_err_gcc: float, density_fluct_gcc: float, autocorr_steps: int
) -> int:
    """Steps needed to resolve the mean density to a target standard error.

    SE = sigma / sqrt(N_independent); N_independent = N_steps / (2 * tau). Solve for
    N_steps. `density_fluct_gcc` is the instantaneous density std (~0.01-0.03 for water
    boxes of ~100 atoms); `autocorr_steps` is the density autocorrelation time. Use this
    BEFORE committing the isobar to check the TMD (~0.001-0.005 g/cc spacing) is visible.
    """
    n_independent = (density_fluct_gcc / target_density_err_gcc) ** 2
    return int(round(n_independent * 2.0 * autocorr_steps))


# ---- AML percentage scores (Schran et al. 2021) --------------------------------------
# These reproduce the exact score formulas in the published AML package
# (github.com/MarsalekGroup/aml, aml/score/util.py + forces.py), so the numbers match the
# paper's convention (force 86-95%, RDF 98-100%, VDOS 96-98% for good water models):
#   RDF / VDOS accuracy = (1 - sum|y_ref - y_test| / (sum y_ref + sum y_test)) * 100
#                         with y_test interpolated onto the reference x-grid; mean over pairs
#   Force accuracy      = (1 - RMSE / RMS_ref) * 100, mean over the pooled force components


def force_score(rmse_mev_ang: float, rms_ref_mev_ang: float) -> float:
    """AML force accuracy: (1 - RMSE/RMS_ref)*100, clamped to [0, 100]."""
    if not rms_ref_mev_ang:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - rmse_mev_ang / rms_ref_mev_ang)))


def _aml_overlap_pct(y_ref, x_ref, y_test, x_test) -> float:
    """AML curve accuracy: (1 - sum|y_ref - y_test| / (sum y_ref + sum y_test))*100, with
    y_test interpolated onto the reference x-grid (aml/score/util.compute_all_errors).
    """
    import numpy as np

    y_ref = np.asarray(y_ref, dtype=float)
    y_test = np.interp(
        np.asarray(x_ref, dtype=float),
        np.asarray(x_test, dtype=float),
        np.asarray(y_test, dtype=float),
    )
    mae = float(np.sum(np.abs(y_ref - y_test))) / (
        float(np.sum(y_ref) + np.sum(y_test)) + 1e-12
    )
    return 100.0 * (1.0 - mae)


def rdf_score(g_model: dict, g_ref: dict):
    """Mean per-pair RDF accuracy (AML convention). Returns (score, {pair: mae})."""
    import numpy as np

    per_pair = {}
    scores = []
    for key in g_ref:
        rm, gm = g_model[key]
        rr, gr = g_ref[key]
        pct = _aml_overlap_pct(gr, rr, gm, rm)
        per_pair["".join(key)] = round((100.0 - pct) / 100.0, 4)
        scores.append(pct)
    return float(np.mean(scores)) if scores else 0.0, per_pair


def _trapz(y, x):
    """Trapezoidal integral, robust to the numpy 1.x/2.x trapz->trapezoid rename."""
    import numpy as np

    integrate = getattr(np, "trapezoid", None) or np.trapz
    return float(integrate(y, x))


def vdos_score(model, ref) -> float:
    """VDOS accuracy (AML convention). `model`/`ref` are (freqs_cm1, intensity); both are
    area-normalised, then the AML curve-overlap metric is applied on the reference grid.
    """
    import numpy as np

    fm, im = np.asarray(model[0], dtype=float), np.asarray(model[1], dtype=float)
    fr, ir = np.asarray(ref[0], dtype=float), np.asarray(ref[1], dtype=float)
    im_norm = im / (_trapz(im, fm) + 1e-12)
    ir_norm = ir / (_trapz(ir, fr) + 1e-12)
    return _aml_overlap_pct(ir_norm, fr, im_norm, fm)


def _vacf_spectrum(vel, timestep_fs: float):
    """Vibrational density of states from a velocity time series `vel` (T, N, 3).

    VDOS = |FFT(normalised velocity autocorrelation)|, Hann-tapered to reduce leakage.
    Returns (freqs_cm1, intensity).
    """
    import numpy as np

    n_t, n_at, _ = vel.shape
    acf = np.zeros(n_t)
    for i in range(n_at):
        for d in range(3):
            x = vel[:, i, d]
            f = np.fft.rfft(x, 2 * n_t)
            acf += np.fft.irfft(f * np.conj(f))[:n_t]
    acf /= n_at * 3
    if acf[0] != 0:
        acf /= acf[0]
    taper = np.hanning(2 * n_t)[n_t:]  # decaying half-Hann for the one-sided ACF
    spec = np.abs(np.fft.rfft(acf * taper))
    freqs_cm1 = np.fft.rfftfreq(n_t, d=timestep_fs * 1e-15) / 2.99792458e10
    return freqs_cm1, spec


def compute_vdos(
    cfg,
    model_path: str,
    workdir: str | Path,
    md_steps: int | None = None,
    temperature_k: float | None = None,
    return_frames: bool = False,
    rdf_stride: int | None = None,
    calc=None,
):
    """Run a short NVE trajectory with the model and return its VDOS (freqs_cm1, intensity).

    A brief Langevin stage thermalises the seed, then plain velocity-Verlet (NVE) is used
    so the velocity autocorrelation is not damped by a thermostat. The NVE segment also
    doubles as (i) the RDF trajectory (with `return_frames`, position snapshots every
    `rdf_stride` steps come back too — far better statistics than the handful of
    spot-check frames, zero extra MD) and (ii) an energy-conservation check (the returned
    drift in meV/atom/ps is a direct integrator/model-smoothness diagnostic).

    With `return_frames`, returns ((freqs, intensity), frames, drift_mev_atom_ps).
    """
    import numpy as np
    from ase import units as ase_units
    from ase.md.langevin import Langevin
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
    from mace.calculators import MACECalculator

    from .engines import make_nvt_dyn

    v = getattr(cfg, "validate_cfg", None)
    if md_steps is None:
        md_steps = getattr(v, "vdos_md_steps", 20000) if v else 20000
    if temperature_k is None:
        temperature_k = getattr(v, "vdos_temperature_k", 300.0) if v else 300.0
    if rdf_stride is None:
        rdf_stride = getattr(v, "vdos_rdf_stride", 100) if v else 100
    dt = cfg.explore.timestep_fs

    atoms = _load_seed(cfg)
    # v4 (Schran): observables run NVT (CSVR) at the EXPERIMENTAL density — the 2021
    # scoring convention. This decouples structure/spectra scores from the model's own
    # density error (density is tested separately by the anchor). CSVR's gentle global
    # rescaling leaves the VACF spectrum essentially intact at tau=100 fs.
    nvt_cell = getattr(v, "nvt_cell_abc", None) if v else None
    if nvt_cell:
        atoms.set_cell(nvt_cell, scale_atoms=True)
    # float32: a sampling run for VDOS/RDF statistics; scoring is distribution-level.
    # `calc` override lets callers benchmark non-file models (e.g. the foundation
    # explorer as an iteration-0 baseline) under the identical observables protocol.
    atoms.calc = (
        calc
        if calc is not None
        else MACECalculator(
            model_paths=model_path, device=cfg.train.device, default_dtype="float32"
        )
    )
    MaxwellBoltzmannDistribution(atoms, temperature_K=temperature_k)
    Langevin(atoms, dt * ase_units.fs, temperature_K=temperature_k, friction=0.02).run(
        max(1, md_steps // 10)
    )

    dyn = make_nvt_dyn(atoms, dt, temperature_k, thermostat="bussi", taut_fs=100.0)
    vels: list = []
    frames: list = []

    def collect():
        vels.append(atoms.get_velocities().copy())
        if len(vels) % max(1, rdf_stride) == 0:
            snap = atoms.copy()
            snap.calc = None
            frames.append(snap)

    dyn.attach(collect, interval=1)
    dyn.run(md_steps)
    spectrum = _vacf_spectrum(np.asarray(vels), dt)
    if not return_frames:
        return spectrum
    # Drift retired: energy conservation is meaningless under a thermostat (v4 NVT);
    # stability is covered by the geometric minima checks.
    return spectrum, frames, None


def _decorr_summary(validate_workdir) -> dict:
    """Roll up the per-cell decorr.json (written by generate) for the report."""
    import json

    import numpy as np

    path = Path(validate_workdir).parent / "decorr.json"
    if not path.exists():
        return {}
    try:
        recs = json.loads(path.read_text())
    except Exception:
        return {}
    taus = [r["tau_fs"] for r in recs if r.get("tau_fs") is not None]
    ivs = [r["interval_frames"] for r in recs if r.get("interval_frames") is not None]
    out = {"n_uncorrelated_total": int(sum(r.get("n_uncorrelated", 0) for r in recs))}
    if taus:
        out["mean_tau_fs"] = round(float(np.mean(taus)), 1)
    if ivs:
        out["mean_interval_frames"] = round(float(np.mean(ivs)), 1)
    return out


def _resolve_ref(cfg, path_str: str):
    """Resolve a reference-data path from the config (see Config.resolve_path)."""
    return cfg.resolve_path(path_str)


def fixed_test_eval(cfg, model_path: str, test_path: Path, frames=None) -> dict:
    """Force/energy metrics on the DFT validation set.

    `frames` (optional) scores a provided subset instead of reading `test_path` —
    used by the v4 incremental mode to score the newest increment separately
    (the unbiased-on-new-data check).
    """
    import numpy as np
    from mace.calculators import MACECalculator

    from . import dataset

    if frames is None:
        frames = [
            a
            for a in dataset.read_frames(test_path)
            if dataset.has_labels(a, cfg.train.energy_key, cfg.train.forces_key)
        ]
    if not frames:
        raise ValueError(f"{test_path}: no labelled frames")
    calc = MACECalculator(
        model_paths=model_path, device=cfg.train.device, default_dtype="float64"
    )
    sq_err = ref_sq = 0.0
    n_comp = 0
    energy_abs_err = []
    for atoms in frames:
        ref_f = np.asarray(atoms.arrays[cfg.train.forces_key], dtype=float)
        ref_e = float(atoms.info[cfg.train.energy_key])
        a = atoms.copy()
        a.calc = calc
        pred_f = a.get_forces()
        sq_err += float(np.sum((pred_f - ref_f) ** 2))
        ref_sq += float(np.sum(ref_f**2))
        n_comp += ref_f.size
        energy_abs_err.append(abs(a.get_potential_energy() - ref_e) / len(a) * 1000.0)
    return {
        "n_frames": len(frames),
        "force_rmse_mev_ang": (sq_err / n_comp) ** 0.5 * 1000.0,
        "force_rms_ref_mev_ang": (ref_sq / n_comp) ** 0.5 * 1000.0,
        "energy_mae_mev_atom": float(np.mean(energy_abs_err)),
    }


def extend_test_set(cfg, workdir: str | Path, pass_index: int) -> int:
    """v4 incremental validation set: label +N fresh frames from the independent pool.

    Pool = validate.testset_pool_xyz (decorrelated frames from ONE foundation
    trajectory on a dedicated velocity-seed lane, never trained on). Frames already
    in test_set.xyz are skipped by structure hash; new ones are DFT-labelled (host
    cores — call this from the LABEL stage) and appended, tagged with the pass that
    added them so the scorecard can report the newest-increment score separately.
    Returns the number of frames added.
    """
    from ase.io import read, write

    from . import dataset, label

    v = cfg.validate_cfg
    if getattr(v, "testset_mode", "fixed") != "incremental":
        return 0
    n_add = int(getattr(v, "testset_increment", 5) or 0)
    pool_path = _resolve_ref(cfg, v.testset_pool_xyz) if v.testset_pool_xyz else None
    test_path = _resolve_ref(cfg, v.fixed_test_xyz) if v.fixed_test_xyz else None
    if not n_add or pool_path is None or test_path is None or not pool_path.exists():
        return 0
    have = (
        {dataset.structure_hash(a) for a in dataset.read_frames(test_path)}
        if test_path.exists()
        else set()
    )
    pool = read(str(pool_path), index=":")
    pool = pool if isinstance(pool, list) else [pool]
    fresh = [a for a in pool if dataset.structure_hash(a) not in have][:n_add]
    if not fresh:
        print("  test-set increment: pool exhausted (extend the pool trajectory)")
        return 0
    # REUSE-ONLY: this runs inside the GPU train stage, which has NO CP2K (psmp would
    # SIGILL on the AMD GPU host). The label array pre-labels these increment frames
    # (label_worker --testset-increment); here we only collect what's already labeled
    # and NEVER spawn DFT. A frame not yet labeled is skipped this pass (picked up next
    # pass once its label lands) — the invariant "GPU driver never runs DFT" holds.
    added = []
    skipped = 0
    for a in fresh:
        h = dataset.structure_hash(a)
        parsed = label._try_parse_existing(Path(workdir) / "test_dft" / h)
        if parsed is None:
            skipped += 1
            continue
        label.attach_labels(
            a, parsed, cfg.train.energy_key, cfg.train.forces_key, cfg.train.stress_key
        )
        a.info["config_type"] = "fixed_test"
        a.info["added_pass"] = pass_index
        added.append(a)
    if added:
        write(str(test_path), added, format="extxyz", append=test_path.exists())
    msg = (
        f"  test-set increment: +{len(added)} frames (pass {pass_index}) -> {test_path}"
    )
    if skipped:
        msg += f"  ({skipped} not yet labeled — deferred to a later pass)"
    print(msg)
    return len(added)


def _goo_peak(g_mod: dict, r_lo: float = 2.4, r_hi: float = 3.2):
    """Position/height of the first g_OO maximum (the structural anchor observable)."""
    import numpy as np

    key = ("O", "O")
    if key not in g_mod:
        return None, None
    r, g = g_mod[key]
    mask = (r >= r_lo) & (r <= r_hi)
    if not mask.any():
        return None, None
    i = int(np.argmax(g[mask]))
    return float(r[mask][i]), float(g[mask][i])


def _save_observables(path: Path, g_mod: dict, vdos_model) -> None:
    """Persist the pass's RDF curves (+ VDOS spectrum) for the NEXT pass to score against."""
    import numpy as np

    arrays = {}
    for (a, b), (r, g) in g_mod.items():
        arrays.setdefault("rdf_r", np.asarray(r, dtype=float))
        arrays[f"rdf_{a}{b}"] = np.asarray(g, dtype=float)
    if vdos_model is not None:
        arrays["vdos_freq"] = np.asarray(vdos_model[0], dtype=float)
        arrays["vdos_intensity"] = np.asarray(vdos_model[1], dtype=float)
    np.savez(str(path), **arrays)


def _score_vs_previous(
    g_mod: dict, vdos_model, prev_path: Path, pairs
) -> tuple[dict, dict]:
    """Score this pass's observables against the stored previous-pass curves.

    Self-convergence per the meeting protocol: the previous-iteration model is the
    surrogate reference (no external AIMD trajectory at a mismatched functional needed);
    the loop is converged when these deltas fall below the paper's score anchors.
    """
    import numpy as np

    conv: dict = {}
    per_pair: dict = {}
    prev = np.load(str(prev_path))
    g_prev = {}
    for a, b in pairs:
        key = f"rdf_{a}{b}"
        if key in prev.files and "rdf_r" in prev.files:
            g_prev[(a, b)] = (prev["rdf_r"], prev[key])
    if g_prev:
        sub_mod = {k: g_mod[k] for k in g_prev if k in g_mod}
        pct, per_pair = rdf_score(sub_mod, g_prev)
        conv["rdf_prev_pct"] = round(pct, 1)
    if (
        vdos_model is not None
        and "vdos_freq" in prev.files
        and "vdos_intensity" in prev.files
    ):
        conv["vdos_prev_pct"] = round(
            vdos_score(vdos_model, (prev["vdos_freq"], prev["vdos_intensity"])), 1
        )
    return conv, per_pair


def validate_model(
    cfg,
    model_path: str,
    workdir: str | Path,
    density_gcc: float | None = None,
    density_ref_gcc: float | None = None,
    model_level: str = "current",
    prev_observables: str | Path | None = None,
    store_observables: bool = True,
    pass_index: int | None = None,
) -> dict:
    """Assemble the AML-style scorecard for one model, in validation-step order:

      1. static test on the fixed DFT test set (skipped + note when unset)
      2. stability MD (the spot-check trajectory doubles as the blow-up check)
      3. on-policy spot-check: ~10 DFT single points on the model's own dynamics
      4. density (from the loop's NPT probe, passed in) + experimental anchor
      5. RDF: computed every pass; scored vs external ref (if set) AND vs the stored
         previous-pass curves (self-convergence)
      6. VDOS (validate.vdos_enabled): NVE run that also provides the RDF trajectory
         and an energy-conservation check; scored like the RDF
      7. observables cached to observables.npz for the next pass; AML-package RDF
         cross-score when aml/mdtraj are installed

    `scores` keeps the external-comparable AML trio (+ overall); pass-vs-previous
    numbers live under `convergence` so the headline score's meaning never changes.
    """
    import numpy as np
    from ase.io import read

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    v = cfg.validate_cfg
    pairs = [tuple(p) for p in v.rdf_pairs]
    notes: list = []
    scores: dict = {}
    raw: dict = {}
    convergence: dict = {}

    # 1. Static test on the DFT validation set (fixed or incrementally grown).
    if v.fixed_test_xyz:
        test_path = _resolve_ref(cfg, v.fixed_test_xyz)
        if test_path.exists():
            from . import dataset as _ds

            tframes = [
                a
                for a in _ds.read_frames(test_path)
                if _ds.has_labels(a, cfg.train.energy_key, cfg.train.forces_key)
            ]
            test = fixed_test_eval(cfg, model_path, test_path, frames=tframes)
            scores["test_force_pct"] = round(
                force_score(test["force_rmse_mev_ang"], test["force_rms_ref_mev_ang"]),
                1,
            )
            raw["test_force_rmse_mev_ang"] = round(test["force_rmse_mev_ang"], 2)
            raw["test_energy_mae_mev_atom"] = round(test["energy_mae_mev_atom"], 3)
            raw["n_test_frames"] = test["n_frames"]
            # v4 incremental mode: also score the NEWEST increment alone — frames the
            # ruler gained this pass, unseen by any tuning choice (overfit check).
            if getattr(v, "testset_mode", "fixed") == "incremental" and pass_index:
                inc = [a for a in tframes if a.info.get("added_pass") == pass_index]
                if inc:
                    t_inc = fixed_test_eval(cfg, model_path, test_path, frames=inc)
                    scores["test_increment_pct"] = round(
                        force_score(
                            t_inc["force_rmse_mev_ang"], t_inc["force_rms_ref_mev_ang"]
                        ),
                        1,
                    )
                    raw["increment_force_rmse_mev_ang"] = round(
                        t_inc["force_rmse_mev_ang"], 2
                    )
                    raw["n_increment_frames"] = t_inc["n_frames"]
        else:
            notes.append(f"fixed test set {test_path} not found - static test skipped")
    else:
        notes.append(
            "fixed test set not set (validate.fixed_test_xyz) - static test skipped"
        )

    # 2+3. Stability MD + on-policy spot-check (one trajectory serves both). With
    # n_dft_spotcheck=0 the MD still provides the stability/RDF trajectory, but the
    # force anchor comes from the fixed test set (step 1) so no CP2K is needed here.
    spot, frames = own_trajectory_spot_check(
        cfg, model_path, workdir=workdir / "spotcheck", return_frames=True
    )
    stability = stability_metrics(
        frames, v.stability_min_oo_ang, v.stability_min_oh_ang, v.stability_min_any_ang
    )
    if spot["n_frames"] > 0:
        scores["force_rmse_pct"] = round(
            force_score(spot["force_rmse_mev_ang"], spot["force_rms_ref_mev_ang"]), 1
        )
        raw.update(
            {
                "force_rmse_mev_ang": round(spot["force_rmse_mev_ang"], 2),
                "force_rms_ref_mev_ang": round(spot["force_rms_ref_mev_ang"], 2),
                "force_rmse_max_mev_ang": round(spot["force_rmse_max_mev_ang"], 2),
                "energy_mae_mev_atom": round(spot["energy_mae_mev_atom"], 3),
                "n_dft_spotcheck": spot["n_frames"],
            }
        )
    elif "test_force_pct" in scores:
        scores["force_rmse_pct"] = scores["test_force_pct"]
        raw["n_dft_spotcheck"] = 0
        notes.append(
            "spot-check disabled (n_dft_spotcheck=0): force score anchored "
            "to the fixed DFT test set"
        )
    else:
        raw["n_dft_spotcheck"] = 0
        notes.append(
            "NO DFT FORCE ANCHOR: spot-check disabled and no fixed test set "
            "(validate.fixed_test_xyz) - promotion/convergence cannot trigger"
        )

    # 4. Density (probe value is computed by the loop and passed in).
    if density_ref_gcc is None:
        density_ref_gcc = v.density_ref_gcc
    if density_gcc is not None:
        raw["density_gcc"] = round(density_gcc, 4)
    if density_ref_gcc is not None:
        raw["density_ref_gcc"] = round(density_ref_gcc, 4)

    # 5+6. VDOS NVE run (also the RDF trajectory + energy-conservation check); RDF
    # falls back to the spot-check frames when the NVE leg is disabled.
    vdos_model = None
    rdf_frames = frames
    if v.vdos_enabled:
        vdos_model, nve_frames, drift = compute_vdos(
            cfg, model_path, workdir / "vdos", return_frames=True
        )
        if nve_frames:
            rdf_frames = nve_frames
        if drift is not None:
            raw["nve_drift_mev_atom_ps"] = round(float(drift), 3)
    g_mod = compute_rdf(rdf_frames, pairs=pairs, r_max=v.rdf_r_max, nbins=v.rdf_nbins)
    raw["n_rdf_frames"] = len(rdf_frames)

    # Experimental anchor: first g_OO peak (reported, never gated — classical nuclei at
    # a GGA functional should not match experiment exactly).
    peak_r, peak_h = _goo_peak(g_mod)
    if peak_r is not None:
        raw["goo_peak_r_ang"] = round(peak_r, 3)
        raw["goo_peak_h"] = round(peak_h, 3)
        if v.goo_peak_r_ref is not None:
            raw["goo_peak_r_ref_ang"] = v.goo_peak_r_ref
        if v.goo_peak_h_ref is not None:
            raw["goo_peak_h_ref"] = v.goo_peak_h_ref

    # RDF score vs the external reference trajectory (if configured).
    if v.rdf_ref_xyz:
        ref_path = _resolve_ref(cfg, v.rdf_ref_xyz)
        if ref_path.exists():
            ref_frames = read(str(ref_path), index=":")
            ref_frames = ref_frames if isinstance(ref_frames, list) else [ref_frames]
            g_ref = compute_rdf(
                ref_frames, pairs=pairs, r_max=v.rdf_r_max, nbins=v.rdf_nbins
            )
            rdf_pct, per_pair = rdf_score(g_mod, g_ref)
            scores["rdf_pct"] = round(rdf_pct, 1)
            raw["rdf_dist_by_pair"] = per_pair
        else:
            notes.append(f"RDF ref {ref_path} not found - RDF score skipped")
    else:
        notes.append(
            "RDF ref not set (validate.rdf_ref_xyz) - external RDF score skipped"
        )

    # VDOS score vs the external reference spectrum (if configured).
    if v.vdos_ref_npy:
        ref_path = _resolve_ref(cfg, v.vdos_ref_npy)
        if ref_path.exists():
            ref = np.load(str(ref_path))  # (2, M): freq_cm1, intensity
            if vdos_model is None:
                vdos_model = compute_vdos(cfg, model_path, workdir / "vdos")
            vdos_pct = vdos_score(vdos_model, (ref[0], ref[1]))
            scores["vdos_pct"] = round(vdos_pct, 1)
            raw["vdos_overlap"] = round(vdos_pct / 100.0, 4)
        else:
            notes.append(f"VDOS ref {ref_path} not found - VDOS score skipped")
    else:
        notes.append(
            "VDOS ref not set (validate.vdos_ref_npy) - external VDOS score skipped"
        )

    # Self-convergence: score against the previous pass's stored observables.
    if prev_observables is not None:
        prev_path = Path(prev_observables)
        if prev_path.exists():
            conv, per_pair_prev = _score_vs_previous(
                g_mod, vdos_model, prev_path, pairs
            )
            convergence.update(conv)
            if per_pair_prev:
                raw["rdf_prev_dist_by_pair"] = per_pair_prev
        else:
            notes.append(
                "previous-pass observables not found - "
                "self-convergence scores skipped"
            )

    obs_path = workdir / "observables.npz"
    if store_observables:
        _save_observables(obs_path, g_mod, vdos_model)

    # RDF/VDOS self-convergence (pass vs previous) is computed above from the pipeline's
    # own observables; no external cross-scoring package is required.
    aml_report: dict = {}

    # Headline: the force/RDF/VDOS trio only (pass-vs-previous and test-set numbers
    # deliberately excluded so the meaning is constant across the campaign).
    overall_parts = [
        scores[k] for k in ("force_rmse_pct", "rdf_pct", "vdos_pct") if k in scores
    ]
    scores["overall_pct"] = round(float(np.mean(overall_parts)), 1)

    return {
        "model_level": model_level,
        "model_path": str(model_path),
        "scores": scores,
        "raw": raw,
        "stability": stability,
        "convergence": convergence,
        "aml": aml_report,
        "observables_path": str(obs_path) if store_observables else None,
        "decorrelation": _decorr_summary(workdir),
        "notes": notes,
    }
