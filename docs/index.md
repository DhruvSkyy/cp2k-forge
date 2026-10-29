---
hide-toc: true
---

```{toctree}
:hidden:
:caption: Getting started

getting-started/installation
getting-started/quickstart
getting-started/cp2k-dependency
```

```{toctree}
:hidden:
:caption: User guide

guide/how-it-works
guide/configuration
guide/hybrid-dft
guide/campaigns-hpc
guide/validation
guide/showcase-density
guide/troubleshooting
```

```{toctree}
:hidden:
:caption: Results

case-studies/index
case-studies/water
case-studies/fluoride
case-studies/cost
```

```{toctree}
:hidden:
:caption: Reference

reference/cli
reference/api
reference/templates
```

```{toctree}
:hidden:
:caption: About

about/method
about/provenance
GitHub <https://github.com/DhruvSkyy/cp2k-forge>
```

# CP2K-FORGE

<p class="lede">Build a small, fast MACE potential for <em>your</em> system, trained only on CP2K DFT labels.</p>

<p class="expansion">Foundation-model Optimisation of Reference Generation and Evaluation in CP2K</p>

<nav class="hero-actions" aria-label="Start here">
  <a class="primary" href="getting-started/quickstart/">Get started</a>
  <a href="guide/how-it-works/">How it works</a>
  <a href="case-studies/">Results</a>
</nav>

<p class="project-meta">
  <span>Python 3.9+</span>
  <a href="about/license/">MIT licence</a>
  <span>CP2K is a runtime dependency, never linked</span>
  <a href="about/changelog/">Changelog</a>
  <a href="https://github.com/DhruvSkyy/cp2k-forge">GitHub</a>
</p>

## What it does

You write one YAML file describing your system. CP2K-FORGE then:

<ul class="key-points">
  <li><strong>Samples structures with a foundation model.</strong> A general model such as MACE-MP-0 runs short MD to propose realistic configurations. Its energies and forces are thrown away.</li>
  <li><strong>Labels them with CP2K.</strong> Every kept structure gets a DFT single point (semi-local GGA, or hybrid revPBE0-D3). These labels are the only training data.</li>
  <li><strong>Trains a compact MACE from scratch.</strong> No weights are inherited, so the model's physics is exactly the DFT level you chose.</li>
</ul>

A campaign, trimmed from `configs/water_hybrid.yaml`:

```yaml
system:
  seed_xyz: ../examples/water64.xyz
  elements: [H, O]
  cell_abc: [12.4313, 12.4313, 12.4313]
dft:
  mode: hybrid              # revPBE0-D3 under ADMM
  functional: revPBE
generator:
  model: mace-mp-0          # the sampler; its labels are discarded
  dispersion: true          # D3, needed for liquid water
explore:
  temperatures_k: [300]
subsample:
  method: random
  n_per_pass: 10            # DFT labels added per pass
train:
  num_channels: 96          # compact by design
loop:
  max_passes: 15
  min_rel_improvement_force: 0.05   # stop when a pass improves < 5%
```

Every key is documented in the [configuration reference](guide/configuration.md). (The thesis water campaign sampled with MACE-OFF23 medium; the shipped config uses MACE-MP-0 with D3. Only the sampler differs; the labels are the same CP2K level.)

This is not distillation, not fine-tuning and not query-by-committee. The loop repeats until a stop rule set in the config says more labels no longer help, or the pass budget runs out.

## The loop

<ol class="method-sequence">
  <li><span>1</span><div><h3>Sample</h3><p>Short MD across your state points. Pass 1 uses the foundation model; later passes use the latest compact model, or, with the promotion gate on, the latest one that passed it.</p></div></li>
  <li><span>2</span><div><h3>Select</h3><p>Thin trajectories by autocorrelation time and pick a small batch.</p></div></li>
  <li><span>3</span><div><h3>Label</h3><p>Run independent CP2K single points, in parallel.</p></div></li>
  <li><span>4</span><div><h3>Train</h3><p>Fit the compact MACE and export it for CP2K.</p></div></li>
  <li><span>5</span><div><h3>Validate</h3><p>Score held-out forces and run short MD on the candidate's own forces; the stop rule then decides whether to continue.</p></div></li>
