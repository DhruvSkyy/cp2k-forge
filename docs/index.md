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
:caption: Case studies

case-studies/index
case-studies/water
case-studies/fluoride
case-studies/cost
```

```{toctree}
:hidden:
:caption: Reference

reference/cli
reference/api/pipeline
reference/api/config-io
reference/api/environment
reference/templates
```

```{toctree}
:hidden:
:caption: About

about/method
about/provenance
about/changelog
about/license
GitHub <https://github.com/DhruvSkyy/cp2k-forge>
```

# CP2K-FORGE

<p class="lede">Build a small, fast MACE potential for <em>your</em> system, trained only on CP2K DFT labels.</p>

<p class="expansion">Foundation-model Optimisation of Reference Generation and Evaluation in CP2K</p>

<nav class="hero-actions" aria-label="Start here">
  <a class="primary" href="getting-started/quickstart/">Get started</a>
  <a href="guide/how-it-works/">How it works</a>
  <a href="case-studies/">See the results</a>
</nav>

<p class="project-meta">
  <span>Python 3.9+</span>
  <span>MIT licence</span>
  <span>CP2K is a runtime dependency, never linked</span>
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

Every key is documented in the [configuration reference](guide/configuration.md).

This is not distillation, not fine-tuning and not query-by-committee. The loop repeats until a convergence rule, fixed before the campaign starts, says more labels no longer help.

## The loop

<ol class="method-sequence">
  <li><span>1</span><div><h3>Sample</h3><p>Short MD across your state points. Pass 1 uses the foundation model; later passes use the latest accepted compact model.</p></div></li>
  <li><span>2</span><div><h3>Select</h3><p>Drop time-correlated frames and pick a small batch.</p></div></li>
  <li><span>3</span><div><h3>Label</h3><p>Run independent CP2K single points, in parallel.</p></div></li>
  <li><span>4</span><div><h3>Train</h3><p>Fit the compact MACE and export it for CP2K.</p></div></li>
  <li><span>5</span><div><h3>Validate</h3><p>Accept the model only if forces improve <em>and</em> its own MD stays stable.</p></div></li>
</ol>

State is saved after every stage, so labelling (CPU) and training (GPU) can run as separate jobs, and a killed campaign resumes without recomputing anything.

## Results

Tested on bulk water and on fluoride in water, both labelled at hybrid revPBE0-D3 and compared with a published committee potential at the same level of theory. Both campaigns were stopped by the pre-registered convergence rule, not by the compute budget.

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

```{figure} assets/figures/fig_forge_cost_curve.png
:alt: Held-out force RMSE falling as cumulative build cost grows, for the water and fluoride campaigns
:class: figure-narrow

Held-out force error against cumulative build cost. Error bars are bootstrap uncertainties.
```

A low force error alone is not enough. In the water campaign some candidates fitted forces well and then fell apart in MD. That is why a model is only accepted after it also passes a short-range (compressed dimer) check and a stability run driven by its own forces. Details: [Validation and gates](guide/validation.md).

**Not yet shown:** two systems do not establish general transferability. Density at the hybrid level and a species-weighted convergence rule for fluoride are still to be tested.

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

Developed by Dhruv Sharma for the MPhil in Scientific Computing, University of Cambridge (2026). The method, validation protocol, results and limitations are in the thesis *Machine-Learned Interatomic Potentials in CP2K with GPU Acceleration, MACE Integration and CP2K-FORGE for Domain-Specific Models*. See [Provenance and citation](about/provenance.md).
