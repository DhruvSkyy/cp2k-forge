"""Train a compact MACE on a labelled dataset.

The pipeline's default is train-FROM-SCRATCH: the model is initialised randomly and learns
only from the DFT labels, so its physics is purely the labelling functional. The model is
deliberately small (few channels, short cutoff) because the headline speed claim depends on
a compact, high-throughput model.

Two other training modes are supported for the comparison study (scripts/compare_training.py):
  fine-tune     initialise from the MACE-MP-0 foundation, continue-train on the DFT labels
                (naive fine-tuning, no multihead replay) -> pass `foundation_model`
  distillation  train from scratch on labels from the FOUNDATION model instead of DFT
                (foundation_relabel builds that dataset) -> tests whether DFT relabelling
                buys anything over just compressing the foundation

Training shells out to the mace-torch CLI (`mace_run_train`); evaluation loads the
result through ASE to report held-out force RMSE.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import dataset


def _write_splits(cfg, dataset_path, out_dir: Path):
    from ase.io import write

    train_frames, valid_frames = dataset.split_train_valid(
        Path(dataset_path), cfg.train.valid_fraction, seed=cfg.train.seed
    )
    if not train_frames or not valid_frames:
        raise ValueError("not enough labelled frames to form a train/valid split")
    train_path = out_dir / "train.xyz"
    valid_path = out_dir / "valid.xyz"
    write(str(train_path), train_frames, format="extxyz")
    write(str(valid_path), valid_frames, format="extxyz")
    return train_path, valid_path, valid_frames, len(train_frames)


def _e0s_argument(e0s: dict | None) -> str:
    """Render the --E0s argument: fixed isolated-atom energies, or the 'average' fit.

    Fixed E0s keep the energy baseline invariant as the dataset grows across passes
    (--E0s=average re-fits it every pass, and is degenerate for a fixed-composition box).
    """
    if not e0s:
        return "--E0s=average"  # least-squares atomic energies from the dataset
    pairs = ", ".join(f"{int(z)}: {float(e):.10f}" for z, e in sorted(e0s.items()))
    return f"--E0s={{{pairs}}}"


def load_e0s(cfg, workdir: str | Path) -> dict | None:
    """Resolve the E0s dict for training, per cfg.train.e0s_mode.

    "average"  -> None (mace_run_train fits them)
    "isolated" -> workdir/e0s.json, produced by cp2k_forge.e0s.ensure_e0s during the label
                  stage (hard error if absent: the CP2K node did not run it)
    "file"     -> cfg.train.e0s_file (relative paths resolve from the config
                  file's directory)
    """
    import json

    mode = getattr(cfg.train, "e0s_mode", "average")
    if mode == "average":
        return None
    if mode == "isolated":
        path = Path(workdir) / "e0s.json"
        if not path.exists():
            raise RuntimeError(
                f"train.e0s_mode='isolated' but {path} is missing — the label stage "
                "computes it on the CP2K node (rerun with --stop-after label there)."
            )
    else:
        path = cfg.resolve_path(cfg.train.e0s_file)
        if not path.exists():
            raise RuntimeError(f"train.e0s_file {path} not found")
    data = json.loads(path.read_text())
    return {int(z): float(e) for z, e in data.items() if str(z).isdigit()}


def _trainer_argv(configured: str) -> list[str]:
    """Argv prefix that launches the MACE trainer.

    Prefer the configured console script. If it is not on PATH but mace-torch is
    importable, fall back to running the same entry point as a module with the current
    interpreter — the common case where a venv's packages are importable but its bin/ is
    not on PATH. cp2k_forge.doctor reports this as the `train:binary` check.
    """
    import importlib.util
    import shutil
    import sys

    if shutil.which(configured) or Path(configured).exists():
        return [configured]
    if importlib.util.find_spec("mace.cli.run_train") is not None:
        return [sys.executable, "-m", "mace.cli.run_train"]
    raise RuntimeError(
        f"MACE trainer '{configured}' not found on PATH and mace.cli.run_train is not "
        "importable. Install mace-torch and activate its environment, or set "
        "train.mace_run_train_bin to the full path of mace_run_train."
    )


def _train_command(
    cfg,
    name: str,
    train_file: Path,
    valid_file: Path,
    model_dir: Path,
    foundation_model: str | None = None,
    e0s: dict | None = None,
    pass_index: int | None = None,
    extra_args: list[str] | None = None,
    n_train: int | None = None,
):
    t = cfg.train
    # Clamp batch size to the training-set size. mace_run_train drops the last partial
    # batch, so batch_size > n_train yields ZERO batches -> empty loader ->
    # "torch.cat(): expected a non-empty list" crash (seed passes have <20 frames).
    # Prefer the in-memory count from _write_splits (race-proof); fall back to a
    # re-read only if not supplied. Keep >=2 batches where possible; floor 1.
    if n_train is None:
        n_train = sum(
            1
            for ln in Path(train_file).read_text().splitlines()
            if ln.strip().isdigit()
        )  # extxyz: bare-integer natoms line/frame
    batch_size = max(1, min(t.batch_size, max(1, n_train // 2)))
    cmd = [
        *_trainer_argv(t.mace_run_train_bin),
        f"--name={name}",
        f"--train_file={train_file}",
        f"--valid_file={valid_file}",
        f"--energy_key={t.energy_key}",
        f"--forces_key={t.forces_key}",
        f"--stress_key={t.stress_key}",
        "--model=MACE",
        f"--num_channels={t.num_channels}",
        f"--max_L={t.max_ell}",
        f"--r_max={t.r_max}",
        f"--num_interactions={t.num_interactions}",
        f"--batch_size={batch_size}",
        f"--max_num_epochs={t.max_num_epochs}",
        f"--seed={t.seed}",
        f"--device={t.device}",
        "--default_dtype=float64",
        _e0s_argument(e0s),
        "--energy_weight=1.0",
        "--forces_weight=100.0",
        f"--model_dir={model_dir}",
        f"--log_dir={model_dir}/logs",
        f"--checkpoints_dir={model_dir}/checkpoints",
        f"--results_dir={model_dir}/results",
    ]
    # Train on the virial/stress only when asked (fixes the 1-bar density for the TMD).
    sw = getattr(t, "stress_weight", 0.0)
    if sw and sw > 0:
        cmd.append(f"--stress_weight={sw}")
    # ZBL pair repulsion: short-range physics a tiny dataset cannot teach. Applied to all
    # passes when pair_repulsion_until_pass == 0, else only to passes <= that (early-pass
    # scaffolding, dropped once the dataset carries enough close contacts).
    # Bare flag: mace-torch declares --pair_repulsion as store_true, so the =True form
    # is rejected by argparse ("ignored explicit argument").
    pr = getattr(t, "pair_repulsion", False)
    until = getattr(t, "pair_repulsion_until_pass", 0)
    if pr and (not until or pass_index is None or pass_index <= until):
        cmd.append("--pair_repulsion")
    # Optimizer stability (see TrainConfig): EMA is the standard MACE stabilizer — without it
    # the force loss diverges and the run keeps only an early checkpoint. SWA is an optional
    # stage-two accuracy boost. --ema/--swa are store_true bare flags.
    if getattr(t, "lr", None):
        cmd.append(f"--lr={t.lr}")
    if getattr(t, "ema", True):
        cmd += ["--ema", f"--ema_decay={getattr(t, 'ema_decay', 0.99)}"]
    if getattr(t, "swa", False):
        start = getattr(t, "start_swa", None) or max(1, int(0.75 * t.max_num_epochs))
        cmd += [
            "--swa",
            f"--start_swa={start}",
            f"--swa_energy_weight={getattr(t, 'swa_energy_weight', 1000.0)}",
        ]
    if getattr(t, "patience", None):
        cmd.append(f"--patience={t.patience}")
    if getattr(t, "eval_interval", None):
        cmd.append(f"--eval_interval={t.eval_interval}")
    if getattr(t, "enable_cueq", False):
        try:
            import cuequivariance_torch  # noqa: F401

            cmd.append("--enable_cueq=True")
        except ImportError:
            print("  [enable_cueq requested but cueq not installed - training without]")
    extra_args = list(extra_args or [])
    if foundation_model:
        cmd.append(f"--foundation_model={foundation_model}")
        # Default to naive fine-tuning (no pretraining-replay, which needs the PT
        # dataset/network), unless the caller already set a --multiheads_finetuning flag
        # (e.g. the multihead-replay arm of the training-strategy comparison).
        if not any(a.startswith("--multiheads_finetuning") for a in extra_args):
            cmd.append("--multiheads_finetuning=False")
    # Caller-supplied flags (the comparison harness passes fine-tune-strategy flags here:
    # --lora/--lora_rank/--lora_alpha, --freeze, --multiheads_finetuning + --pt_train_file).
    cmd += extra_args
    return cmd


def train_model(
    cfg,
    name: str,
    model_dir: str | Path,
    dataset_path: str | Path,
    foundation_model: str | None = None,
    e0s: dict | None = None,
    pass_index: int | None = None,
    extra_args: list[str] | None = None,
):
    """Train one compact MACE on `dataset_path`. Returns (model_path, force_rmse_mev_ang).

    foundation_model=None -> from scratch; a name/path -> fine-tune from that foundation.
    extra_args -> extra mace_run_train flags (the strategy-comparison harness).
    """
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    train_file, valid_file, valid_frames, n_train = _write_splits(
        cfg, dataset_path, model_dir
    )
    cmd = _train_command(
        cfg,
        name,
        train_file,
        valid_file,
        model_dir,
        foundation_model,
        e0s=e0s,
        pass_index=pass_index,
        extra_args=extra_args,
        n_train=n_train,
    )
    subprocess.run(cmd, cwd=str(model_dir), check=True)

    # With --swa, mace 0.3.16 writes the stage-one best to "<name>.model" and the
    # stage-two (SWA, energy-reweighted) model to "<name>_stagetwo.model". Stage two
    # is the one the campaign wants (energy/density balance) — prefer it when present.
    model_path = model_dir / f"{name}_stagetwo.model"
    if not model_path.exists():
        model_path = model_dir / f"{name}.model"
    if not model_path.exists():
        # mace-torch names the inference model "<name>.model"; fall back to a glob.
        candidates = sorted(model_dir.glob(f"{name}*.model"))
        if not candidates:
            raise FileNotFoundError(f"no trained model produced in {model_dir}")
        model_path = candidates[0]

    rmse = evaluate_force_rmse(
        str(model_path), valid_frames, cfg.train.device, cfg.train.forces_key
    )
    export_symmetrix(cfg, model_path)
    return str(model_path), rmse


def export_symmetrix(cfg, model_path: str | Path) -> str | None:
    """Export the trained model to the JSON the in-CP2K MACE backend consumes.

    Only runs when generator.engine selects the backend ('cp2k-backend') AND the
    converter is available via SYMMETRIX_EXTRACT_SRC (the exporter shipped with the
    MACE backend contribution). Writes <stem>_symmetrix.json next to the model.
    Best-effort: an export failure never kills the train stage — the explorer then
    falls back to ASE for one pass and the failure is visible in the log. The default
    ASE path never reaches here."""
    import json

    if getattr(cfg.generator, "engine", "ase") not in ("cp2k-backend", "symmetrix"):
        return None
    src = os.environ.get("SYMMETRIX_EXTRACT_SRC")
    if not src or not Path(src).exists():
        print(
            "  NOTE: SYMMETRIX_EXTRACT_SRC not set to a valid exporter; skipping "
            "backend JSON export (needs the symmetrix model-to-JSON converter)"
        )
        return None
    model_path = Path(model_path)
    out = model_path.with_name(model_path.stem + "_symmetrix.json")
    try:
        import importlib.util

        import torch

        spec = importlib.util.spec_from_file_location("_symmetrix_extract", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        elements = list(getattr(cfg.system, "elements", ["H", "O"]))
        # GPU-trained checkpoints embed CUDA-compiled TorchScript submodules that
        # fail under the exporter's map_location="cpu" load. Loading on the native
        # device and then moving the module tree to CPU extracts cleanly (verified
        # against a live pass-1 model; requires a GPU node).
        orig_load = torch.load
        if torch.cuda.is_available():

            def _load_native(*a, **k):
                m = orig_load(*a, **{**k, "map_location": "cuda"})
                return m.cpu() if hasattr(m, "cpu") else m

            torch.load = _load_native
        try:
            data = mod.extract_mace_data(str(model_path), elements, None)
        finally:
            torch.load = orig_load
        with open(out, "w") as fh:
            json.dump(data, fh)
        print(f"  exported symmetrix JSON: {out} (has_zbl={data.get('has_zbl')})")
        return str(out)
    except Exception as exc:
        print(f"  WARNING: symmetrix export failed ({exc}); explorer will use ASE")
        return None


def train_from_scratch(cfg, workdir: str | Path, pass_index: int):
    """Pipeline default: train one compact MACE on the accumulated DFT dataset.xyz.

    v4 (train.warm_start): passes >= 2 continue from the previous pass's model
    ("continually trained" — Schran's protocol). Provenance is unchanged: only our
    DFT labels ever enter the loss; the init comes from a model with the same
    provenance. Pass 1 (or a missing previous model) trains from scratch.
    """
    workdir = Path(workdir)
    model_dir = workdir / f"pass{pass_index}" / "model"
    name = f"{cfg.system.name}_pass{pass_index}"
    init_model = None
    extra = None
    if getattr(cfg.train, "warm_start", False) and pass_index > 1:
        prev = (
            workdir
            / f"pass{pass_index - 1}"
            / "model"
            / f"{cfg.system.name}_pass{pass_index - 1}_stagetwo.model"
        )
        if not prev.exists():
            prev = prev.with_name(f"{cfg.system.name}_pass{pass_index - 1}.model")
        # Architecture guard: warm-starting across an architecture change (e.g. the
        # r_max 6->5 revision) is invalid — fall back to one from-scratch pass; the
        # arch is recorded per pass by the driver, so subsequent passes warm again.
        prev_arch = _recorded_arch(workdir, pass_index - 1)
        arch_now = _arch_sig(cfg)
        if prev.exists() and prev_arch == arch_now:
            init_model = str(prev)
            # Plain weight continuation, NOT mace's multihead foundation-finetuning:
            # the default multiheads path builds an MP replay buffer (54 GB OOM live,
            # and it would train on MP data - a provenance violation for this method).
            extra = ["--multiheads_finetuning=False"]
            warm_lr = getattr(cfg.train, "warm_lr", None)
            if warm_lr:
                extra.append(f"--lr={warm_lr}")  # appended last -> overrides base --lr
            print(
                f"  warm start from {prev.name}"
                + (f" (lr={warm_lr})" if warm_lr else "")
            )
        else:
            why = (
                "previous model missing"
                if not prev.exists()
                else f"architecture changed ({prev_arch} -> {arch_now})"
            )
            print(f"  warm start unavailable ({why}) - training from scratch")
    if init_model is None and getattr(cfg.train, "cold_epochs", None):
        extra = (extra or []) + [
            f"--max_num_epochs={cfg.train.cold_epochs}",
            f"--start_swa={max(1, int(0.75 * cfg.train.cold_epochs))}",
        ]
        print(f"  from-scratch budget: {cfg.train.cold_epochs} epochs")
    return train_model(
        cfg,
        name,
        model_dir,
        workdir / "dataset.xyz",
        foundation_model=init_model,
        e0s=load_e0s(cfg, workdir),
        pass_index=pass_index,
        extra_args=extra,
    )


def _arch_sig(cfg) -> str:
    t = cfg.train
    return f"ch{t.num_channels}_L{t.max_ell}_r{t.r_max}_int{t.num_interactions}"


def _recorded_arch(workdir: Path, pass_index: int) -> str | None:
    import json

    try:
        m = json.loads((Path(workdir) / "manifest.json").read_text())
        for rec in m.get("passes", []):
            if rec.get("index") == pass_index:
                return rec.get("train_arch")
    except Exception:
        pass
    return None


def foundation_relabel(
    frames, cfg, out_path: str | Path, model_path: str | None = None
):
    """Write `frames` with teacher-model energy/forces in the REF keys (distillation set).

    Same structures as the DFT set, but labelled by a TEACHER model instead of DFT, so a
    from-scratch train on the result is a distillation of that teacher. The teacher is the
    raw foundation (MACE-MP-0+D3) by default, or a fine-tuned `.model` file when
    `model_path` is given (the fine-tune-then-distill arm, where the teacher is the
    fine-tuned MACE that "replaces DFT" for bulk data generation, per Zhang 2026).
    """
    import numpy as np
    from ase.io import write

    if model_path:
        from mace.calculators import MACECalculator

        calc = MACECalculator(
            model_paths=str(model_path),
            device=cfg.train.device,
            default_dtype="float64",
        )
    else:
        from mace.calculators import mace_mp

        from .engines import _MP_ALIASES

        model = _MP_ALIASES.get(cfg.generator.model, cfg.generator.model)
        calc = mace_mp(
            model=model,
            dispersion=cfg.generator.dispersion,
            device=cfg.train.device,
            default_dtype="float64",
        )
    labelled = []
    for atoms in frames:
        a = atoms.copy()
        a.calc = calc
        energy = float(a.get_potential_energy())
        forces = np.asarray(a.get_forces(), dtype=float)
        b = atoms.copy()
        b.info[cfg.train.energy_key] = energy
        b.arrays[cfg.train.forces_key] = forces
        labelled.append(b)
    write(str(out_path), labelled, format="extxyz")
    return out_path


def evaluate_force_rmse(model_path: str, valid_frames, device: str, forces_key: str):
    """Force RMSE (meV/Angstrom) of the trained model on the held-out frames."""
    import numpy as np
    from mace.calculators import MACECalculator

    calc = MACECalculator(
        model_paths=model_path, device=device, default_dtype="float64"
    )
    sq_err, count = 0.0, 0
    for atoms in valid_frames:
        ref = np.asarray(atoms.arrays[forces_key], dtype=float)
        a = atoms.copy()
        a.calc = calc
        pred = a.get_forces()
        sq_err += float(np.sum((pred - ref) ** 2))
        count += ref.size
    if count == 0:
        return None
    rmse_ev_ang = (sq_err / count) ** 0.5
    return rmse_ev_ang * 1000.0  # meV/Angstrom