</ol>

State is saved after every stage, so labelling (CPU) and training (GPU) can run as separate jobs, and a killed campaign resumes without recomputing anything.

## Results

Tested on bulk water and on fluoride in water, both labelled at hybrid revPBE0-D3 and compared with a published committee potential at the same level of theory. Both campaigns stopped by a convergence rule fixed before use (a paired-bootstrap test on held-out force error), not by the compute budget. That rule was applied with the thesis analysis scripts; see [Validation and gates](guide/validation.md) for what v0.1.0 implements.

<div class="table-scroll">
<table class="academic-results">
  <thead><tr><th>System and measure</th><th>CP2K-FORGE</th><th>Committee</th></tr></thead>
  <tbody>
    <tr class="table-section"><th colspan="3">Bulk water</th></tr>
    <tr><td>Training labels</td><td>89</td><td>814</td></tr>
    <tr><td>Force RMSE, 55 shared frames</td><td>53.3 meV/Å</td><td>64.6 meV/Å</td></tr>
    <tr><td>RDF overlap with 298 K experiment</td><td>95.6%</td><td>95.6%</td></tr>
    <tr class="table-section"><th colspan="3">Fluoride in water</th></tr>
    <tr><td>Training labels</td><td>64</td><td>299</td></tr>
    <tr><td>Force RMSE, 37 shared frames</td><td>57.7 meV/Å</td><td>69.4 meV/Å</td></tr>
    <tr><td>RDF / VDOS overlap with AIMD</td><td>97.2 / 98.7%</td><td>97.7 / 97.7%<sup>*</sup></td></tr>
  </tbody>
</table>
</div>
<p class="table-caption">Force errors compare both models on the same held-out frames. <sup>*</sup>Committee's 11 ps run, length-matched to this work's 10 ps run.</p>

A low force error alone is not enough. In the water campaign, early candidates fitted forces well and then collapsed in MD driven by their own forces:

```{figure} assets/figures/fig_water_stability.png
:alt: Minimum oxygen-oxygen distance in a 10 ps own-MD screen for water models trained on 10 to 89 labels; models below 40 labels collapse below 1 angstrom, later models stay near 2.5 angstrom

Minimum O-O approach in one 10 ps own-MD screen per water model (thesis Fig. 9.6). Models below 40 labels collapse into unphysical contact despite good force scores.
```

That is why every candidate also gets a stability run driven by its own forces, and why the promotion gate refuses to let an unstable model sample. Details: [Validation and gates](guide/validation.md).

**Not yet shown:** two systems do not establish general transferability. Density at the hybrid level and a species-weighted convergence rule for fluoride are still to be tested, and only one selector (random) was used.

## Try it in two minutes

No CP2K or GPU needed. The smoke config replaces DFT with mock labels to exercise the full loop:

```bash
git clone https://github.com/DhruvSkyy/cp2k-forge.git
cd cp2k-forge
python -m pip install -U pip
pip install -e ".[train]"
cp2k-forge --check
cp2k-forge --config configs/smoke.yaml
```

For a real campaign, continue with [Installation](getting-started/installation.md), [CP2K as a dependency](getting-started/cp2k-dependency.md) and [Campaigns on HPC](guide/campaigns-hpc.md).

## Citation

Developed by Dhruv Sharma for the MPhil in Scientific Computing, University of Cambridge (2026). The method, validation protocol, results and limitations are in the thesis *Machine-Learned Interatomic Potentials in CP2K* (CP2K-FORGE is Chapters 8.3 and 9.3). See [Provenance and citation](about/provenance.md).
