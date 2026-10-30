"""Human-readable validation reporting: the per-pass scorecard.

The meeting ask was a "super clear way to get the validation steps" out of the workflow:
every validation step is listed by name with its inputs, threshold, measured value and a
PASS / FAIL / SKIPPED(+why) verdict, in the order the steps ran. Written as
passN/validate/scorecard.md and echoed to stdout (so it also lands in the SLURM log).
scripts/print_report.py aggregates the campaign-level view.
"""

from __future__ import annotations

from pathlib import Path


def _fmt(x, spec="{}"):
    return spec.format(x) if x is not None else "-"


def _verdict(ok) -> str:
    # None = the check RAN but no threshold is configured (distinct from SKIPPED rows,
    # which say so explicitly with a reason).
    if ok is None:
        return "REPORTED"
    return "PASS" if ok else "FAIL"


def _scorecard_rows(report: dict, pass_rec: dict, prev_rec: dict | None, cfg) -> list:
    """Build (step, inputs, threshold, value, verdict) rows in validation order."""
    s = report.get("scores", {})
    raw = report.get("raw", {})
    conv = report.get("convergence", {})
    stab = report.get("stability", {})
    loop = cfg.loop
    v = cfg.validate_cfg
    rows = []

    # 1. Static test on the fixed test set (gate: no regression vs previous pass).
    if "test_force_pct" in s:
        prev_pct = None
        if prev_rec:
            prev_val = prev_rec.get("validation") or {}
            prev_pct = (prev_val.get("scores") or {}).get("test_force_pct")
        thr = (
            f">= {prev_pct - 2.0:.1f}% (prev - 2%)"
            if prev_pct is not None
            else "report only (no previous pass)"
        )
        ok = None if prev_pct is None else s["test_force_pct"] >= prev_pct - 2.0
        rows.append(
            (
                "1. Static test (fixed set)",
                f"{raw.get('n_test_frames', '?')} DFT frames",
                thr,
                f"{s['test_force_pct']:.1f}% "
                f"(RMSE {_fmt(raw.get('test_force_rmse_mev_ang'), '{:.1f}')} meV/A)",
                _verdict(ok),
            )
        )
    else:
        rows.append(
            (
                "1. Static test (fixed set)",
                "-",
                "-",
                "-",
                "SKIPPED (validate.fixed_test_xyz unset or missing)",
            )
        )

    # 2. Stability MD (geometric blow-up check on the spot-check trajectory).
    if stab:
        rows.append(
            (
                "2. Stability MD",
                f"{v.spotcheck_md_steps} steps NVT @ {v.spotcheck_temperature_k:.0f} K",
                f"min any >= {stab.get('threshold_any_ang')} A, "
                f"min O-O >= {stab.get('threshold_oo_ang')} A, "
                f"min O-H >= {stab.get('threshold_oh_ang')} A",
                f"min any {_fmt(stab.get('min_any_ang'))} A, "
                f"min O-O {_fmt(stab.get('min_oo_ang'))} A, "
                f"min O-H {_fmt(stab.get('min_oh_ang'))} A",
                _verdict(stab.get("ok")),
            )
        )

    # 3. On-policy spot-check (AML force score on the model's own dynamics).
    if "force_rmse_pct" in s:
        thr_parts = []
        if loop.force_score_converged_pct is not None:
            thr_parts.append(f">= {loop.force_score_converged_pct:.0f}% converge")
        if loop.promote_min_force_pct:
            thr_parts.append(f">= {loop.promote_min_force_pct:.0f}% promote")
        ok = None
        if loop.force_score_converged_pct is not None:
            ok = s["force_rmse_pct"] >= loop.force_score_converged_pct
        rows.append(
            (
                "3. On-policy spot-check",
                f"{raw.get('n_dft_spotcheck', '?')} DFT points on own MD",
                "; ".join(thr_parts) or "report only",
                f"{s['force_rmse_pct']:.1f}% "
                f"(RMSE {_fmt(raw.get('force_rmse_mev_ang'), '{:.1f}')} meV/A, "
                f"E MAE {_fmt(raw.get('energy_mae_mev_atom'), '{:.1f}')} meV/atom)",
                _verdict(ok),
            )
        )

    # 4. Density probe vs anchor + promotion window.
    rho = raw.get("density_gcc")
    if rho is not None:
        window = loop.promote_density_window_gcc
        ok = window[0] <= rho <= window[1] if loop.promote_min_force_pct else None
        ref = raw.get("density_ref_gcc")
        rows.append(
            (
                "4. Density probe (NPT)",
                f"{v.density_probe_steps} steps @ " f"{cfg.showcase.barostat} barostat",
                f"in [{window[0]}, {window[1]}] g/cc for promotion"
                + (f"; anchor {ref} g/cc reported" if ref is not None else ""),
                f"{rho:.4f} g/cc",
                _verdict(ok),
            )
        )
    else:
        rows.append(("4. Density probe (NPT)", "-", "-", "-", "SKIPPED (probe failed)"))

    # 5. RDF: self-convergence vs previous pass (+ external ref and anchor if present).
    if "rdf_prev_pct" in conv:
        ok = (
            conv["rdf_prev_pct"] >= loop.rdf_converged_pct
            if loop.rdf_converged_pct is not None
            else None
        )
        rows.append(
            (
                "5. RDF vs previous pass",
                f"{raw.get('n_rdf_frames', '?')} frames, "
                f"{'/'.join(''.join(p) for p in v.rdf_pairs)}",
                _fmt(loop.rdf_converged_pct, ">= {:.0f}%"),
                f"{conv['rdf_prev_pct']:.1f}%",
                _verdict(ok),
            )
        )
    else:
        rows.append(
            (
                "5. RDF vs previous pass",
                "-",
                "-",
                "-",
                "SKIPPED (first pass or observables missing)",
            )
        )
    if "rdf_pct" in s:
        rows.append(
            (
                "5b. RDF vs external ref",
                str(v.rdf_ref_xyz),
                "report only",
                f"{s['rdf_pct']:.1f}%",
                "PASS" if s["rdf_pct"] > 0 else "FAIL",
            )
        )
    if raw.get("goo_peak_r_ang") is not None:
        ref_r, ref_h = raw.get("goo_peak_r_ref_ang"), raw.get("goo_peak_h_ref")
        tail = f" (expt {ref_r} A / {ref_h})" if ref_r is not None else ""
        rows.append(
            (
                "5c. g_OO first peak (anchor)",
                "from the RDF above",
                "report only, never gated",
                f"r {raw['goo_peak_r_ang']:.2f} A, h {raw['goo_peak_h']:.2f}{tail}",
                "REPORTED",
            )
        )

    # 6. VDOS: self-convergence + NVE energy conservation.
    if "vdos_prev_pct" in conv:
        ok = (
            conv["vdos_prev_pct"] >= loop.vdos_converged_pct
            if loop.vdos_converged_pct is not None
            else None
        )
        rows.append(
            (
                "6. VDOS vs previous pass",
                f"{v.vdos_md_steps} NVE steps",
                _fmt(loop.vdos_converged_pct, ">= {:.0f}%"),
                f"{conv['vdos_prev_pct']:.1f}%",
                _verdict(ok),
            )
        )
    elif v.vdos_enabled:
        rows.append(
            (
                "6. VDOS vs previous pass",
                f"{v.vdos_md_steps} NVE steps",
                "-",
                "-",
                "SKIPPED (first pass or observables missing)",
            )
        )
    else:
        rows.append(
            (
                "6. VDOS vs previous pass",
                "-",
                "-",
                "-",
                "SKIPPED (validate.vdos_enabled=false)",
            )
        )
    if "vdos_pct" in s:
        rows.append(
            (
                "6b. VDOS vs external ref",
                str(v.vdos_ref_npy),
                "report only",
                f"{s['vdos_pct']:.1f}%",
                "PASS" if s["vdos_pct"] > 0 else "FAIL",
            )
        )
    drift = raw.get("nve_drift_mev_atom_ps")
    if drift is not None:
        rows.append(
            (
                "6c. NVE energy conservation",
                "the VDOS trajectory",
                "abs drift < 5 meV/atom/ps",
                f"{drift:+.3f} meV/atom/ps",
                _verdict(abs(drift) < 5.0),
            )
        )

    # 7. AML-package cross-score (Christoph's own code).
    aml = report.get("aml") or {}
    if "rdf_prev_pct" in aml:
        rows.append(
            (
                "7. AML package RDF cross-score",
                "aml.score on exported trajs",
                "agrees with row 5",
                f"{aml['rdf_prev_pct']:.1f}%",
                "REPORTED",
            )
        )
    return rows


