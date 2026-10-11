# Provenance and citation

## Where this code comes from

CP2K-FORGE was developed as part of an MPhil project at the University of Cambridge and
extracted into this standalone repository from the author's CP2K development fork
(`cp2k-mlp`, branch `mace-distill-pipeline`, which stays frozen as report provenance).
The accompanying report is

> Dhruv Sharma, *Machine-Learned Interatomic Potentials in CP2K with GPU Acceleration,
> MACE Integration and CP2K-FORGE for Domain-Specific Models*, MPhil report, University
> of Cambridge, 2026.

The [case studies](../case-studies/index.md) reproduce that report's Chapter 4 FORGE
results; the figures and raw data under `docs/assets/` are vendored verbatim from the
report's data package (*Report 2 data package*, v1.1, 2026-08-13, CC BY 4.0) — see the
[provenance manifest](../assets/README.md) for the file-by-file mapping.

## How to cite

`CITATION.cff` at the repository root carries the machine-readable citation (GitHub's
"Cite this repository" button uses it).

## The released model

The v0.1.0 release ships one trained model as an asset:

**`water64_pass6_stagetwo.model`** — a compact water MACE (96 channels, L = 2,
r_max = 5.0 Å, ZBL pair repulsion, float64), the final model of the **semi-local
revPBE-D3** `water64_tmd` campaign: pass 6, 70 labels, held-out force RMSE
59.46 meV/Å on that campaign's frozen 50-frame set (force score 91.9%, RDF/VDOS
self-convergence 98.9/98.8, flash density probe 0.97 g/cm³).

Honest caveats, so the asset is never over-read:

- it was **accepted by user decision at pass 6** (a GPU-budget call), not by the
  automated convergence rule;
- it is **not** the report's headline model — the headline campaigns are hybrid
  revPBE0-D3 and their weights ship with the report data package;
- density/TMD language for anything run with it follows the
  [claim constraints](../guide/showcase-density.md).

Load it with `mace.calculators.MACECalculator(model_paths=..., device=...)`.

SHA-256:

```text
11501d1fe7c0f17d9af2a787fbaf430f78f9f9bec1047061d818d402219abf7e
```

## Licensing

- Code: [MIT](license.md).
- Vendored documentation assets (`docs/assets/`): CC BY 4.0, © 2026 Dhruv Sharma.
