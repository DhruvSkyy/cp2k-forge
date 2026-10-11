#!/usr/bin/env python3
"""Top-level resumable driver for the domain-specific MACE pipeline.

Runs the loop  generate -> subsample -> label -> train  for up to `loop.max_passes`
passes, stopping early when the held-out force RMSE plateaus (and, if a density probe
succeeds, the target property stops moving). Every stage transition is persisted to
`manifest.json`, so the run resumes from where it stopped after any interruption.

Usage:
    cp2k-forge --config configs/water.yaml
    python -m cp2k_forge --config configs/water.yaml
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from cp2k_forge import (
    generate,
    label,
    report as report_mod,
    subsample,
    train,
    validate,
)
from cp2k_forge.config import Config
from cp2k_forge.manifest import Manifest
from cp2k_forge.seed import density_gcc as _density_gcc, load_seed as _load_seed
from cp2k_forge.timing import format_timings, stage_timer


def _density_probe(cfg, model_path: str, device: str | None = None) -> float | None:
    """Best-effort NPT density probe (the convergence/promotion observable).

    Runs validate.density_probe_steps under the showcase barostat ("mtk" = canonical NPT;
    2000 steps is only a smoke value — a campaign needs ~100 ps for a ~0.006 g/cc SEM).
    Returns g/cm^3, or None if the probe could not run; the loop falls back to
    force-RMSE-only convergence when this is None.
    """
    try:
        from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
        from mace.calculators import MACECalculator

        from cp2k_forge.engines import make_npt_dyn

        v = cfg.validate_cfg
        seed = _load_seed(cfg)
        if device is None:
            device = cfg.train.device
        # float32: a sampling probe; density is a trajectory average, not a
        # force score (float64 measured ~4x the wall on A100 for zero gain here).
        seed.calc = MACECalculator(
            model_paths=model_path, device=device, default_dtype="float32"
        )
        t_probe = v.density_probe_temperature_k
        if t_probe is None:
            temps = cfg.showcase.temperatures_k
            t_probe = temps[len(temps) // 2]
        MaxwellBoltzmannDistribution(seed, temperature_K=t_probe)
        dyn = make_npt_dyn(
            seed,
            cfg.showcase.timestep_fs,
            t_probe,
            cfg.showcase.pressure_bar,
            cfg.showcase.barostat,
            tdamp_fs=cfg.explore.tdamp_fs,
            pdamp_fs=cfg.explore.pdamp_fs,
        )
        densities = []

        def sample():
            rho = _density_gcc(seed)
            # NaN/blow-up guard: a diverging model turns the barostat into NaN math
            # that still "runs" at full cost (live: 2 h of exploded MTK dynamics).
            if not (0.05 < rho < 5.0) or rho != rho:
                raise RuntimeError(
                    f"density probe diverged (rho={rho}) - model unstable"
                )
            densities.append(rho)

        steps = int(v.density_probe_steps)
        dyn.attach(sample, interval=max(1, min(200, steps // 10)))
        dyn.run(steps)
        if not densities:
            return None
        keep = densities[len(densities) // 2 :]  # drop the first half as equilibration
        return float(sum(keep) / len(keep))
    except Exception as exc:  # probe is optional — never let it kill the loop
        print(f"  [density probe skipped: {exc}]")
        return None


def _decorr_headline(records: list) -> str:
    """One-line sampling summary for stdout/SLURM logs."""
    total = sum(r.get("n_uncorrelated", 0) for r in records)
    short = sum(1 for r in records if r.get("shortfall"))
    unreliable = sum(1 for r in records if not r.get("tau_reliable", True))
    aborts = sum(1 for r in records if r.get("clamp_aborted"))
    taus = [r["tau_fs"] for r in records if r.get("tau_fs") is not None]
    tau_part = f", mean tau {sum(taus) / len(taus):.0f} fs" if taus else ""
    return (
        f"{total} uncorrelated candidates across {len(records)} cells{tau_part}"
        + (f", {short} cells SHORT of target" if short else "")
        + (f", {unreliable} cells with unreliable tau" if unreliable else "")
        + (f", {aborts} clamp aborts" if aborts else "")
    )


def _write_reports(cfg, manifest, workdir: Path, pass_dir: Path, report: dict, p: int):
    """Write the per-pass scorecard.md + refresh the campaign REPORT.md (best-effort)."""
    try:
        prev_rec = None
        for rec in manifest.state["passes"]:
            if rec["index"] == p - 1:
                prev_rec = rec
        out = report_mod.write_pass_scorecard(
            report,
            manifest.pass_record(p),
            prev_rec,
            cfg,
            p,
            pass_dir / "validate" / "scorecard.md",
        )
        print(f"  scorecard: {out}")
    except Exception as exc:
        print(f"  [scorecard.md skipped: {exc}]")


def _run_pass(cfg, manifest, workdir: Path, seed, stop_after=None):
    p = manifest.current_pass
    pass_dir = workdir / f"pass{p}"
    timings: dict = {}
    print(f"\n=== pass {p} (stage: {manifest.stage}) ===")

    # GENERATE -------------------------------------------------------------
    if manifest.stage == "generate":
        with stage_timer("generate", timings):
            explorer_path = manifest.promoted_model_path(cfg.loop)
            rec = manifest.pass_record()
            rec["explorer"] = explorer_path or "foundation"
            if cfg.loop.promote_min_force_pct and manifest.previous_model_path():
                verdict = "promoted" if explorer_path else "NOT promoted (gate failed)"
                print(f"  explorer: {rec['explorer']} — previous model {verdict}")
            engine = generate.build_explorer(cfg, explorer_path)
            frames, records = generate.generate_frames(cfg, engine, seed, p, pass_dir)
            rec["clamp_aborts"] = sum(1 for r in records if r.get("clamp_aborted"))
            manifest.save()
            print(f"  generated {len(frames)} frames: {_decorr_headline(records)}")
            manifest.set_stage("subsample")
        manifest.record_timings(timings)
        if stop_after == "generate":
            return

    # SUBSAMPLE ------------------------------------------------------------
    if manifest.stage == "subsample":
        from ase.io import read, write

        with stage_timer("subsample", timings):
            frames = read(str(pass_dir / "traj.xyz"), index=":")
            frames = frames if isinstance(frames, list) else [frames]
            method = cfg.subsample.method if cfg.subsample.enabled else "none"
            n_pick = (
                cfg.subsample.n_first_pass
                if (p == 1 and cfg.subsample.n_first_pass)
                else cfg.subsample.n_per_pass
            )
            dataset_frames = None
            if cfg.subsample.dataset_aware:
                from cp2k_forge import dataset

                dataset_frames = dataset.read_frames(workdir / "dataset.xyz")
            picked = subsample.subsample(
                frames,
                n_pick,
                method,
                foundation_model=cfg.generator.model,
                device=cfg.generator.device,
                dataset_frames=dataset_frames,
                rng_seed=cfg.subsample.selection_seed + p,
            )
            write(str(pass_dir / "candidates.xyz"), picked, format="extxyz")
            rec = manifest.pass_record()
            rec["subsample_method"] = method
            rec["dataset_aware"] = bool(dataset_frames)
            print(
                f"  selected {len(picked)}/{n_pick} candidates (method={method}, "
                f"dataset_aware={bool(dataset_frames)})"
            )
            manifest.set_stage("label")
        manifest.record_timings(timings)
        if stop_after == "subsample":
            return

    # LABEL ----------------------------------------------------------------
    if manifest.stage == "label":
        from ase.io import read

        with stage_timer("label", timings):
            cand = read(str(pass_dir / "candidates.xyz"), index=":")
            cand = cand if isinstance(cand, list) else [cand]
            written = label.label_frames(
                cand, cfg, workdir, manifest=manifest, pass_index=p
            )
            print(f"  labelled {written} new frames with DFT")
            if cfg.train.e0s_mode == "isolated":
                # Runs on the CP2K-capable node; the GPU train job only reads the JSON.
                from cp2k_forge import e0s

                e0s.ensure_e0s(cfg, workdir)
            # v4 incremental validation set: grow the ruler while CP2K is available.
            with stage_timer("testset_increment", timings):
                validate.extend_test_set(cfg, workdir, p)
            manifest.set_stage("train")
        manifest.record_timings(timings)
        if stop_after == "label":
            return

    # TRAIN ----------------------------------------------------------------
    if manifest.stage == "train":
        from cp2k_forge import dataset

        density = None
        model_path = None
        with stage_timer("train", timings):
            model_path, rmse = train.train_from_scratch(cfg, workdir, p)
            n_total = len(dataset.existing_hashes(workdir / "dataset.xyz"))
            manifest.record_train_result(model_path, n_total, rmse)
            manifest.pass_record()["train_arch"] = train._arch_sig(cfg)
            manifest.save()
            print(
                f"  trained {model_path}  (held-out force RMSE: {rmse:.1f} meV/A, "
                f"{n_total} frames total)"
            )
        manifest.record_timings(timings)

        # VALIDATE (inline, not a manifest stage -> no state-machine migration).
        # The flash density probe runs CONCURRENTLY in a sibling process (spare GPU
        # when present) while the NVT observables run here: validation stays complete
        # but drops from ~33 to ~18 min (probe and observables fully overlap).
        if cfg.validate_cfg.enabled and model_path is not None:
            with stage_timer("validate", timings):
                import multiprocessing as _mp
                from concurrent.futures import ProcessPoolExecutor as _Pool

                probe_dev = None
                try:
                    import torch as _torch

                    if _torch.cuda.device_count() > 1:
                        probe_dev = "cuda:1"
                except Exception:
                    pass
                _ctx = _mp.get_context("spawn")
                _pool = _Pool(1, mp_context=_ctx)
                density_fut = _pool.submit(_density_probe, cfg, model_path, probe_dev)

                prev_obs = (
                    workdir / f"pass{p - 1}" / "validate" / "observables.npz"
                    if p > 1
                    else None
                )
                # Guarded: the model is already trained + RMSE recorded. If validation
                # blows up (unstable sparse model → NaN MD, empty RDF, etc.) DON'T
                # crash the pass — a raise here leaves stage=train and the watcher
                # retrains forever. Degrade to an empty report; convergence just won't
                # fire this pass and the loop advances to gather more data.
                try:
                    report = validate.validate_model(
                        cfg,
                        model_path,
                        pass_dir / "validate",
                        density_gcc=None,
                        model_level="current",
                        prev_observables=prev_obs,
                        pass_index=p,
                    )
                    prev = manifest.previous_model_path()
                    if cfg.validate_cfg.validate_previous_model and prev:
                        report["previous_model"] = validate.validate_model(
                            cfg,
                            prev,
                            pass_dir / "validate_prev",
                            model_level="previous",
                            store_observables=False,
                        )
                except Exception as _e:  # noqa: BLE001 — never crash-loop the trainer
                    print(
                        f"  WARNING: validation failed ({_e}); pass advances without "
                        "scores (model + RMSE still saved)"
                    )
                    report = {
                        "scores": {},
                        "convergence": {},
                        "raw": {},
                        "notes": f"validation error: {_e}",
                    }
                try:
                    density = density_fut.result()
                finally:
                    _pool.shutdown()
                if density is not None:
                    manifest.record_density(density)
                    report.setdefault("raw", {})["density_gcc"] = round(density, 4)
                    print(f"  density probe: {density:.4f} g/cm^3")
                manifest.record_validation(report)
            manifest.record_timings(timings)
            report_mod.print_scorecard(report, p)
            _write_reports(cfg, manifest, workdir, pass_dir, report, p)

        print(f"  timings: {format_timings(timings)}")

    # CONVERGENCE ----------------------------------------------------------
    verdict = manifest.check_convergence(cfg.loop)
    if verdict == "plateau":
        manifest.mark_converged()
        print("  >>> converged")
    elif verdict == "diminishing_returns":
        manifest.mark_stopped("diminishing_returns")
        print(
            "  >>> stopped: force RMSE improving <"
            f"{cfg.loop.min_rel_improvement_force:.0%}/pass - extra labels are not "
            "buying accuracy. NOT converged (quality gates were not met)."
        )
    else:
        manifest.advance_pass()


def _apply_overrides(cfg: Config, sets: list[str]) -> None:
    """Apply repeatable --set section.key=value overrides onto a loaded config.

    This is what makes ablation arms "otherwise identical by construction": one config
    file, and each arm differs only in its command line, e.g.
        --set subsample.method=random --workdir .../runs/water64_tmd_random
    Values parse as YAML (so ints/floats/bools/lists/null work); cfg.validate() reruns
    after all overrides so an inconsistent combination still fails fast.
    """
    import dataclasses

    import yaml

    alias = {"validate": "validate_cfg"}  # yaml section name -> Config attribute
    for spec in sets or []:
        key, sep, val = spec.partition("=")
        if not sep:
            raise ValueError(f"--set {spec!r}: expected section.key=value")
        parts = [p.strip() for p in key.split(".")]
        parts[0] = alias.get(parts[0], parts[0])
        obj = cfg
        for attr in parts[:-1]:
            obj = getattr(obj, attr)
        leaf = parts[-1]
        if not (
            dataclasses.is_dataclass(obj)
            and any(f.name == leaf for f in dataclasses.fields(obj))
        ) and not hasattr(obj, leaf):
            raise ValueError(f"--set {spec!r}: unknown config key {key!r}")
        setattr(obj, leaf, yaml.safe_load(val))
        print(f"  override: {key} = {val}")
    if sets:
        cfg.validate()


def _preflight(cfg, config_path, stop_after, workdir: Path, skip: bool) -> None:
    """Run the environment doctor before spending compute; abort on any FAIL.

    Runs on the FINAL config (after --set overrides) and the resolved workdir, so what is
    checked is exactly what the run will use. CP2K is required only for invocations that
    will actually reach the label stage (the full loop, or --stop-after label), so a GPU
    train-only node is not failed for lacking CP2K. Skipped with --no-check or
    CP2K_FORGE_SKIP_CHECK=1.
    """
    if skip or os.environ.get("CP2K_FORGE_SKIP_CHECK"):
        return
    from cp2k_forge import doctor

    require_cp2k = stop_after in (None, "label")
    checks = doctor.run_checks(
        config_path, require_cp2k=require_cp2k, workdir=str(workdir), cfg=cfg
    )
    if not doctor.print_report(checks):
        raise SystemExit(
            "preflight failed: fix the FAIL rows above (see the '->' hints), or re-run "
            "with --no-check to bypass. `cp2k-forge --check` re-runs these checks."
        )


def run(
    config_path: str,
    stop_after: str | None = None,
    workdir_override: str | None = None,
    set_overrides: list[str] | None = None,
    skip_check: bool = False,
) -> None:
    # Load + apply --set overrides + resolve the workdir BEFORE the preflight, so the doctor
    # checks the final config (backend, device, workdir) rather than the on-disk defaults.
    cfg = Config.from_yaml(config_path)
    _apply_overrides(cfg, set_overrides or [])
    # Per-machine output path without editing the shared config (env CP2K_FORGE_WORKDIR
    # or --workdir); on a cluster point this at scratch/large storage, not a home quota.
    override = workdir_override or os.environ.get("CP2K_FORGE_WORKDIR")
    workdir = Path(override) if override else Path(cfg.workdir)
    if not workdir.is_absolute():
        workdir = Path.cwd() / workdir

    _preflight(cfg, config_path, stop_after, workdir, skip_check)
    workdir.mkdir(parents=True, exist_ok=True)

    manifest = Manifest.load_or_init(workdir / "manifest.json", config_path)
    seed = _load_seed(cfg, verbose=True)

    import time as _time

    loop_t0 = _time.monotonic()
    while (
        manifest.current_pass <= cfg.loop.max_passes
        and not manifest.converged
        and not manifest.stopped
    ):
        max_wall = getattr(cfg.loop, "max_wall_hours", None)
        if max_wall and (_time.monotonic() - loop_t0) / 3600.0 > float(max_wall):
            manifest.mark_stopped(f"max_wall_hours ({max_wall} h) reached")
            print(
                f"  >>> stopped: campaign wall-clock bound {max_wall} h reached. "
                "NOT converged."
            )
            break
        _run_pass(cfg, manifest, workdir, seed, stop_after=stop_after)
        if stop_after is not None:
            # One stage-bounded invocation (e.g. label on CPU, then train on GPU). The
            # manifest persists progress so a follow-up run resumes from here.
            print(
                f"\nStopped after '{stop_after}' (pass {manifest.current_pass}, "
                f"stage now: {manifest.stage})."
            )
            return

    if manifest.converged:
        print("\nDone.")
    elif manifest.stopped:
        print(f"\nStopped early ({manifest.stopped}) - NOT converged.")
    else:
        print(f"\nStopped after {cfg.loop.max_passes} passes (not yet converged).")
    trained = [r for r in manifest.state["passes"] if r.get("model_path")]
    print(f"Final model: {trained[-1]['model_path'] if trained else None}")


def main():
    from . import __version__

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", action="version", version=f"cp2k-forge {__version__}")
    ap.add_argument("--config", default=None, help="path to the campaign YAML")
    ap.add_argument(
        "--check",
        action="store_true",
        help="run the environment preflight (dependencies, config, CP2K, "
        "device, workdir) and exit; works even before the deps are installed",
    )
    ap.add_argument(
        "--no-check",
        action="store_true",
        help="skip the automatic start-up preflight (also: CP2K_FORGE_SKIP_CHECK=1)",
    )
    ap.add_argument(
        "--stop-after",
        choices=["generate", "subsample", "label", "train"],
        default=None,
        help="run only up to this stage then exit, persisting the "
        "manifest (splits the CPU label stage from the GPU train stage across nodes)",
    )
    ap.add_argument(
        "--workdir",
        default=None,
        help="override the config workdir (scratch "
        "path); also settable via CP2K_FORGE_WORKDIR",
    )
    ap.add_argument(
        "--set",
        dest="set_overrides",
        action="append",
        default=[],
        metavar="SECTION.KEY=VALUE",
        help="override one config value (repeatable); e.g. "
        "--set subsample.method=random for an ablation arm",
    )
    args = ap.parse_args()

    if args.check:
        # A manual --check reports full CP2K reachability (require_cp2k=True) regardless of
        # --stop-after; the automatic start-up preflight instead scopes it to the stage.
        from cp2k_forge import doctor

        checks = doctor.run_checks(args.config, require_cp2k=True, workdir=args.workdir)
        raise SystemExit(0 if doctor.print_report(checks) else 1)

    if not args.config:
        ap.error(
            "--config is required (or use --check for an environment-only preflight)"
        )
    run(
        args.config,
        stop_after=args.stop_after,
        workdir_override=args.workdir,
        set_overrides=args.set_overrides,
        skip_check=args.no_check,
    )


if __name__ == "__main__":
    main()