def render_pass_scorecard(
    report: dict, pass_rec: dict, prev_rec: dict | None, cfg, pass_index: int
) -> str:
    rows = _scorecard_rows(report, pass_rec, prev_rec, cfg)
    lines = [f"# Validation scorecard — pass {pass_index}", ""]
    lines.append(f"Model: `{report.get('model_path')}`")
    explorer = pass_rec.get("explorer")
    if explorer:
        lines.append(f"Explorer this pass: `{explorer}`")
    lines += [
        "",
        "| step | inputs | threshold | value | verdict |",
        "|---|---|---|---|---|",
    ]
    for step, inputs, thr, value, verdict in rows:
        lines.append(f"| {step} | {inputs} | {thr} | {value} | {verdict} |")
    s = report.get("scores", {})
    lines += [
        "",
        f"**Overall (AML trio): {_fmt(s.get('overall_pct'), '{:.1f}')}%**",
        "",
    ]

    decorr = report.get("decorrelation") or {}
    if decorr:
        lines.append(
            f"Sampling: {decorr.get('n_uncorrelated_total', '?')} uncorrelated "
            f"candidates (mean tau "
            f"{_fmt(decorr.get('mean_tau_fs'), '{:.0f}')} fs, mean interval "
            f"{_fmt(decorr.get('mean_interval_frames'))} frames)"
        )
    timings = pass_rec.get("timings") or {}
    if timings:
        parts = sorted(timings.items(), key=lambda kv: -kv[1].get("wall_s", 0))
        bottleneck = parts[0][0] if parts else "-"
        lines.append(
            "Stage wall times: "
            + "  ".join(f"{k} {v.get('wall_s', 0):.0f}s" for k, v in parts)
            + f"  -> bottleneck: **{bottleneck}**"
        )
    notes = report.get("notes") or []
    if notes:
        lines.append("")
        lines.extend(f"- note: {n}" for n in notes)
    lines.append("")
    return "\n".join(lines)


