"""DFT labelling stage: run a CP2K single point per structure and attach labels.

Each candidate frame gets a revPBE-D3 energy+force(+stress) from CP2K, written into
the MACE reference keys and appended to the dataset. Labelling is resumable: a frame
whose hash is already in the manifest's done-list is skipped, so a killed run does not
recompute finished single points.

CP2K invocation is overridable by environment so the same run works on any machine:
    CP2K_BIN            (default: dft.cp2k_bin)      path to the CP2K binary
    CP2K_MPI_LAUNCHER   (default: "mpirun")          use "none" for an OMP-only build
    CP2K_RANKS          (default: dft.cp2k_ranks)    MPI ranks per single point
    CP2K_OMP_THREADS    (default: auto from cores)   OMP threads per rank
CP2K also needs its data files (BASIS_MOLOPT, GTH_POTENTIALS, dftd3.dat): set the
standard CP2K_DATA_DIR, or leave it unset and a directory next to the binary's
install tree is derived and exported to the subprocess (see cp2k_forge.cp2k_env).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import cp2k_env, cp2k_io, dataset


def _cp2k_command(inp: Path, out: Path, dft) -> list[str]:
    binary = cp2k_env.configured_binary(dft)
    launcher = os.environ.get("CP2K_MPI_LAUNCHER", "mpirun")
    ranks = os.environ.get("CP2K_RANKS", str(dft.cp2k_ranks))
    if launcher in ("none", "direct", ""):
        # ssmp (OMP-only) binary: no MPI launcher — used when labelling on a GPU
        # node's host cores with the metatomic/symmetrix build.
        return [binary, "-i", str(inp), "-o", str(out)]
    return [launcher, "-np", str(ranks), binary, "-i", str(inp), "-o", str(out)]


def _cp2k_subprocess_env(dft, workers: int = 1) -> dict:
    """Environment for the CP2K subprocess with the thread count + CPU affinity restored.

    The driver imports torch (generation/training); torch/MKL leave the process at
    OMP_NUM_THREADS=1 and may pin CPU affinity, which the CP2K subprocess would inherit and
    then run on only (ranks x 1) cores (observed: 4 cores -> ~895 s/frame vs ~78 s on a full
    node). Force a sane per-rank OMP thread count and widen affinity back to the whole node.

    With `workers` concurrent frames on the node, each frame gets ncpu/(ranks*workers)
    threads/rank so the node is shared, not oversubscribed. One 192-atom point stops
    scaling near ~16 cores (calibration: 64 cores 186 s vs 76 cores 188 s), so several
    modest-width frames beat one wide one.
    """
    env = dict(os.environ)
    # CP2K resolves bare data-file names (BASIS_MOLOPT, ...) against CP2K_DATA_DIR;
    # when unset, derive it from the binary's install tree so a standard install
    # needs no environment setup. The preflight reports the same derived path.
    if not env.get("CP2K_DATA_DIR"):
        derived = cp2k_env.derive_data_dir(cp2k_env.resolve_binary(dft))
        if derived is not None:
            env["CP2K_DATA_DIR"] = str(derived)
    ranks = int(os.environ.get("CP2K_RANKS", dft.cp2k_ranks))
    # The JOB's cores, not the node's: os.cpu_count() sees all 128 on a shared GPU
    # node while SLURM allocated 64 -> 2x oversubscription (live: 40 min/frame
    # instead of 8). SLURM_CPUS_PER_TASK is authoritative when present.
    ncpu = int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
    threads = os.environ.get("CP2K_OMP_THREADS") or str(
        max(1, ncpu // max(1, ranks * max(1, workers)))
    )
    env["OMP_NUM_THREADS"] = threads
    try:  # widen affinity (child inherits it); harmless if already full
        os.sched_setaffinity(0, set(range(ncpu)))
    except (AttributeError, OSError):
        pass
    return env


def _mock_label(atoms, dft):
    """Label with the cached foundation calculator instead of DFT.

    Smoke-tests the full loop (labelling, spot-check, E0s) on machines without CP2K.
    Plumbing only, never for science — the returned physics is the foundation model's.
    """
    import numpy as np

    from .direct import _foundation_calc

    calc = _foundation_calc(
        getattr(dft, "mock_model", "mace-mp-0"), getattr(dft, "mock_device", "cpu")
    )
    a = atoms.copy()
    a.calc = calc
    return {
        "energy_ev": float(a.get_potential_energy()),
        "forces": np.asarray(a.get_forces(), dtype=float).tolist(),
        "stress": None,
    }


def _try_parse_existing(run_dir: Path):
    """Parse a finished single point if one exists in run_dir (resume-reuse).

    Checks dft.out and mainLog.out: some ssmp builds route the real log to
    mainLog.out (dft.out gets only the banner), while psmp builds write dft.out.
    """
    for name in ("dft.out", "mainLog.out"):
        p = Path(run_dir) / name
        if p.exists():
            try:
                return cp2k_io.parse_singlepoint_output(p)
            except ValueError:
                continue
    return None


def label_one(atoms, dft, run_dir: str | Path, workers: int = 1):
    """Run one DFT single point and return the parsed result (does not mutate atoms).

    Used both by the stage loop and by the Phase-1 unit round-trip check. With
    dft.backend="mock_foundation" the single point is a foundation-model call instead.
    `workers` = how many frames share the node concurrently (sizes the OMP threads).
    A finished point already in run_dir is reused, never recomputed.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    if getattr(dft, "backend", "cp2k") == "mock_foundation":
        return _mock_label(atoms, dft)
    parsed = _try_parse_existing(run_dir)
    if parsed is not None:
        return parsed
    inp = cp2k_io.write_singlepoint_input(
        atoms, dft, project="dft", out_path=run_dir / "dft.inp"
    )
    out = run_dir / "dft.out"
    cmd = _cp2k_command(inp, out, dft)
    with open(out, "w") as fh:
        subprocess.run(
            cmd,
            cwd=str(run_dir),
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=True,
            env=_cp2k_subprocess_env(dft, workers),
        )
    parsed = _try_parse_existing(run_dir)
    if parsed is None:
        raise ValueError(f"{run_dir}: no parsable CP2K output (dft.out/mainLog.out)")
    return parsed


