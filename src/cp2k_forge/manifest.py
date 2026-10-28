"""Resumable run state.

The whole pipeline is a state machine persisted to one JSON file. Every mutation is
written atomically (temp file + os.replace) so a run killed at any point — laptop lid
closed, SLURM pre-emption — resumes from the last completed step rather than restarting.

State shape::

    {
      "config_path": "...",
      "current_pass": 2,
      "stage": "label",            # generate | subsample | label | train | converged
      "passes": [
         {"index": 1,
          "model_path": ".../pass1/model.model",
          "n_labelled_total": 200,
          "force_rmse_mev_ang": 55.3,
          "density_gcc": 0.96,
          "pending_dft": ["<frame_hash>", ...],
          "done_dft":    ["<frame_hash>", ...]},
         ...
      ],
      "converged": false
    }
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

STAGES = ("generate", "subsample", "label", "train", "converged")


class Manifest:
    def __init__(self, path: str | Path, state: dict[str, Any]):
        self.path = Path(path)
        self.state = state

    # ---- lifecycle -------------------------------------------------------
    @classmethod
    def load_or_init(cls, path: str | Path, config_path: str) -> "Manifest":
        p = Path(path)
        if p.exists():
            return cls(p, json.loads(p.read_text()))
        state = {
            "schema_version": 2,  # informational; every reader tolerates absence
            "config_path": str(config_path),
            "current_pass": 1,
            "stage": "generate",
            "passes": [],
            "converged": False,
        }
        m = cls(p, state)
        m.save()
        return m

    def save(self) -> None:
        """Atomic write so a crash never leaves a half-written manifest."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self.state, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # ---- accessors -------------------------------------------------------
    @property
    def current_pass(self) -> int:
        return self.state["current_pass"]

    @property
    def stage(self) -> str:
        return self.state["stage"]

    @property
    def converged(self) -> bool:
        return self.state["converged"]

    def pass_record(self, index: int | None = None) -> dict[str, Any]:
        """Return (creating if absent) the record for a pass."""
        index = self.current_pass if index is None else index
        for rec in self.state["passes"]:
            if rec["index"] == index:
                return rec
        rec = {
            "index": index,
            "model_path": None,
            "n_labelled_total": 0,
            "force_rmse_mev_ang": None,
            "density_gcc": None,
            "pending_dft": [],
            "done_dft": [],
            "validation": None,  # AML-style scorecard (validate.validate_model)
            "timings": {},  # per-stage wall/CPU seconds (cp2k_forge.timing)
        }
        self.state["passes"].append(rec)
        return rec

    def previous_model_path(self) -> str | None:
        """Model from the prior pass — becomes the explorer for the current pass."""
        prev = self.current_pass - 1
        for rec in self.state["passes"]:
            if rec["index"] == prev:
                return rec.get("model_path")
        return None

    def promoted_model_path(self, loop_cfg) -> str | None:
        """Explorer for the current pass under the sampler promotion gate.

        A trained model may explore only after its validation showed it is trustworthy:
        spot-check force score >= loop.promote_min_force_pct, density probe inside
        loop.promote_density_window_gcc, stability MD passed, and — for models that have
        already explored — no density-clamp aborts in the pass they explored (model from
        pass k explores pass k+1, so its clamp record lives there). Walks previous passes
        newest-first and returns the first that qualifies; None means the foundation
        model keeps exploring (the chaperone).

        promote_min_force_pct == 0 disables the gate: the literal previous model is used,
        the legacy behaviour.
        """
        min_pct = getattr(loop_cfg, "promote_min_force_pct", 0.0) or 0.0
        if min_pct <= 0:
            return self.previous_model_path()
        window = getattr(loop_cfg, "promote_density_window_gcc", [0.87, 1.10])
        lo, hi = float(window[0]), float(window[1])
        by_index = {r["index"]: r for r in self.state["passes"]}
        for idx in sorted(by_index, reverse=True):
            if idx >= self.current_pass:
                continue
            rec = by_index[idx]
            model = rec.get("model_path")
            if not model:
                continue
            val = rec.get("validation") or {}
            scores = val.get("scores") or {}
            if (scores.get("force_rmse_pct") or 0.0) < min_pct:
                continue
            rho = rec.get("density_gcc")
            if rho is None or not (lo <= rho <= hi):
                continue
            if (val.get("stability") or {}).get("ok") is False:
                continue
            nxt = by_index.get(idx + 1)
            if nxt is not None and nxt.get("clamp_aborts"):
                continue
            return model
        return None

    # ---- transitions -----------------------------------------------------
    def set_stage(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        self.state["stage"] = stage
        self.save()

    def record_train_result(
        self, model_path: str, n_labelled_total: int, force_rmse_mev_ang: float | None
    ) -> None:
        rec = self.pass_record()
        rec["model_path"] = str(model_path)
        rec["n_labelled_total"] = n_labelled_total
        rec["force_rmse_mev_ang"] = force_rmse_mev_ang
        self.save()

    def record_density(self, density_gcc: float) -> None:
        self.pass_record()["density_gcc"] = density_gcc
        self.save()

    def record_validation(self, report: dict, index: int | None = None) -> None:
        """Store the AML-style validation scorecard for a pass."""
        self.pass_record(index)["validation"] = report
        self.save()

    def record_timings(self, timings: dict, index: int | None = None) -> None:
        """Merge per-stage wall/CPU timings into the pass record (incremental across
        stage-bounded invocations, e.g. label on CPU then train on GPU)."""
        rec = self.pass_record(index)
        rec.setdefault("timings", {}).update(timings)
        self.save()

    def advance_pass(self) -> None:
        self.state["current_pass"] += 1
        self.state["stage"] = "generate"
        self.save()

    def mark_converged(self) -> None:
        self.state["converged"] = True
        self.state["stage"] = "converged"
        self.save()

    def mark_stopped(self, reason: str) -> None:
        """End the campaign WITHOUT claiming convergence (budget cap, diminishing
        returns). `converged` stays False so reports/readers never mistake an early
        stop for a model that met the quality gates."""
        self.state["stopped"] = reason
        self.save()

    @property
    def stopped(self) -> str | None:
        return self.state.get("stopped")

    @staticmethod
    def _pass_plateau(cur: dict, prev: dict, loop_cfg) -> bool:
        """Absolute-plateau criterion for one adjacent pass pair.

        Base rule (legacy): held-out force RMSE below tol AND density barely moved.
        Optional terms, each active only when its LoopConfig field is set: spot-check
        force score, RDF/VDOS self-convergence vs the previous pass, and the
        experimental density anchor. All reads are .get so v1 manifests simply fail
        the extra terms into False (no crash, no false convergence).
        """
        f = cur.get("force_rmse_mev_ang")
        d_cur, d_prev = cur.get("density_gcc"), prev.get("density_gcc")
        if f is None or d_cur is None or d_prev is None:
            return False
        if f > loop_cfg.force_rmse_tol_mev_ang:
            return False
        if abs(d_cur - d_prev) > loop_cfg.density_tol_gcc:
            return False

        val = cur.get("validation") or {}
        scores = val.get("scores") or {}
        conv = val.get("convergence") or {}
        fs_min = getattr(loop_cfg, "force_score_converged_pct", None)
        if fs_min is not None and (scores.get("force_rmse_pct") or 0.0) < fs_min:
            return False
        rdf_min = getattr(loop_cfg, "rdf_converged_pct", None)
        if rdf_min is not None and (conv.get("rdf_prev_pct") or 0.0) < rdf_min:
            return False
        vdos_min = getattr(loop_cfg, "vdos_converged_pct", None)
        if vdos_min is not None and (conv.get("vdos_prev_pct") or 0.0) < vdos_min:
            return False
        anchor = getattr(loop_cfg, "density_anchor_gcc", None)
        anchor_tol = getattr(loop_cfg, "density_anchor_tol_gcc", None)
        if anchor is not None and anchor_tol is not None:
            if abs(d_cur - anchor) > anchor_tol:
                return False
        return True

    def check_convergence(self, loop_cfg) -> bool:
        """Stop the active-learning loop when more data no longer helps.

        Two independent stopping rules (either triggers):
          absolute plateau      _pass_plateau holds for the last
                                loop_cfg.consecutive_passes adjacent pass pairs
                                (>= 2 pairs guards against a lucky pass)
          diminishing returns   force RMSE improved by < min_rel_improvement_force (a
                                fraction) over the previous pass -- the data-efficiency
                                stop: extra labels are not buying accuracy (0 disables it)
        """
        passes = sorted(self.state["passes"], key=lambda r: r["index"])
        if len(passes) < 2:
            return False
        cur, prev = passes[-1], passes[-2]

        n_pairs = max(1, int(getattr(loop_cfg, "consecutive_passes", 1)))
        if len(passes) >= n_pairs + 1:
            if all(
                self._pass_plateau(passes[-1 - k], passes[-2 - k], loop_cfg)
                for k in range(n_pairs)
            ):
                return "plateau"

        # Diminishing returns: prefer the fixed-test RMSE (constant yardstick) when the
        # validation recorded one, else the held-out RMSE as before. This is a STOP
        # signal, never convergence — it bypasses the quality gates by construction,
        # so the caller must record it via mark_stopped, not mark_converged.
        def _rmse(rec):
            val = rec.get("validation") or {}
            raw = val.get("raw") or {}
            return raw.get("test_force_rmse_mev_ang") or rec.get("force_rmse_mev_ang")

        f, f_prev = _rmse(cur), _rmse(prev)
        if loop_cfg.min_rel_improvement_force > 0.0 and f is not None and f_prev:
            rel_gain = (f_prev - f) / f_prev
            if rel_gain < loop_cfg.min_rel_improvement_force:
                return "diminishing_returns"
        return False
