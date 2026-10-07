"""Diversity-based frame selection (no committee, no active learning).

From the many MD snapshots, pick `n_per_pass` *diverse* frames to send to DFT, so the
expensive labelling budget is spent on structurally distinct configurations rather than
near-duplicates. Selection is farthest-point sampling (FPS) on a cheap per-frame
descriptor (a smooth radial-distribution histogram), which needs only numpy + ASE.

This is the deliberate alternative to query-by-committee uncertainty selection: simpler,
single-pass, and engine-agnostic. It can be swapped for an uncertainty rule later if DFT
cost becomes the bottleneck.
"""

from __future__ import annotations


def frame_descriptor(atoms, r_max: float = 6.0, nbins: int = 60):
    """Smooth radial-distribution histogram of all minimum-image pair distances."""
    import numpy as np

    n = len(atoms)
    if n < 2:
        return np.zeros(nbins)
    d = atoms.get_all_distances(mic=True)
    iu = np.triu_indices(n, k=1)
    dists = d[iu]
    dists = dists[dists < r_max]
    hist, _ = np.histogram(dists, bins=nbins, range=(0.0, r_max), density=False)
    # Normalise by atom count so descriptors are comparable across box sizes.
    return hist.astype(float) / float(n)


def farthest_point_sample(
    descriptors, n_select: int, seed_descriptors=None
) -> list[int]:
    """Greedy FPS: indices maximally spread in descriptor space (max-min distance).

    With `seed_descriptors` (descriptors of structures ALREADY in the labelled dataset)
    the min-distance field is initialised against them, so every pick maximises distance
    to labelled-set ∪ picked-so-far — the labelling budget is never spent re-covering
    regions the dataset already owns ("only label new candidates").
    """
    import numpy as np

    X = np.asarray(descriptors, dtype=float)
    m = len(X)
    if n_select >= m:
        return list(range(m))

    if seed_descriptors is not None and len(seed_descriptors):
        S = np.asarray(seed_descriptors, dtype=float)
        min_d = np.full(m, np.inf)
        for s in S:  # row-wise to keep memory flat for big datasets
            min_d = np.minimum(min_d, np.linalg.norm(X - s, axis=1))
        selected: list[int] = []
    else:
        # Seed from the frame farthest from the centroid (deterministic, no RNG).
        centroid = X.mean(axis=0)
        first = int(np.argmax(np.linalg.norm(X - centroid, axis=1)))
        selected = [first]
        min_d = np.linalg.norm(X - X[first], axis=1)
    while len(selected) < n_select:
        nxt = int(np.argmax(min_d))
        selected.append(nxt)
        min_d = np.minimum(min_d, np.linalg.norm(X - X[nxt], axis=1))
    return selected


def subsample(
    frames,
    n_per_pass: int,
    method: str = "fps",
    foundation_model: str = "mace-mp-0",
    device: str = "cpu",
    dataset_frames=None,
    rng_seed: int = 0,
):
    """Return up to `n_per_pass` diverse frames from `frames`.

    method="none"   -> no diversity selection; label the (already-decorrelated) frames as
                       they are. Tests whether time-decorrelation alone suffices.
    method="random" -> seeded uniform draw; the null hypothesis for the selection ablation.
    method="fps"    -> farthest-point sampling on a hand-built RDF descriptor (no model).
    method="direct" -> DIRECT (foundation-model features -> PCA -> KMeans -> stratified pick);
                       `foundation_model`/`device` select the featurizer (the npj recipe).

    `dataset_frames` (the cumulative labelled dataset) makes "fps" and "direct" dataset-
    conditioned: picks maximise distance to what is already labelled, not just to each
    other. Ignored by "random"/"none".
    """
    if not frames:
        return []
    if method == "none":
        return list(frames)
    if len(frames) <= n_per_pass:
        return list(frames)
    if method == "random":
        import random

        idx = sorted(random.Random(rng_seed).sample(range(len(frames)), n_per_pass))
        return [frames[i] for i in idx]
    if method == "fps":
        descriptors = [frame_descriptor(a) for a in frames]
        seed_desc = (
            [frame_descriptor(a) for a in dataset_frames] if dataset_frames else None
        )
        idx = farthest_point_sample(descriptors, n_per_pass, seed_descriptors=seed_desc)
        return [frames[i] for i in idx]
    if method == "direct":
        from .direct import direct_select

        return direct_select(
            frames,
            n_per_pass,
            model=foundation_model,
            device=device,
            dataset_frames=dataset_frames,
        )
    raise ValueError(
        f"unknown subsample method {method!r} (use 'fps', 'direct', 'random' or 'none')"
    )
