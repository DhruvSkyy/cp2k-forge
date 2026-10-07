"""Preflight environment checks — fail loud BEFORE a run spends compute.

`run_checks` inspects everything a campaign needs (Python dependencies, the config and seed,
device availability, the CP2K binary and its data files, a writable output directory) and
returns a list of results, each PASS / WARN / FAIL / SKIP with an actionable fix. Dependency
probing uses importlib.util.find_spec, so `cp2k-forge --check` is useful even before the
requirements are installed. The driver runs the same checks automatically at start-up and
aborts on any FAIL (skippable with --no-check); run them by hand with:

    cp2k-forge --check                       # environment only
    cp2k-forge --check --config configs/water.yaml   # + config/seed/CP2K for that run
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import cp2k_env
from .cp2k_env import CP2K_DATA_FILES

# (import name, pip/display name, required?) — matplotlib is optional (plots only).
_DEPENDENCIES = [
    ("numpy", "numpy", True),
    ("yaml", "pyyaml", True),
    ("ase", "ase", True),
    ("mace", "mace-torch", True),
    ("torch", "torch", True),
    ("sklearn", "scikit-learn", True),
    ("matplotlib", "matplotlib", False),
]


@dataclass
class Check:
    name: str
    status: str  # "PASS" | "WARN" | "FAIL" | "SKIP"
    detail: str = ""
    fix: str = ""


def _have(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _check_python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 9)
    return Check(
        "python",
        "PASS" if ok else "FAIL",
        f"{v.major}.{v.minor}.{v.micro}",
        "" if ok else "Python >= 3.9 is required.",
    )


def _check_dependencies() -> list[Check]:
    checks = []
    for module, pip_name, required in _DEPENDENCIES:
        if _have(module):
            checks.append(Check(f"dep:{pip_name}", "PASS", "importable"))
        elif required:
            checks.append(
                Check(
                    f"dep:{pip_name}",
                    "FAIL",
                    "not importable",
                    f'install it: pip install -e ".[train,plot]" '
                    f"(or ./install.sh); missing '{pip_name}'",
                )
            )
        else:
            checks.append(
                Check(
                    f"dep:{pip_name}",
                    "WARN",
                    "not importable (optional)",
                    f"only needed for plots: pip install {pip_name}",
                )
            )
    return checks


def _check_cp2k_binary(cfg) -> Check:
    configured = cp2k_env.configured_binary(cfg.dft if cfg else None)
    resolved = cp2k_env.resolve_binary(cfg.dft if cfg else None)
    if not resolved:
        # Never silently substitute a variant (psmp vs ssmp changes the launch
        # command), but DO report what is reachable so the fix is one export away.
        on_path = cp2k_env.binaries_on_path()
        hint = (
            "point CP2K_BIN at your CP2K binary, e.g. "
            "export CP2K_BIN=/path/to/cp2k.psmp"
        )
        if on_path:
            hint += (
                f"; found on PATH: {', '.join(on_path)} (for an OMP-only .ssmp "
                "build also set CP2K_MPI_LAUNCHER=none)"
            )
        return Check("cp2k:binary", "FAIL", f"'{configured}' not found", hint)
    version = ""
    try:
        import subprocess

        out = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True, timeout=20
        )
        first = (out.stdout or out.stderr).strip().splitlines()
        version = first[0] if first else ""
    except Exception:
        version = "(found; --version not probed)"
    return Check("cp2k:binary", "PASS", f"{resolved} {version}".strip())


def _check_cp2k_data(cfg) -> Check:
    data_dir, source = cp2k_env.resolve_data_dir(cfg.dft if cfg else None)
    if data_dir is None:
        return Check(
            "cp2k:data",
            "FAIL",
            "CP2K_DATA_DIR unset and no data directory next to the CP2K binary",
            "export CP2K_DATA_DIR=/path/to/cp2k/data (must hold "
            + ", ".join(CP2K_DATA_FILES)
            + ")",
        )
    missing = [f for f in CP2K_DATA_FILES if not (data_dir / f).exists()]
    if missing:
        return Check(
            "cp2k:data",
            "FAIL",
            f"missing {missing} in {data_dir}",
            "export CP2K_DATA_DIR at a directory that has "
            + ", ".join(CP2K_DATA_FILES),
        )
    if source == "derived":
        # The label stage exports this derived path to the CP2K subprocess, so no
        # environment setup is needed for a standard install layout.
        return Check(
            "cp2k:data",
            "PASS",
            f"{data_dir} (derived from the binary location; "
            "export CP2K_DATA_DIR to override)",
        )
    return Check("cp2k:data", "PASS", str(data_dir))


def _check_config(config_path: str):
    """Return (Check, cfg_or_None). Import config lazily so --check works without deps."""
    from .config import Config

    try:
        cfg = Config.from_yaml(config_path)
        return Check("config", "PASS", f"{config_path} ({cfg.system.name})"), cfg
    except Exception as exc:  # noqa: BLE001 — surface any load/validate error verbatim
        return (
            Check("config", "FAIL", str(exc), "fix the config and re-run --check"),
            None,
        )


def _check_seed(cfg) -> Check:
    seed_path = cfg.resolve_path(cfg.system.seed_xyz)
    if seed_path.exists():
        return Check("seed", "PASS", str(seed_path))
    return Check(
        "seed",
        "FAIL",
        f"{seed_path} not found",
        "set system.seed_xyz to an existing structure (relative paths resolve "
        "from the config file's directory)",
    )


def _check_device(cfg) -> Check:
    wants_cuda = any(
        str(getattr(cfg, owner).device).lower().startswith("cuda")
        for owner in ("generator", "train")
    )
    if not wants_cuda:
        return Check("device", "PASS", "cpu")
    if not _have("torch"):
        return Check(
            "device",
            "WARN",
            "cuda requested but torch not importable yet",
            "install torch, or set generator.device/train.device to cpu",
        )
    try:
        import torch

        if torch.cuda.is_available():
            return Check("device", "PASS", f"cuda ({torch.cuda.get_device_name(0)})")
        return Check(
            "device",
            "FAIL",
            "cuda requested but torch.cuda.is_available() is False",
            "run on a GPU node, or set generator.device/train.device to cpu",
        )
    except Exception as exc:  # noqa: BLE001
        return Check("device", "WARN", f"cuda check failed: {exc}")


def _check_workdir(cfg, workdir: str | None) -> Check:
    target = workdir or os.environ.get("CP2K_FORGE_WORKDIR") or cfg.workdir
    p = Path(target)
    if not p.is_absolute():
        p = Path.cwd() / p
    # Probe writability WITHOUT creating the workdir: walk up to the nearest existing
    # ancestor and check it is a writable directory, so a plain --check never leaves a
    # stray tree behind (the run itself creates the workdir later).
    existing = p
    while not existing.exists():
        if existing.parent == existing:
            break
        existing = existing.parent
    if existing.is_dir() and os.access(existing, os.W_OK):
        return Check("workdir", "PASS", str(p))
    return Check(
        "workdir",
        "FAIL",
        f"{p}: nearest existing path {existing} is not writable",
        "set CP2K_FORGE_WORKDIR to a writable path (prefer scratch)",
    )


def _check_trainer(cfg) -> Check:
    """The MACE trainer must be launchable *before* any compute is spent.

    `mace-torch` being importable does not imply its `mace_run_train` console script is on
    PATH (a common venv/module-load mismatch). Without this check a campaign passes
    preflight, spends the whole generate+label stage — hours of DFT in a real run — and
    only then dies with FileNotFoundError at the train stage.
    """
    configured = getattr(cfg.train, "mace_run_train_bin", "mace_run_train")
    if shutil.which(configured) or Path(configured).exists():
        return Check("train:binary", "PASS", str(configured))
    # Importable as a module is a usable fallback: the train stage can run it with -m.
    if importlib.util.find_spec("mace.cli.run_train") is not None:
        return Check(
            "train:binary",
            "WARN",
            f"'{configured}' not on PATH; mace.cli.run_train is importable",
            "activate the venv holding the mace-torch console scripts, or set "
            "train.mace_run_train_bin to its full path",
        )
    return Check(
        "train:binary",
        "FAIL",
        f"'{configured}' not found",
        "install mace-torch and activate its environment, or set "
        "train.mace_run_train_bin to the full path of mace_run_train",
    )


def run_checks(
    config_path: str | None = None,
    require_cp2k: bool = True,
    workdir: str | None = None,
    cfg=None,
) -> list[Check]:
    """Collect all preflight checks. CP2K checks are skipped when the config uses the mock
    backend or require_cp2k is False (e.g. a GPU train-only invocation).

    Pass an already-built `cfg` (with --set overrides applied and workdir resolved) to check
    exactly what the run will use; otherwise a `config_path` is loaded here for a standalone
    check."""
    checks: list[Check] = [_check_python(), *_check_dependencies()]

    if cfg is not None:
        checks.append(
            Check(
                "config", "PASS", f"{config_path or '(in-memory)'} ({cfg.system.name})"
            )
        )
    elif config_path:
        cfg_check, cfg = _check_config(config_path)
        checks.append(cfg_check)

    if cfg is not None:
        checks.append(_check_seed(cfg))
        checks.append(_check_device(cfg))
        checks.append(_check_workdir(cfg, workdir))
        checks.append(_check_trainer(cfg))
        mock = getattr(cfg.dft, "backend", "cp2k") == "mock_foundation"
        if mock:
            checks.append(
                Check("cp2k", "SKIP", "dft.backend=mock_foundation (no CP2K needed)")
            )
        elif require_cp2k:
            checks.append(_check_cp2k_binary(cfg))
            checks.append(_check_cp2k_data(cfg))
        else:
            checks.append(Check("cp2k", "SKIP", "not needed for this invocation"))
    elif config_path is None and require_cp2k:
        # Environment-only check (no config): still report CP2K reachability best-effort.
        checks.append(_check_cp2k_binary(None))
        checks.append(_check_cp2k_data(None))

    return checks


def print_report(checks: list[Check]) -> bool:
    """Print the checks as a table. Returns True if there are no FAILs."""
    symbol = {"PASS": "ok  ", "WARN": "warn", "FAIL": "FAIL", "SKIP": "skip"}
    width = max((len(c.name) for c in checks), default=4)
    print("\ncp2k-forge preflight")
    print("-" * (width + 8))
    ok = True
    for c in checks:
        print(f"  [{symbol.get(c.status, c.status)}] {c.name:<{width}}  {c.detail}")
        if c.fix and c.status in ("FAIL", "WARN"):
            print(f"        -> {c.fix}")
        if c.status == "FAIL":
            ok = False
    fails = sum(1 for c in checks if c.status == "FAIL")
    warns = sum(1 for c in checks if c.status == "WARN")
    print("-" * (width + 8))
    print(
        f"  {'all required checks passed' if ok else str(fails) + ' FAIL'}"
        f"{', ' + str(warns) + ' warning(s)' if warns else ''}\n"
    )
    return ok


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="cp2k-forge environment preflight check")
    ap.add_argument("--config", default=None, help="also validate this campaign config")
    ap.add_argument(
        "--no-cp2k", action="store_true", help="skip the CP2K binary/data checks"
    )
    args = ap.parse_args()
    checks = run_checks(args.config, require_cp2k=not args.no_cp2k)
    return 0 if print_report(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
