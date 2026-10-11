"""Campaign configuration: load and validate the YAML that drives a pipeline run.

The config is intentionally explicit and flat-ish so a non-expert can edit one file
(`configs/water_tmd.yaml`) and change DFT level, the explore T/density grid, the
target model size, and the convergence tolerances without touching code.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SystemConfig:
    name: str
    seed_xyz: str  # path to the initial structure (extended XYZ)
    elements: list[str]
    cell_abc: list[float]  # orthorhombic box of the seed structure, Angstrom


@dataclass
class DFTConfig:
    functional: str = "revPBE"  # XC functional for labelling
    dispersion_ref: str = "revPBE"  # REFERENCE_FUNCTIONAL for the D3 correction
    d3_damping: str = "zero"  # "zero" (DFTD3) or "bj" (DFTD3(BJ)). For water/revPBE,
    # zero-damping is correct; BJ inverts the ice/water
    # density order (JCP 161:131102).
    cutoff_ry: float = 400.0
    rel_cutoff_ry: float = 50.0
    basis_set: str = (
        "TZV2P-MOLOPT-GTH"  # SR variant is absent for H/O; this is the std water basis
    )
    potential: str = "GTH-PBE"  # GTH-PBE pseudos are standard for (rev)PBE water
    eps_scf: float = 1.0e-6
    max_scf: int = 20
    # --- hybrid / ADMM (mode="gga" keeps the GGA path byte-identical) ---
    # mode="hybrid" renders templates/dft_singlepoint_hybrid.inp: a PBE-family GGA
    # exchange scaled by (1 - hf_fraction) plus exact exchange under ADMM with a
    # truncated Coulomb operator (revPBE0 = functional revPBE + hf_fraction 0.25).
    mode: str = "gga"  # "gga" | "hybrid"
    hf_fraction: float = 0.25  # &HF FRACTION; GGA SCALE_X = 1 - hf_fraction
    hfx_cutoff_radius_ang: float = (
        6.0  # truncated Coulomb radius; MUST be < min(cell)/2
    )
    # for EVERY labelled frame (guarded per frame in
    # cp2k_io) and must never change mid-campaign
    # (it is part of the level of theory)
    eps_schwarz: float = 1.0e-6  # &HF &SCREENING EPS_SCHWARZ
    hfx_max_memory_mb: int = 2400  # &HF &MEMORY MAX_MEMORY, per MPI rank
    admm_basis: str = "cpFIT3"  # AUX_FIT basis for every kind (BASIS_ADMM file)
    admm_basis_overrides: dict = field(default_factory=dict)  # per-element AUX_FIT
    # override, e.g. {F: aug-cpFIT3} — anions want
    # diffuse auxiliary functions
    admm_purification: str = "MO_DIAG"  # ADMM_PURIFICATION_METHOD
    admm_exch_correction_func: str = (
        "PBEX"  # EXCH_CORRECTION_FUNC (EXCH_SCALING_MODEL NONE)
    )
    # --- electrostatics ---
    charge: int = 0  # &DFT CHARGE: net cell charge (e.g. -1 for a
    # charged box; compensated by the GPW background).
    # E0 atoms stay neutral regardless (cp2k_forge.e0s).
    uks: bool = False  # open-shell labelling (E0 atoms set UKS via
    # their own template independent of this)
    cp2k_bin: str = "cp2k.psmp"
    cp2k_ranks: int = 4
    label_workers: int = 1  # concurrent CP2K frames per node; one 192-atom
    # point stops scaling near ~16 cores, so ~4
    # workers x (ranks x ncpu/(ranks*workers)) beats
    # one full-width run ~3-4x on a 76-core node
    # Label backend: "cp2k" is the science path. "mock_foundation" labels with the cached
    # foundation calculator instead of DFT so the full loop (including the validation
    # spot-check and isolated-atom E0s) can be smoke-tested on a machine without CP2K.
    # Plumbing only, never for science.
    backend: str = "cp2k"
    mock_model: str = "mace-mp-0"
    mock_device: str = "cpu"


@dataclass
class GeneratorConfig:
    model: str = "mace-mp-0"  # foundation model name or path to a .model file
    dispersion: bool = True  # add D3 (mandatory for water — MP-0 has none)
    device: str = "cpu"
    engine: str = "ase"  # "ase" (default, runs anywhere with mace-torch)
    # or "cp2k-backend": trained models explore inside
    # CP2K via the MACE backend (needs a metatomic-
    # enabled CP2K build). The foundation pass stays
    # ASE (it needs the D3 add-on)
    enable_cueq: bool = False  # cuEquivariance kernels for torch-side MD
    # (foundation explorer / probes); needs the
    # cueq packages — silently off if missing


@dataclass
class ExploreConfig:
    temperatures_k: list[float] = field(default_factory=lambda: [250, 270, 290, 310])
    density_scales: list[float] = field(default_factory=lambda: [0.95, 1.0, 1.05])
    md_workers: int = 1  # >1: run the grid cells in worker processes,
    # round-robin over visible GPUs (identical output;
    # cells have deterministic per-cell seeds)
    # v4 (Schran): explicit +/- pressure cells replace density scaling. density_scales
    # only set INITIAL volumes (NPT relaxes back to the sampler's biased equilibrium —
    # how pass 1 ended up all-dense); explicit pressures pin the ENSEMBLE, so sampled
    # densities genuinely bracket and P(rho) is learned by interpolation. When set,
    # the grid is temperatures_k x pressures_bar and density_scales is ignored.
    # Choose values with scripts/make_eos_grid.py ("meaningful pressures").
    pressures_bar: list[float] | None = None
    # v4 (Schran): "same frame -> same equilibration": warm-start each cell from ITS
    # final frame of the previous pass (fresh deterministic velocities). The cache
    # updates ONLY from gate-passing explorers/foundation, so a refused model can
    # never poison future starting points.
    warm_start_cells: bool = False
    warm_equilibration_steps: int | None = None  # shorter equil from a warm start
    # (None -> equilibration_steps)
    ensemble: str = "NPT"  # NPT samples density too (more phase space); NVT
    # keeps the box fixed at the scaled seed density
    steps: int = 10000  # long enough to yield time-uncorrelated frames;
    # a water H-bond decorrelates on ~3 ps, so at 0.5 fs
    # ~100 uncorrelated frames need ~200k steps summed
    # over the T/density grid (raise per campaign need)
    timestep_fs: float = 0.5
    sample_every: int = 50  # raw probe stride: store a frame every N MD steps.
    # In "fixed" mode these are the candidates; in
    # "decorrelation" mode they are strided further below
    equilibration_steps: int = 200  # discard before sampling
    # NPT barostat (used when ensemble == "NPT")
    pressure_bar: float = 1.0
    compressibility_au: float = 4.57e-5  # water isothermal compressibility, per bar
    friction: float = 0.01  # Langevin friction (NVT only)
    deuterium_masses: bool = (
        False  # opt-in: D masses (Schran et al. protocol; pair with
    )
    # a 1 fs step). Off by default so H physics is unchanged
    # NPT stability guard: abort a trajectory whose density leaves the physical window
    # (an under-trained model can otherwise collapse or evaporate the box).
    density_min_gcc: float = 0.6
    density_max_gcc: float = 1.3
    clamp_patience: int = 5  # consecutive out-of-window samples before abort
    # Decorrelation-based subsampling (per individual T/density trajectory)
    sample_mode: str = "decorrelation"  # "decorrelation" | "fixed"
    decorrelation_observable: str = "hbond"  # "hbond" | "energy" | "density"
    target_uncorrelated: int = 100  # per-trajectory cap on uncorrelated frames
    min_sample_every_fs: float = (
        1000.0  # 1 ps floor (encodes the H-bond-lifetime argument)
    )
    # What to do when a cell cannot yield target_uncorrelated frames at the stride the
    # decorrelation analysis demands: "warn" records the shortfall and continues (legacy
    # behaviour, now loud); "fail" aborts the generate stage so the campaign never runs
    # on silently-thin sampling. A static feasibility check at config load catches the
    # arithmetic version of this before any MD is spent.
    on_undersample: str = "warn"  # "warn" | "fail"
    # Replicas: extra trajectories per (T, density_scale) cell that differ only in their
    # initial Maxwell-Boltzmann velocity seed. Every cell gets a deterministic seed
    # derived from velocity_seed_base + pass + cell index, so identical (T, scale) cells
    # explore genuinely different phase-space paths instead of relying on thermostat noise.
    n_replicas: int = 1
    velocity_seed_base: int = 0
    # Integrators. Berendsen relaxes fast but suppresses the very fluctuations NPT
    # sampling is for (non-canonical), so it is only ever used for the discarded
    # equilibration segment; "mtk" runs production with a canonical NPT integrator
    # (IsotropicMTKNPT on ASE >= 3.25, ase.md.npt.NPT Melchionna as fallback).
    barostat: str = "berendsen"  # production barostat: "berendsen" | "mtk"
    nvt_thermostat: str = "langevin"  # NVT segments: "langevin" | "bussi" (CSVR)
    tdamp_fs: float = 100.0  # thermostat time constant (standard for water)
    pdamp_fs: float = 1000.0  # barostat 10x slower than thermostat (avoids ringing)


@dataclass
class SubsampleConfig:
    n_per_pass: int = 200  # diverse frames selected for DFT each pass
    n_first_pass: int | None = None  # seed-pass budget (e.g. 20 while later passes take
    # 10): a from-scratch model needs a larger first
    # batch to be MD-stable; None -> n_per_pass
    method: str = "fps"  # "fps" | "direct" | "random" | "none" (see `enabled`)
    min_frames: int = 50
    enabled: bool = True  # when False, skip diversity selection and label the
    # decorrelated frames directly (tests whether
    # time-decorrelation alone suffices; measurable A/B)
    # Condition selection on the cumulative labelled dataset: picks maximise distance to
    # labelled-set ∪ picked-so-far, so the budget is never spent re-covering regions the
    # dataset already owns ("only label new candidates").
    dataset_aware: bool = False
    selection_seed: int = 0  # RNG seed for method="random" (varied per pass)


@dataclass
class TrainConfig:
    mace_run_train_bin: str = "mace_run_train"
    device: str = "cpu"
    seed: int = 1
    # Compact-model knobs — small by design (the speed claim depends on this).
    num_channels: int = 64
    max_ell: int = 2
    r_max: float = 5.0
    num_interactions: int = 2
    batch_size: int = 5
    max_num_epochs: int = 200
    valid_fraction: float = 0.1
    stress_weight: float = (
        0.0  # >0 trains on the virial/stress (fixes 1-bar density for
    )
    # TMD; leave 0 until the stress sign/format is validated)
    energy_key: str = "REF_energy"
    forces_key: str = "REF_forces"
    stress_key: str = "REF_stress"
    # ZBL pair repulsion: guarantees short-range repulsion that a tiny early dataset
    # cannot teach (guards against the box-collapse failure of undertrained models).
    pair_repulsion: bool = False
    pair_repulsion_until_pass: int = 0  # 0 = every pass (when pair_repulsion); N = only
    # passes <= N (scaffolding dropped once stable)
    # Atomic reference energies. "average" least-squares-fits E0s from the dataset every
    # pass, which silently shifts the energy baseline as the dataset grows (and is
    # degenerate for a fixed-composition box); "isolated" uses one-time spin-polarized
    # isolated-atom calcs at the exact labelling level (cp2k_forge.e0s, cached in the workdir);
    # "file" reads a prepared e0s.json (e.g. for smoke tests without CP2K).
    e0s_mode: str = "average"  # "average" | "isolated" | "file"
    e0s_file: str | None = None  # path for e0s_mode="file"
    # Optimizer stability. EMA is the standard MACE stabilizer and is REQUIRED for stable
    # force training: without it the force loss climbs after ~1e2 epochs and the run keeps
    # only an early checkpoint, plateauing well short of convergence (observed on the 32-water
    # pilot: ~57 meV/A). MACE's default lr=0.01 is stable WITH ema; lower it if a run still
    # diverges. SWA is an optional stage-two boost (higher energy weight + weight averaging)
    # that improves the energy/density balance. patience early-stops stalled runs.
    lr: float = 0.01
    ema: bool = True
    ema_decay: float = 0.99
    swa: bool = False
    start_swa: int | None = None  # default: 3/4 of max_num_epochs
    swa_energy_weight: float = 1000.0
    patience: int | None = None  # early-stop after N epochs with no valid improvement
    eval_interval: int | None = None  # evaluate valid every N epochs (mace default 1;
    # per-epoch eval is a large share of small-data
    # epoch time)
    # v4 (Schran): continually train — warm-start each pass from the previous pass's
    # model instead of random init (pass 1 stays from scratch). Provenance unchanged:
    # only our DFT labels ever enter the loss. warm_lr replaces lr on continuation
    # passes (a hot LR on a warm start un-learns; 0.005 = the finetune arm's value).
    warm_start: bool = False
    warm_lr: float | None = None
    cold_epochs: int | None = None  # epoch budget for from-scratch trains when
    # warm_start is on (pass 1, or after an
    # architecture change); None -> max_num_epochs
    enable_cueq: bool = False  # cuEquivariance-accelerated training


@dataclass
class LoopConfig:
    max_passes: int = 5
    force_rmse_tol_mev_ang: float = 40.0  # held-out force RMSE plateau target
    density_tol_gcc: float = 0.005  # target-property movement between passes
    min_rel_improvement_force: float = (
        0.0  # data-efficiency early stop: if a pass improves
    )
    # the force RMSE by less than this fraction over
    # the previous pass, more data isn't buying
    # accuracy so stop (0 = disabled)
    # Extra convergence terms, each active only when set (None = legacy behaviour).
    # Anchored to the Schran 2021 score conventions: force >= 86%, RDF >= 98%,
    # VDOS >= 96% mark a "good" water model.
    force_score_converged_pct: float | None = None  # spot-check AML force score gate
    rdf_converged_pct: float | None = None  # RDF(pass p vs p-1) self-convergence gate
    vdos_converged_pct: float | None = None  # VDOS(pass p vs p-1) self-convergence gate
    density_anchor_gcc: float | None = (
        None  # experimental density anchor (0.997 at 300 K)
    )
    density_anchor_tol_gcc: float | None = None
    consecutive_passes: int = 1  # plateau must hold for this many passes in a row
    # Sampler promotion gate: the explorer only switches from the foundation model to a
    # trained model once that model's validation passed these bars (an undertrained model
    # must not explore unsupervised; the pilot collapsed to 0.677 g/cc that way).
    # promote_min_force_pct = 0 disables the gate (legacy: always use the previous model).
    promote_min_force_pct: float = 0.0
    promote_density_window_gcc: list[float] = field(
        default_factory=lambda: [0.87, 1.10]
    )
    # Portable wall-clock bound for the whole campaign loop (scheduler-agnostic "infinite
    # loop" guard on top of max_passes). The driver stops cleanly (mark_stopped) before
    # starting a pass that would exceed it. None = off. Use this instead of any
    # site-specific core-hour accounting.
    max_wall_hours: float | None = None


@dataclass
class ValidateConfig:
    """AML-style accuracy scorecard (Schran et al. 2021) run after each training pass.

    Produces percentage scores for force RMSE, RDF match and VDOS match, plus density,
    for the current model (and, optionally, the previous-iteration model so progress is
    visible pass-to-pass). RDF/VDOS scoring needs a reference trajectory/spectrum; when
    the reference paths are unset the corresponding score is skipped with a note.
    """

    enabled: bool = True
    n_dft_spotcheck: int = 10  # DFT single points on the model's own dynamics
    spotcheck_md_steps: int = (
        2000  # doubles as the stability MD (raise to ~20000 = 10 ps
    )
    # for a meaningful blow-up check in a campaign)
    spotcheck_temperature_k: float = 300.0
    validate_previous_model: bool = True
    # Fixed held-out test set (DFT-labelled extxyz, built once by scripts/make_test_set.py):
    # per-pass spot-check frames change every pass, so cross-pass and cross-ablation-arm
    # comparisons need this constant yardstick. None -> skipped with a note.
    fixed_test_xyz: str | None = None
    # v4 (Schran): incremental validation set — "save the 50 DFT": instead of a big
    # upfront test set, label +testset_increment fresh decorrelated frames per pass
    # from ONE independent foundation trajectory (dedicated velocity-seed lane, never
    # trained on) and append to fixed_test_xyz. Scorecard reports the accumulated-set
    # score AND the newest-increment score (unbiased-on-new-data check).
    testset_mode: str = "fixed"  # "fixed" | "incremental"
    testset_increment: int = 5
    testset_pool_xyz: str | None = None  # decorrelated candidate pool for increments
    # (e.g. <workdir>/test_candidates.xyz)
    # v4 (Schran): observables MD is NVT (CSVR) at the EXPERIMENTAL density, matching
    # the 2021 scoring convention and decoupling structure/spectra scores from the
    # model's own density error. None -> the system cell.
    nvt_cell_abc: list[float] | None = None
    rdf_ref_xyz: str | None = None  # reference trajectory (e.g. revPBE-D3 AIMD) for RDF
    vdos_ref_npy: str | None = (
        None  # reference VDOS as a 2-column (cm^-1, intensity) .npy
    )
    rdf_pairs: list = field(
        default_factory=lambda: [["O", "O"], ["O", "H"], ["H", "H"]]
    )
    rdf_r_max: float = 6.0
    rdf_nbins: int = 120
    vdos_enabled: bool = False  # run the NVE VDOS every pass (also yields the RDF
    # trajectory + an energy-conservation check); off by
    # default because the NVE leg is CPU-noticeable
    vdos_md_steps: int = 20000  # NVE run for the velocity autocorrelation -> VDOS
    vdos_temperature_k: float = 300.0
    vdos_rdf_stride: int = 100  # store a position frame every N NVE steps for the RDF
    # NPT density probe (the convergence/promotion observable). 2000 steps = 1 ps is the
    # legacy smoke value; a campaign needs ~100 ps for a ~0.006 g/cc standard error.
    density_probe_steps: int = 2000
    density_probe_temperature_k: float | None = None  # None -> mid showcase temperature
    # Experimental anchors: reported next to the scores, never gated (classical nuclei at
    # a GGA functional should NOT reproduce experiment exactly). Values are config, not
    # code, so they are visible and revisable: water 300 K density 0.997 g/cc; g_OO first
    # peak ~2.80 A, height ~2.57 (X-ray, Skinner et al. JCP 138, 074506 (2013)).
    density_ref_gcc: float | None = None
    goo_peak_r_ref: float | None = None
    goo_peak_h_ref: float | None = None
    # Stability gate for the spot-check MD: minimum intermolecular O-O and covalent O-H
    # distances that must survive the trajectory (a collapsing model violates these first).
    stability_min_oo_ang: float = 2.0
    stability_min_oh_ang: float = 0.7
    # Published-reference overlay for the figure suite: the target model's literature
    # numbers, drawn on every per-pass plot so progress reads directly against the
    # published baseline. Free-form dict, e.g.
    #   {label: "Schran 2021 C-NNP (n=8), f-h2o", n_train: 299,
    #    force_rmse_mev: {F: 55.8, H: 29.7, O: 56.8},
    #    scores: {force: 90.4, rdf: 98.8, vdos: 97.4}}
    # None -> plot_validation falls back to its legacy water literals.
    published_reference: dict | None = None


@dataclass
class ShowcaseConfig:
    temperatures_k: list[float] = field(
        default_factory=lambda: [250, 260, 270, 277, 285, 295, 310, 320]
    )
    pressure_bar: float = 1.0
    steps: int = 100000
    equilibration_steps: int = 20000
    timestep_fs: float = 0.5
    # The showcase isobar and the density probe are OBSERVABLE-bearing runs: they need a
    # canonical NPT integrator ("mtk"), not Berendsen, or the density fluctuations that
    # define the error bar are suppressed by construction.
    barostat: str = "mtk"


@dataclass
class Config:
    system: SystemConfig
    dft: DFTConfig = field(default_factory=DFTConfig)
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    explore: ExploreConfig = field(default_factory=ExploreConfig)
    subsample: SubsampleConfig = field(default_factory=SubsampleConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    validate_cfg: ValidateConfig = field(default_factory=ValidateConfig)
    showcase: ShowcaseConfig = field(default_factory=ShowcaseConfig)
    workdir: str = "runs/water_tmd"
    # Directory of the YAML this config was loaded from. Relative input paths in the
    # config (seed_xyz, e0s_file, reference data) resolve against it, so a config and
    # the files it names travel together regardless of the caller's cwd.
    config_dir: str | None = None

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve a user-supplied input path from the config.

        Absolute paths pass through. Relative paths anchor at the directory of the
        loaded YAML (falling back to the cwd for an in-memory config).
        """
        p = Path(path)
        if p.is_absolute():
            return p
        base = Path(self.config_dir) if self.config_dir else Path.cwd()
        return (base / p).resolve()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        import yaml  # lazy — keeps non-config modules import-light

        raw = yaml.safe_load(Path(path).read_text())
        if not isinstance(raw, dict) or "system" not in raw:
            raise ValueError(
                f"{path}: config must be a mapping with a 'system' section"
            )

        def build(dc_type, section: dict[str, Any]):
            known = {f.name for f in dataclasses.fields(dc_type)}
            unknown = set(section) - known
            if unknown:
                raise ValueError(f"{dc_type.__name__}: unknown keys {sorted(unknown)}")
            return dc_type(**section)

        cfg = cls(
            system=build(SystemConfig, raw["system"]),
            dft=build(DFTConfig, raw.get("dft", {})),
            generator=build(GeneratorConfig, raw.get("generator", {})),
            explore=build(ExploreConfig, raw.get("explore", {})),
            subsample=build(SubsampleConfig, raw.get("subsample", {})),
            train=build(TrainConfig, raw.get("train", {})),
            loop=build(LoopConfig, raw.get("loop", {})),
            validate_cfg=build(ValidateConfig, raw.get("validate", {})),
            showcase=build(ShowcaseConfig, raw.get("showcase", {})),
            workdir=raw.get("workdir", "runs/water_tmd"),
            config_dir=str(Path(path).resolve().parent),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        import math

        # Normalise device aliases: docs/users write "gpu" but torch/MACE need "cuda"
        # (passing "gpu" gives: "don't know how to restore data location ... tagged with gpu").
        for owner in (self.generator, self.train):
            if str(owner.device).lower() == "gpu":
                owner.device = "cuda"
        if len(self.system.cell_abc) != 3:
            raise ValueError(
                "system.cell_abc must have three entries (orthorhombic box)"
            )
        if not self.explore.temperatures_k:
            raise ValueError("explore.temperatures_k must be non-empty")
        if self.subsample.n_per_pass < self.subsample.min_frames:
            raise ValueError("subsample.n_per_pass must be >= subsample.min_frames")
        if (
            self.subsample.n_first_pass is not None
            and self.subsample.n_first_pass < self.subsample.min_frames
        ):
            raise ValueError("subsample.n_first_pass must be >= subsample.min_frames")
        if self.explore.ensemble.upper() not in ("NVT", "NPT"):
            raise ValueError("explore.ensemble must be 'NVT' or 'NPT'")
        if self.explore.sample_mode not in ("decorrelation", "fixed"):
            raise ValueError("explore.sample_mode must be 'decorrelation' or 'fixed'")
        if self.explore.on_undersample not in ("warn", "fail"):
            raise ValueError("explore.on_undersample must be 'warn' or 'fail'")
        if self.explore.n_replicas < 1:
            raise ValueError("explore.n_replicas must be >= 1")
        for owner, name in ((self.explore, "explore"), (self.showcase, "showcase")):
            if owner.barostat not in ("berendsen", "mtk"):
                raise ValueError(f"{name}.barostat must be 'berendsen' or 'mtk'")
        if self.explore.nvt_thermostat not in ("langevin", "bussi"):
            raise ValueError("explore.nvt_thermostat must be 'langevin' or 'bussi'")
        if self.subsample.method not in ("fps", "direct", "random", "none"):
            raise ValueError(
                "subsample.method must be 'fps', 'direct', 'random' or 'none'"
            )
        if self.dft.backend not in ("cp2k", "mock_foundation"):
            raise ValueError("dft.backend must be 'cp2k' or 'mock_foundation'")
        if self.dft.mode not in ("gga", "hybrid"):
            raise ValueError("dft.mode must be 'gga' or 'hybrid'")
        if self.dft.mode == "hybrid":
            # Truncated-Coulomb legality: the HFX cutoff radius must fit inside the
            # minimum image of every cell that will ever be labelled. Two checks:
            # (1) the seed cell here; (2) a per-frame hard error in cp2k_io for the
            # NPT-explored candidates, whose cells shrink under compression.
            half_min_cell = min(self.system.cell_abc) / 2.0
            if self.dft.hfx_cutoff_radius_ang >= half_min_cell:
                raise ValueError(
                    f"dft.hfx_cutoff_radius_ang={self.dft.hfx_cutoff_radius_ang} must "
                    f"be < min(system.cell_abc)/2 = {half_min_cell:.3f} A "
                    "(truncated Coulomb)"
                )
            if not (0.0 < self.dft.hf_fraction <= 1.0):
                raise ValueError("dft.hf_fraction must be in (0, 1]")
            # Couple the explorer's density ceiling to HFX legality: at density_max the
            # cubic cell shrinks to L_seed * (rho_seed/rho_max)^(1/3); frames beyond
            # 2*radius are unlabelable at this level of theory.
            ex = self.explore
            if ex.ensemble.upper() == "NPT" and ex.density_max_gcc:
                # Seed density ~1 g/cc assumed (aqueous systems); at density_max the
                # cell edge is l_seed / density_max^(1/3). Margin 0.2 A.
                l_seed = min(self.system.cell_abc)
                l_at_max = l_seed / ex.density_max_gcc ** (1.0 / 3.0)
                if l_at_max <= 2.0 * self.dft.hfx_cutoff_radius_ang + 0.2:
                    raise ValueError(
                        f"explore.density_max_gcc={ex.density_max_gcc} lets NPT cells "
                        f"shrink to ~{l_at_max:.2f} A < 2 x hfx_cutoff_radius + margin "
                        f"({2 * self.dft.hfx_cutoff_radius_ang + 0.2:.2f} A): such "
                        "frames cannot be labelled with this truncated-Coulomb radius. "
                        "Lower density_max_gcc or hfx_cutoff_radius_ang."
                    )
        if self.generator.engine not in ("ase", "cp2k-backend", "symmetrix"):
            raise ValueError(
                "generator.engine must be 'ase' (default) or 'cp2k-backend' (needs the MACE "
                f"backend build); got {self.generator.engine!r}"
            )
        if self.train.e0s_mode not in ("average", "isolated", "file"):
            raise ValueError("train.e0s_mode must be 'average', 'isolated' or 'file'")
        if self.train.e0s_mode == "file" and not self.train.e0s_file:
            raise ValueError("train.e0s_mode='file' requires train.e0s_file")
        if len(self.loop.promote_density_window_gcc) != 2:
            raise ValueError("loop.promote_density_window_gcc must be [lo, hi]")
        if not self.generator.dispersion:
            # Not fatal for non-water systems, but flag the water foot-gun loudly.
            print(
                "WARNING: generator.dispersion is off — for water this evaporates the liquid."
            )

        # Static sampling-feasibility check: can a cell even yield target_uncorrelated
        # frames at the decorrelation floor? Computed, never hardcoded. This is the
        # optimistic bound (a measured tau > floor/2 shortens the yield further; the
        # runtime shortfall check in generate covers that case).
        ex = self.explore
        if ex.sample_mode == "decorrelation":
            frame_dt_fs = ex.timestep_fs * ex.sample_every
            interval_frames_floor = max(
                1, math.ceil(ex.min_sample_every_fs / frame_dt_fs)
            )
            steps_required = ex.equilibration_steps + ex.sample_every * (
                1 + (ex.target_uncorrelated - 1) * interval_frames_floor
            )
            if ex.steps < steps_required:
                msg = (
                    f"explore.steps={ex.steps} cannot yield "
                    f"target_uncorrelated={ex.target_uncorrelated} frames/cell at the "
                    f"{ex.min_sample_every_fs:.0f} fs floor: needs >= {steps_required} "
                    f"steps ({ex.equilibration_steps} equilibration + "
                    f"{ex.target_uncorrelated} frames spaced "
                    f"{interval_frames_floor * frame_dt_fs:.0f} fs)"
                )
                if ex.on_undersample == "fail":
                    raise ValueError(msg)
                print(f"WARNING: {msg}")
