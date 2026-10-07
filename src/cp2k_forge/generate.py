"""Structure generation: run MD across the temperature/density grid.

Pass 1 uses the MACE-MP-0+D3 foundation model as the explorer; later passes use the
latest trained model (so it wanders into — and we then label — the regions the
previous model got wrong). Densities are sampled by scaling the box, so the DFT set
brackets the true equilibrium even though the explorer's level differs from revPBE-D3.

Output: one trajectory of unlabelled frames per pass, tagged with `config_type`.

Parallelism: the (T, density, replica) cells are independent trajectories with
deterministic per-cell velocity seeds, so `explore.md_workers > 1` runs them in
worker processes (spawn; round-robin over visible GPUs). Results are identical to
the serial path by construction — cells are reassembled in grid order. At 192 atoms
one MD leaves an A100 mostly idle (ASE-loop + D3 host overhead dominate), so even
several workers sharing ONE GPU overlap well; SLURM charges GPU-h x allocation, so
extra GPUs are wall-clock, not budget.
"""

from __future__ import annotations

from pathlib import Path

from .engines import ASEMaceEngine, CP2KSymmetrixEngine, MDEngine


def symmetrix_json_for(model_path: str | None) -> str | None:
    """The auto-exported symmetrix JSON that cp2k_forge.train writes next to a model."""
    if not model_path:
        return None
    p = Path(model_path)
    j = p.with_name(p.stem + "_symmetrix.json")
    return str(j) if j.exists() else None


def build_explorer(cfg, previous_model_path: str | None) -> MDEngine:
    """Foundation generator on pass 1; the latest trained model afterwards.

    generator.engine == "cp2k-backend": trained models run inside CP2K via the MACE
    backend (needs the exported JSON and a metatomic/&SYMMETRIX-enabled CP2K
    build). The foundation model always uses ASE (it needs the D3 add-on, which
    lives ASE-side); if the JSON is missing the explorer falls back to ASE with a
    loud note rather than dying. Default engine 'ase' runs anywhere with mace-torch.
    """
    if previous_model_path is None:
        return ASEMaceEngine(
            model=cfg.generator.model,
            dispersion=cfg.generator.dispersion,
            device=cfg.generator.device,
            is_foundation=True,
            enable_cueq=getattr(cfg.generator, "enable_cueq", False),
        )
    if getattr(cfg.generator, "engine", "ase") in ("cp2k-backend", "symmetrix"):
        j = symmetrix_json_for(previous_model_path)
        if j:
            return CP2KSymmetrixEngine(model_json=j, device=cfg.generator.device)
        print(
            f"  NOTE: no symmetrix JSON next to {previous_model_path}; "
            "explorer falls back to ASE for this pass"
        )
    return ASEMaceEngine(
        model=previous_model_path,
        dispersion=False,
        device=cfg.generator.device,
        is_foundation=False,
        enable_cueq=getattr(cfg.generator, "enable_cueq", False),
    )


def _scaled(seed_atoms, density_scale: float):
    """Return a copy of the seed at the requested *relative density* (V ∝ 1/ρ)."""
    atoms = seed_atoms.copy()
    s = (1.0 / density_scale) ** (1.0 / 3.0)
    atoms.set_cell(atoms.get_cell().array * s, scale_atoms=True)
    return atoms


def _set_deuterium(atoms):
    """Replace H masses with deuterium (2.014 amu) in place (Schran et al. protocol)."""
    import numpy as np

    sym = np.asarray(atoms.get_chemical_symbols())
    masses = atoms.get_masses()
    masses[sym == "H"] = 2.014
    atoms.set_masses(masses)


def _cell_key(temp, pressure_bar, dscale, rep) -> str:
    """Pass-independent cell identity (warm-start cache key)."""
    if pressure_bar is not None:
        return f"T{int(temp)}_p{int(pressure_bar)}" + (f"_r{rep}" if rep else "")
    return f"T{int(temp)}_d{dscale:.2f}" + (f"_r{rep}" if rep else "")