def attach_labels(
    atoms, parsed, energy_key: str, forces_key: str, stress_key: str
) -> None:
    import numpy as np

    atoms.info[energy_key] = float(parsed["energy_ev"])
    atoms.arrays[forces_key] = np.asarray(parsed["forces"], dtype=float)
    if parsed["stress"] is not None:
        atoms.info[stress_key] = np.asarray(parsed["stress"], dtype=float)


def label_frames(
    frames, cfg, workdir: str | Path, manifest=None, pass_index: int | None = None
) -> int:
    """Label every candidate frame and append to the dataset. Returns frames newly written.

    `manifest` (optional) records each frame hash as it completes so the stage resumes.
    """
    workdir = Path(workdir)
    dataset_path = workdir / "dataset.xyz"
    dft_root = workdir / "dft"

    done = set()
    rec = None
    if manifest is not None:
        rec = manifest.pass_record(pass_index)
        done = set(rec["done_dft"])

    seen_hashes = dataset.existing_hashes(dataset_path)
    pending = []
    for atoms in frames:
        h = dataset.structure_hash(atoms)
        if h in done or h in seen_hashes:
            continue
        pending.append((h, atoms))

    def _finish(h, atoms, parsed):
        nonlocal written
        attach_labels(
            atoms,
            parsed,
            cfg.train.energy_key,
            cfg.train.forces_key,
            cfg.train.stress_key,
        )
        written += dataset.append_frames(
            dataset_path, [atoms], dedup_against=seen_hashes
        )
        if rec is not None:
            rec["done_dft"].append(h)
            rec["n_labelled_total"] = len(dataset.existing_hashes(dataset_path))
            manifest.save()

    written = 0
    workers = int(getattr(cfg.dft, "label_workers", 1) or 1)
    workers = min(workers, max(1, len(pending)))
    if workers > 1 and getattr(cfg.dft, "backend", "cp2k") != "mock_foundation":
        # CP2K runs are independent subprocesses in per-hash dirs; threads just launch
        # and wait on them. Dataset appends + manifest saves stay in THIS thread
        # (as_completed loop), so resume bookkeeping is never racy. Completion order
        # is nondeterministic but frames are keyed by hash — order carries no meaning.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"  labelling {len(pending)} frames with {workers} concurrent CP2K runs")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(label_one, atoms, cfg.dft, dft_root / h, workers): (
                    h,
                    atoms,
                )
                for h, atoms in pending
            }
            for fut in as_completed(futs):
                h, atoms = futs[fut]
                _finish(h, atoms, fut.result())
    else:
        for h, atoms in pending:
            _finish(h, atoms, label_one(atoms, cfg.dft, dft_root / h))
    return written