def write_pass_scorecard(
    report: dict,
    pass_rec: dict,
    prev_rec: dict | None,
    cfg,
    pass_index: int,
    out_md: str | Path,
) -> Path:
    out = Path(out_md)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_pass_scorecard(report, pass_rec, prev_rec, cfg, pass_index),
        encoding="utf-8",
    )  # job locale is ASCII; scorecards use em-dashes
    return out


def print_scorecard(report: dict, pass_index: int) -> None:
    """Compact stdout summary (also lands in the SLURM log)."""

    def _one(rep, header):
        s, raw = rep["scores"], rep["raw"]
        print(header)
        if "test_force_pct" in s:
            print(
                f"  Test set     {raw.get('test_force_rmse_mev_ang', 0):.1f} meV/A   -> "
                f"{s['test_force_pct']:.0f}%   [{raw.get('n_test_frames', '?')} fixed frames]"
            )
        if raw.get("force_rmse_mev_ang") is not None:
            print(
                f"  Force RMSE   {raw['force_rmse_mev_ang']:.1f} meV/A   -> "
                f"{s['force_rmse_pct']:.0f}%   [{raw['n_dft_spotcheck']} DFT spot-checks]"
            )
        elif "force_rmse_pct" in s:
            print(
                f"  Force score  {s['force_rmse_pct']:.0f}%   [fixed test set anchor, "
                "spot-check disabled]"
            )
        conv = rep.get("convergence") or {}
        if "rdf_prev_pct" in conv:
            print(f"  RDF vs prev               -> {conv['rdf_prev_pct']:.0f}%")
        if "rdf_pct" in s:
            print(f"  RDF match    OO/OH/HH     -> {s['rdf_pct']:.0f}%")
        if "vdos_prev_pct" in conv:
            print(f"  VDOS vs prev              -> {conv['vdos_prev_pct']:.0f}%")
        if "vdos_pct" in s:
            print(f"  VDOS match                -> {s['vdos_pct']:.0f}%")
        if "density_gcc" in raw:
            ref = raw.get("density_ref_gcc")
            tail = f" (ref {ref:.3f})" if ref is not None else ""
            print(f"  Density      {raw['density_gcc']:.3f} g/cc{tail}")
        stab = rep.get("stability") or {}
        if stab:
            print(
                f"  Stability    {'OK' if stab.get('ok') else 'FAILED'} "
                f"(min any {stab.get('min_any_ang')} A, "
                f"min O-O {stab.get('min_oo_ang')} A, min O-H {stab.get('min_oh_ang')} A)"
            )
        print(f"  Overall                   -> {s['overall_pct']:.0f}%")
        for note in rep.get("notes", []):
            print(f"  note: {note}")

    _one(report, f"\n=== VALIDATION (pass {pass_index}, current model) ===")
    if report.get("previous_model"):
        _one(
            report["previous_model"],
            "--- previous-iteration model (DFT-reference level) ---",
        )