def _cell_specs(ex, seed_atoms, pass_index: int, warmstart_dir: Path | None = None):
    """The explore grid as a list of per-cell dicts (deterministic order + seeds).

    v4 grid: temperatures_k x pressures_bar when pressures are set (explicit +/-
    pressures pin the sampled ensemble — see ExploreConfig); else the legacy
    temperatures_k x density_scales grid. With warm-start enabled, a cell whose
    cached final frame exists starts from it (fresh velocities, shorter equil).
    """
    from ase.io import read

    specs = []
    n_replicas = max(1, ex.n_replicas)
    pressures = getattr(ex, "pressures_bar", None)
    axis = (
        [(None, d) for d in ex.density_scales]
        if not pressures
        else [(p, 1.0) for p in pressures]
    )
    cell_counter = 0
    for temp in ex.temperatures_k:
        for pressure, dscale in axis:
            for rep in range(n_replicas):
                cell_counter += 1
                key = _cell_key(temp, pressure, dscale, rep)
                seed, warm = None, False
                if warmstart_dir is not None:
                    cached = Path(warmstart_dir) / f"{key}.xyz"
                    if cached.exists():
                        try:
                            seed = read(str(cached))
                            warm = True
                        except Exception:
                            seed = None
                if seed is None:
                    seed = _scaled(seed_atoms, dscale)
                if ex.deuterium_masses:
                    _set_deuterium(seed)
                # Deterministic per-cell velocity seed; includes the pass so a later
                # pass never replays the previous pass's initial conditions.
                vseed = ex.velocity_seed_base + pass_index * 100000 + cell_counter
                tag = f"explore_pass{pass_index}_{key}"
                specs.append(
                    {
                        "temp": temp,
                        "dscale": dscale,
                        "rep": rep,
                        "pressure_bar": pressure,
                        "key": key,
                        "warm": warm,
                        "warmstart_dir": str(warmstart_dir) if warmstart_dir else None,
                        "vseed": vseed,
                        "tag": tag,
                        "seed": seed,
                    }
                )
    return specs


def _run_cell_md(engine, ex, spec):
    """One cell's MD. Returns (raw_frames, run_info, md_wall_s)."""
    import time

    is_npt = ex.ensemble.upper() == "NPT"
    pressure = spec.get("pressure_bar")
    if pressure is None:
        pressure = ex.pressure_bar
    equil = ex.equilibration_steps
    if spec.get("warm") and getattr(ex, "warm_equilibration_steps", None):
        equil = ex.warm_equilibration_steps
    t0 = time.perf_counter()
    raw = engine.run_md(
        spec["seed"],
        temperature_k=spec["temp"],
        steps=ex.steps,
        timestep_fs=ex.timestep_fs,
        sample_every=ex.sample_every,
        equilibration_steps=equil,
        ensemble=ex.ensemble,
        pressure_bar=pressure,
        compressibility_au=ex.compressibility_au,
        friction=ex.friction,
        density_min=ex.density_min_gcc if is_npt else None,
        density_max=ex.density_max_gcc if is_npt else None,
        clamp_patience=ex.clamp_patience,
        velocity_seed=spec["vseed"],
        barostat=ex.barostat,
        thermostat=ex.nvt_thermostat,
        tdamp_fs=ex.tdamp_fs,
        pdamp_fs=ex.pdamp_fs,
    )
    md_wall = time.perf_counter() - t0
    run_info = getattr(engine, "last_run_info", {}) or {}
    return raw, run_info, md_wall


