"""Extract time-uncorrelated frames from a single MD trajectory.

Consecutive MD snapshots are correlated on the timescale of the slowest relevant motion;
for liquid water the hydrogen-bond network reorganises on ~3 ps, so sampling faster than
that spends the DFT budget on near-duplicate structures. This module measures the
decorrelation time of a scalar observable *from the trajectory itself* and strides the
frames at (at least) twice that time, per individual trajectory (each T/density cell).

This is the cheap, physically-motivated alternative to always running farthest-point
sampling: it needs no model, only the frames already produced. FPS (cp2k_forge.subsample) can
still run afterwards as an optional diversity refinement so its marginal value is
measurable (subsample.enabled).

All arithmetic is done here in Python (e.g. a 1 ps interval at 0.5 fs is 2000 steps,
computed, never hardcoded).
"""

from __future__ import annotations

import math


def hbond_count(
    atoms, r_ha: float = 2.5, angle_min_deg: float = 150.0, r_oh_cov: float = 1.2
) -> float:
    """Number of O-H...O hydrogen bonds by the geometric (distance+angle) criterion.

    For each H: its covalently bonded O (nearest O within `r_oh_cov`) is the donor; any
    other O within `r_ha` of the H is an acceptor if the donor-H...acceptor angle at H
    exceeds `angle_min_deg`. Angles use minimum-image displacement vectors so the count
    is correct across periodic boundaries. This scalar fluctuates as the H-bond network
    rearranges, so its autocorrelation time tracks the network decorrelation time.
    """
    import numpy as np

    sym = np.asarray(atoms.get_chemical_symbols())
    o_idx = np.where(sym == "O")[0]
    h_idx = np.where(sym == "H")[0]
    if o_idx.size == 0 or h_idx.size == 0:
        return 0.0

    dist = atoms.get_all_distances(mic=True)
    count = 0
    for h in h_idx:
        d_oh = dist[h, o_idx]
        donor = o_idx[int(np.argmin(d_oh))]
        if dist[h, donor] > r_oh_cov:
            continue  # not covalently bound (rare)
        acceptors = o_idx[(dist[h, o_idx] <= r_ha) & (o_idx != donor)]
        if acceptors.size == 0:
            continue
        v_d = atoms.get_distance(h, donor, mic=True, vector=True)
        nv_d = np.linalg.norm(v_d)
        for a in acceptors:
            v_a = atoms.get_distance(h, int(a), mic=True, vector=True)
            cos = float(np.dot(v_d, v_a) / (nv_d * np.linalg.norm(v_a) + 1e-12))
            if math.degrees(math.acos(max(-1.0, min(1.0, cos)))) > angle_min_deg:
                count += 1
    return float(count)


def _potential_energy(atoms) -> float:
    # Sampled frames have their calculator stripped; the engine stores the MD potential
    # energy in info so the "energy" observable works without a recompute.
    if "md_epot_ev" in atoms.info:
        return float(atoms.info["md_epot_ev"])
    try:
        return float(atoms.get_potential_energy())
    except Exception:
        return 0.0


def _density_gcc(atoms) -> float:
    import numpy as np

    amu_to_g = 1.66053906660e-24
    ang3_to_cm3 = 1.0e-24
    return (float(np.sum(atoms.get_masses())) * amu_to_g) / (
        atoms.get_volume() * ang3_to_cm3
    )


def observable_series(frames, kind: str = "hbond"):
    """Per-frame scalar time series used to measure the decorrelation time."""
    import numpy as np

    if kind == "hbond":
        vals = [hbond_count(a) for a in frames]
    elif kind == "energy":
        vals = [_potential_energy(a) for a in frames]
    elif kind == "density":
        vals = [_density_gcc(a) for a in frames]
    else:
        raise ValueError(f"unknown decorrelation observable {kind!r}")
    return np.asarray(vals, dtype=float)


def _acf_fft(x):
    """Normalised autocorrelation function of a 1-D series via FFT (unbiased lags)."""
    import numpy as np

    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    n = x.size
    if n < 2 or not np.any(x):
        return np.ones(1)
    f = np.fft.rfft(x, 2 * n)
    acf = np.fft.irfft(f * np.conj(f))[:n]
    acf /= np.arange(n, 0, -1)  # unbiased: divide lag k by (n-k) samples
    if acf[0] == 0:
        return np.ones(1)
    return acf / acf[0]


def autocorr_time(series, timestep_fs: float, stride_steps: int) -> float:
    """Integrated autocorrelation time of `series` in fs.

    `series` is sampled every `stride_steps` MD steps, so the lag spacing is
    `stride_steps * timestep_fs` fs. tau = dt_lag * (1 + 2*sum_k acf[k]) summed up to the
    first zero crossing (the standard windowed estimator). White noise -> tau ~ dt_lag;
    a slowly varying signal -> a larger tau.
    """
    acf = _acf_fft(series)
    dt_lag = stride_steps * timestep_fs
    total = 0.0
    for k in range(1, acf.size):
        if acf[k] <= 0.0:
            break
        total += acf[k]
    return float(dt_lag * (1.0 + 2.0 * total))


def subsample_interval(
    series, timestep_fs: float, stride_steps: int, floor_fs: float = 1000.0
):
    """Return (interval_frames, tau_fs, n_available, tau_reliable).

    interval_frames is how many *stored frames* (each `stride_steps` apart) to skip so
    consecutive kept frames are ~2 tau apart, never closer than `floor_fs`. n_available is
    how many uncorrelated frames the trajectory can yield at that interval.

    tau_reliable is True when the observation window spans >= 20x the measured tau
    (Sokal's rule of thumb for a stable integrated-ACF estimate). On a shorter window the
    windowed estimator can only UNDERestimate tau, so max(2*tau, floor) never over-strides
    either way — the flag marks that the floor, not the measurement, is the authoritative
    interval, and is surfaced per cell in decorr.json.
    """
    tau_fs = autocorr_time(series, timestep_fs, stride_steps)
    window_fs = max(0, len(series) - 1) * stride_steps * timestep_fs
    tau_reliable = bool(window_fs >= 20.0 * tau_fs) if tau_fs > 0 else True
    # The floor is AUTHORITATIVE when tau is unreliable (window < 20*tau): a windowed
    # estimate there cannot be trusted to widen the stride, and letting it do so is
    # what turns one slow cell into a deterministic undersample abort.
    interval_fs = max(2.0 * tau_fs, floor_fs) if tau_reliable else floor_fs
    frame_dt_fs = stride_steps * timestep_fs
    interval_frames = max(1, math.ceil(interval_fs / frame_dt_fs))
    n_series = len(series)
    n_available = 1 + (n_series - 1) // interval_frames if n_series else 0
    return interval_frames, tau_fs, n_available, tau_reliable


def pick_uncorrelated(frames, interval_frames: int, target_n: int = 100):
    """Stride `frames` by `interval_frames` and cap at `target_n`."""
    picked = list(frames)[:: max(1, interval_frames)]
    return picked[:target_n]
