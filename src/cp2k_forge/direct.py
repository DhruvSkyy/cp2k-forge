"""DIRECT config selection: foundation-model features -> PCA -> cluster -> stratified pick.

A re-implementation of the DIRECT recipe (Qi/Ko/Wood/Pham/Ong, npj Comput. Mater. 10:43,
2024) used as the selection stage of the npj single-shot workflow we automate (Zhang 2026).
The featurizer is a FIXED foundation model (MACE-MP-0) -- its invariant per-atom descriptors,
pooled per species -- so selection is consistent across active-learning passes regardless of
the system-specific model being trained. Generic to any chemistry: nothing here is
water-specific.

Pipeline: features -> standardise -> PCA (keep components with eigenvalue > 1, the Kaiser
rule used by DIRECT) -> KMeans(k = n_select) -> take the frame nearest each cluster centroid.
"""

from __future__ import annotations

# Canonical foundation-model size aliases (mirrors engines._MP_ALIASES).
_MP_ALIASES = {"mace-mp-0": "medium", "mp-0": "medium", "mace-mp": "medium"}

_FOUNDATION_CALC = {}  # cache: (model, device) -> calculator (load once per pass)


def _foundation_calc(model: str, device: str):
    key = (model, device)
    calc = _FOUNDATION_CALC.get(key)
    if calc is None:
        from mace.calculators import mace_mp

        calc = mace_mp(
            model=_MP_ALIASES.get(model, model),
            dispersion=False,
            device=device,
            default_dtype="float64",
        )
        _FOUNDATION_CALC[key] = calc
    return calc


def structure_features(frames, model: str = "mace-mp-0", device: str = "cpu"):
    """Fixed-length per-structure feature vectors (per-species mean of MACE descriptors).

    Species columns are ordered by the GLOBAL sorted element set across `frames`, so every
    row has the same length even if a frame is missing a species (missing -> zeros).
    """
    import numpy as np

    calc = _foundation_calc(model, device)
    elements = sorted({s for a in frames for s in a.get_chemical_symbols()})
    rows = []
    ndesc = None
    per_frame = []
    for atoms in frames:
        a = atoms.copy()
        a.calc = None
        d = np.asarray(calc.get_descriptors(a))  # (n_atoms, n_desc)
        ndesc = d.shape[1]
        syms = np.asarray(a.get_chemical_symbols())
        per_frame.append((d, syms))
    for d, syms in per_frame:
        parts = []
        for el in elements:
            mask = syms == el
            parts.append(d[mask].mean(axis=0) if mask.any() else np.zeros(ndesc))
        rows.append(np.concatenate(parts))
    return np.asarray(rows, dtype=float)


def direct_select(
    frames,
    n_select: int,
    model: str = "mace-mp-0",
    device: str = "cpu",
    random_state: int = 0,
    dataset_frames=None,
):
    """Return ~`n_select` diverse frames via the DIRECT recipe. <= n_select returns all.

    Without `dataset_frames` this is the plain per-pass DIRECT pipeline (PCA + KMeans on
    the pool). With `dataset_frames` (the cumulative labelled dataset) the selection is
    dataset-conditioned: pool and dataset are featurized TOGETHER (one batch, so species
    column order cannot diverge), the PCA is fitted on the union, and picks come from
    greedy FPS over the pool seeded with the dataset — every pick maximises distance to
    labelled ∪ picked. KMeans-per-pass would happily re-cover regions the dataset already
    owns, which is exactly the failure mode this removes.
    """
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA
    from sklearn.cluster import KMeans

    frames = list(frames)
    if len(frames) <= n_select:
        return frames
    dataset_frames = list(dataset_frames) if dataset_frames else []

    X = structure_features(frames + dataset_frames, model=model, device=device)
    X = StandardScaler().fit_transform(X)
    # PCA on standardised features: explained_variance_ are correlation-matrix eigenvalues;
    # keep those > 1 (Kaiser). Always keep at least 1 component.
    pca = PCA(n_components=min(X.shape[0], X.shape[1]), random_state=random_state)
    Xp = pca.fit_transform(X)
    keep = max(1, int((pca.explained_variance_ > 1.0).sum()))
    Xp = Xp[:, : min(keep, Xp.shape[1])]
    Xp_pool, Xp_data = Xp[: len(frames)], Xp[len(frames) :]

    if len(Xp_data):
        from .subsample import (
            farthest_point_sample,
        )  # function-local: avoids an import cycle

        idx = farthest_point_sample(Xp_pool, n_select, seed_descriptors=Xp_data)
        return [frames[i] for i in sorted(set(idx))]

    km = KMeans(n_clusters=n_select, random_state=random_state, n_init=10).fit(Xp_pool)
    chosen = []
    for k in range(n_select):
        members = np.where(km.labels_ == k)[0]
        if len(members) == 0:
            continue
        c = km.cluster_centers_[k]
        j = int(members[np.argmin(((Xp_pool[members] - c) ** 2).sum(axis=1))])
        chosen.append(j)
    return [frames[i] for i in sorted(set(chosen))]