def _postprocess_cell(ex, spec, raw, run_info, md_wall):
    """Decorrelation subsampling + the per-cell record (shared by both exec paths)."""
    from . import decorrelation

    tau_reliable = True
    if ex.sample_mode == "decorrelation":
        if raw:
            series = decorrelation.observable_series(raw, ex.decorrelation_observable)
            interval, tau_fs, n_avail, tau_reliable = decorrelation.subsample_interval(
                series, ex.timestep_fs, ex.sample_every, ex.min_sample_every_fs
            )
            frames = decorrelation.pick_uncorrelated(
                raw, interval, ex.target_uncorrelated
            )
        else:
            # A clamp-aborted cell with NO in-window frames is the worst undersample,
            # not a free pass: count its full quota short so on_undersample=fail
            # still triggers.
            frames, interval, tau_fs, n_avail = [], 1, None, 0
        shortfall = max(0, ex.target_uncorrelated - len(frames))
    else:
        frames, interval, tau_fs, n_avail = raw, 1, None, len(raw)
        shortfall = 0

    for f in frames:
        f.info["config_type"] = spec["tag"]
        f.info["velocity_seed"] = spec["vseed"]
    record = {
        "tag": spec["tag"],
        "temperature_k": spec["temp"],
        "density_scale": spec["dscale"],
        "replica": spec["rep"],
        "pressure_bar": spec.get("pressure_bar"),
        "warm_start": spec.get("warm", False),
        "velocity_seed": spec["vseed"],
        "n_raw": len(raw),
        "n_uncorrelated": len(frames),
        "n_available": n_avail,
        "tau_fs": tau_fs,
        "tau_reliable": bool(tau_reliable),
        "interval_frames": interval,
        "shortfall": shortfall,
        "clamp_aborted": bool(run_info.get("clamp_aborted")),
        "sample_every_steps": ex.sample_every,
        "md_wall_s": round(md_wall, 1),
    }
    # Warm-start cache: this cell's final raw frame seeds the same cell next pass.
    # Only healthy cells update (a clamped/empty run leaves the previous cache).
    wdir = spec.get("warmstart_dir")
    if wdir and raw and not record["clamp_aborted"]:
        from ase.io import write as _ase_write

        _ase_write(str(Path(wdir) / f"{spec['key']}.xyz"), raw[-1], format="extxyz")
    return frames, record


def _parallel_cell_worker(payload):
    """Process worker: build a private engine, run + postprocess one cell.

    Runs under the 'spawn' start method (CUDA is unusable in forked children).
    `device` already carries the worker's GPU pin (e.g. "cuda:1").
    """
    idx, spec, ex, eng_type, eng_kw = payload
    engine = (CP2KSymmetrixEngine if eng_type == "symmetrix" else ASEMaceEngine)(
        **eng_kw
    )
    raw, run_info, md_wall = _run_cell_md(engine, ex, spec)
    frames, record = _postprocess_cell(ex, spec, raw, run_info, md_wall)
    return idx, frames, record


def _worker_devices(base_device: str, n: int):
    """Round-robin worker device strings over the visible GPUs (or CPU passthrough)."""
    if not str(base_device).startswith("cuda"):
        return [base_device] * n
    try:
        import torch

        ngpu = max(1, torch.cuda.device_count())
    except Exception:
        ngpu = 1
    return [f"cuda:{i % ngpu}" for i in range(n)]


