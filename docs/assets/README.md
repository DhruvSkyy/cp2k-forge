# Vendored report assets

Figures and raw data behind the documentation's case studies, vendored verbatim from
the Report 2 data package ("Report 2 data package: Machine-Learned Interatomic
Potentials in CP2K", v1.1, 2026-08-13) and its rendered figures. They are **never
regenerated here** — the package's `scripts/` directory holds the generators, and every
CSV row carries a `source` column pointing at the raw run directory it came from.

**License:** figures and data © 2026 Dhruv Sharma, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (the licence the original
data package carries). The code in this repository is MIT; the CC BY 4.0 terms apply only to
the files under `docs/assets/`.

| File | Source in the data package | Feeds |
| --- | --- | --- |
| `figures/fig_water_convergence.png` | `figures_rendered/ch4/` | Water case study: force RMSE vs cumulative labels (ambient campaign, frozen 50-frame set) |
| `figures/fig_water_stability.png` | `figures_rendered/ch4/` | Water case study: own-MD minimum O–O approach per model (the stability gate) |
| `figures/fig_water_rdf.png` | `figures_rendered/ch4/` | Water case study: O–O/O–H/H–H RDFs vs committee and experiment |
| `figures/fig_water_ambient_audit.png` | `figures_rendered/ch4/` | Water case study: second-ruler audit of the v2 campaign |
| `figures/fig_fluoride_learning.png` | `figures_rendered/ch4/` | Fluoride case study: per-pass force RMSE vs labels |
| `figures/fig_fluoride_structure.png` | `figures_rendered/ch4/` | Fluoride case study: g_FO/g_FH/g_OO + hydrogen VDOS vs AIMD and committee |
| `figures/fig_cost_ledger.png` | `figures_rendered/ch4/` | Cost page: labels vs committee labels vs parent-AIMD steps |
| `figures/fig_forge_cost_curve.png` | draft figure kept with the package scripts | Cost page: accuracy vs cumulative core-hour-equivalents (orphaned draft — water series covers passes 1–3 only; fluoride complete) |
| `figures/fig_scorecard.png` | draft figure kept with the package scripts | Cost page: Schran-style score bars (orphaned draft, kept for talks) |
| `figures/fig_water_density_isobar.png` | `figures_rendered/appendix/` | Density page: equilibrium density vs temperature, own-DFT reference band only |
| `figures/fig_systems.png` | `figures_rendered/ch4/` | Case-studies index: the two simulation cells |
| `figures/fig_gpu_isocost.png` | `figures_rendered/ch4/` | Provenance "Why this exists": GPU HDNNP iso-cost throughput (H2O-16384, 1-4 A100s vs CPU core-equivalents) |
| `figures/fig_mace_steptime.png` | `figures_rendered/ch4/` | Provenance "Why this exists": MACE backend step time, metatomic vs Symmetrix, GPU and CPU panels |
| `data/water/water_learning_curve.csv` | `data/aggregated/hybrid/water_ambient/` | Water learning curve (deployed / invalid / cold-curve roles) |
| `data/water/water_stability.csv` | `data/aggregated/hybrid/water_ambient/` | Water stability screens (min O–O per model) |
| `data/water/water_ambient_audit.csv` | `data/aggregated/hybrid/water/` | v2-campaign audit on the pre-registered ambient ruler |
| `data/water/curve_overlap.csv` | `data/aggregated/hybrid/water/` | RDF overlap vs labels |
| `data/water/committee_gOO.csv` | `data/aggregated/hybrid/water/` | Committee reference g_OO |
| `data/fluoride/convergence.json` | `data/aggregated/hybrid/fluoride/` | Fluoride paired-bootstrap convergence record |
| `data/fluoride/gates_by_pass.json` | `data/aggregated/hybrid/fluoride/` | Per-pass gate outcomes |
| `data/fluoride/species_by_pass.json` | `data/aggregated/hybrid/fluoride/` | Per-species force RMSE by pass |
| `data/fluoride/coordination_scores.json` | `data/aggregated/hybrid/fluoride/` | F coordination numbers vs AIMD/committee |
| `data/cost/forge_cost_curve.csv` | `data/aggregated/` | Accuracy-vs-cost curve (see caveat above) |
| `data/cost/mace_steptime_data.csv` | `data/aggregated/` | Backend step-time measurements (feeds `fig_mace_steptime.png`) |
| `data/cost/backends_table_data.csv` | `data/aggregated/` | Backend comparison table data |
| `data/cost/gpu_isocost_data.csv` | `data/aggregated/` | GPU/CPU iso-cost throughput measurements (feeds `fig_gpu_isocost.png`) |
| `data/density/results_rho_t.csv` | `data/aggregated/rhoT/` | All 49 barostat-free NVT P(rho)=0 crossings |
| `data/density/tmd.json` | `data/aggregated/rhoT/` | Density-maximum fit record — its verdict field is the authority on what may be claimed (UNRESOLVED) |