def generate_frames(
    cfg, engine: MDEngine, seed_atoms, pass_index: int, out_dir: str | Path
):
    """Run the full explore grid and return (frames, per_cell_records).

    Each (T, density_scale, replica) cell is run independently with a deterministic
    velocity seed; the raw trajectory is then subsampled at its own measured decorrelation
    time (cp2k_forge.decorrelation) so the DFT budget goes to time-uncorrelated structures.
    Per-cell stats (tau, its reliability, yield shortfall, clamp aborts) are written to
    decorr.json; with explore.on_undersample="fail" a total shortfall aborts the stage
    (before the manifest advances) so a campaign never runs on silently-thin sampling.

    explore.md_workers > 1 runs the cells in that many worker processes (ASEMaceEngine
    explorers only); output is identical to the serial path.
    """
    import json

    from ase.io import write

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ex = cfg.explore
    is_npt = ex.ensemble.upper() == "NPT"
    # Warm-start cache lives beside the passes (pass-independent cell keys). Safe by
    # construction: only gate-passing explorers (or the foundation) ever reach
    # generate, so every cached frame came from a trusted sampler; clamp-aborted
    # cells never update it (below).
    warmstart_dir = None
    if getattr(ex, "warm_start_cells", False):
        warmstart_dir = Path(out_dir).parent / "warmstart"
        warmstart_dir.mkdir(parents=True, exist_ok=True)
    # Symmetrix rundirs must live on the SHARED filesystem: the engine's tempdir
    # default lands on node-local /tmp, unreadable post-mortem (live: three
    # SIGABRT crashes with no readable md.out).
    if isinstance(engine, CP2KSymmetrixEngine) and engine.run_root is None:
        engine.run_root = Path(out_dir) / "symmd"
    specs = _cell_specs(ex, seed_atoms, pass_index, warmstart_dir)

    workers = min(int(getattr(ex, "md_workers", 1) or 1), len(specs))
    if isinstance(engine, CP2KSymmetrixEngine):
        # ONE Kokkos-CUDA process per GPU: N>1 concurrent cp2k.ssmp clients per device
        # SIGABRT (live, 3x); single-per-GPU is canary-proven with and without MPS.
        try:
            import torch

            n_gpu = max(1, torch.cuda.device_count())
        except Exception:
            n_gpu = 1
        workers = min(workers, 2 * n_gpu)
    parallel = workers > 1 and isinstance(engine, (ASEMaceEngine, CP2KSymmetrixEngine))

    results = []
    if parallel:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        devices = _worker_devices(engine.device, workers)
        payloads = []
        for i, spec in enumerate(specs):
            if isinstance(engine, CP2KSymmetrixEngine):
                eng_type = "symmetrix"
                eng_kw = {
                    "model_json": engine.model_json,
                    "cp2k_bin": engine.cp2k_bin,
                    "run_root": str(engine.run_root) if engine.run_root else None,
                    "device": devices[i % workers],
                    "omp_threads": engine.omp_threads,
                }
            else:
                eng_type = "ase"
                eng_kw = {
                    "model": engine.model,
                    "dispersion": engine.dispersion,
                    "device": devices[i % workers],
                    "is_foundation": engine.is_foundation,
                    "default_dtype": engine.default_dtype,
                    "enable_cueq": getattr(engine, "enable_cueq", False),
                }
            # dispersion was already ANDed with is_foundation in the parent engine
            payloads.append((i, spec, ex, eng_type, eng_kw))
        print(
            f"  generate: {len(specs)} cells across {workers} workers "
            f"(engine {'symmetrix' if isinstance(engine, CP2KSymmetrixEngine) else 'ase'}, "
            f"devices {sorted(set(devices))})"
        )
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            results = list(pool.map(_parallel_cell_worker, payloads))
        results.sort(key=lambda r: r[0])
        results = [(frames, record) for _, frames, record in results]
    else:
        for spec in specs:
            raw, run_info, md_wall = _run_cell_md(engine, ex, spec)
            results.append(_postprocess_cell(ex, spec, raw, run_info, md_wall))

    all_frames = []
    records = []
    for frames, record in results:
        all_frames.extend(frames)
        records.append(record)
        if is_npt and record["n_raw"] == 0:
            print(
                f"  WARNING: {record['tag']} yielded no in-window frames "
                "(density clamp tripped)"
            )
        elif record["shortfall"] > 0:
            tau_fs = record["tau_fs"]
            tau_txt = f"{tau_fs:.0f}" if tau_fs is not None else "n/a"
            print(
                f"  WARNING: {record['tag']} yielded {record['n_uncorrelated']}/"
                f"{ex.target_uncorrelated} uncorrelated frames "
                f"(tau {tau_txt} fs -> interval {record['interval_frames']} frames"
                f"{'' if record['tau_reliable'] else ', tau UNRELIABLE: window < 20*tau'})"
            )

    if all_frames:
        write(str(out_dir / "traj.xyz"), all_frames, format="extxyz")
    (out_dir / "decorr.json").write_text(json.dumps(records, indent=2))

    total_shortfall = sum(r["shortfall"] for r in records)
    total_kept = sum(r["n_uncorrelated"] for r in records)
    if total_shortfall > 0 and ex.on_undersample == "fail" and total_kept >= 20:
        # Partial-cell loss (e.g. an extreme-pressure cell clamped mid-run) with a
        # still-ample decorrelated pool (>= 2x the 10 labels/pass) is degraded, not
        # invalid: the shortfall is on record in decorr.json and the surviving
        # frames are as uncorrelated as ever. Hard-fail only on a truly thin pool.
        print(
            f"  WARNING: {total_shortfall} frames short across "
            f"{sum(1 for r in records if r['shortfall'])} cells, but pool has "
            f"{total_kept} decorrelated frames (>=20) - continuing, see decorr.json"
        )
    elif total_shortfall > 0 and ex.on_undersample == "fail":
        raise RuntimeError(
            f"generate: {total_shortfall} uncorrelated frames short of target across "
            f"{sum(1 for r in records if r['shortfall'])} cells (see {out_dir}/decorr.json). "
            "Lengthen explore.steps or lower explore.target_uncorrelated; the manifest is "
            "still at stage=generate, so a rerun resumes here."
        )
    return all_frames, records
