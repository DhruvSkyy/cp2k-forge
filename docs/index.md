---
hide-toc: true
---

```{toctree}
:hidden:
:caption: Getting started

getting-started/installation
getting-started/quickstart
getting-started/your-system
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

<div class="hero">
<p class="lede">Train a small, fast MACE potential for your own system, using only CP2K DFT labels.</p>
<p class="hero-sub">You describe the system in one YAML file. A foundation model proposes structures, CP2K labels a few of them, and a compact MACE is trained from scratch on those labels. The loop repeats until extra labels stop helping.</p>
<nav class="hero-actions" aria-label="Start here">
  <a class="primary" href="getting-started/quickstart/">Get started</a>
  <a href="getting-started/your-system/">Use it on your system</a>
  <a href="case-studies/">Results</a>
</nav>
<dl class="hero-needs">
  <div><dt>CP2K</dt><dd>any recent binary, run as a subprocess</dd></div>
  <div><dt>A seed structure</dt><dd>extended XYZ in an orthorhombic cell</dd></div>
  <div><dt>One YAML file</dt><dd>system, DFT level, sampler and stop rule</dd></div>
</dl>
<p class="project-meta">
  <span>Python 3.9+</span>
  <a href="about/license/">MIT licence</a>
  <a href="about/changelog/">Changelog</a>
  <a href="https://github.com/DhruvSkyy/cp2k-forge">GitHub</a>
</p>
<p class="expansion">FORGE: Foundation-model Optimisation of Reference Generation and Evaluation in CP2K.</p>
</div>

## Why this approach

Foundation models run on almost anything, but they are large, slow and trained on
someone else's level of theory. A potential fitted to your own DFT is faster and matches
the level of theory you chose, but it usually needs a long ab initio trajectory to
supply the training structures.

CP2K-FORGE uses the foundation model only to generate structures. Its energies and
forces are discarded. Every training label is a CP2K single point at your chosen level,
and the final model starts from random weights, so it inherits nothing from the sampler.
No ab initio MD is needed.

## How a campaign runs

<ol class="method-sequence">
  <li><span>1</span><div><h3>Sample</h3><p>Short MD over your state points. Pass 1 uses the foundation model; later passes use the latest compact model.</p></div></li>
  <li><span>2</span><div><h3>Select</h3><p>Thin the trajectories by autocorrelation time and pick a small batch, typically ten frames.</p></div></li>
  <li><span>3</span><div><h3>Label</h3><p>Run a CP2K single point on each frame. The points are independent, so they run in parallel.</p></div></li>
  <li><span>4</span><div><h3>Train</h3><p>Fit a compact MACE on all labels so far and export it.</p></div></li>
  <li><span>5</span><div><h3>Validate</h3><p>Score held-out forces and run short MD on the model's own forces. The stop rule then decides whether to run another pass.</p></div></li>
</ol>

Progress is saved after every stage. A killed job resumes where it stopped, and the CPU
labelling and GPU training can run as separate jobs. Details: [How it works](guide/how-it-works.md).

## A config

This is the core of `configs/water_hybrid.yaml`. For another system you change the
`system` and `dft` blocks and a few water-tuned defaults, listed in
[Use it on your system](getting-started/your-system.md).

```yaml
system:
  seed_xyz: ../examples/water64.xyz
  elements: [H, O]
  cell_abc: [12.4313, 12.4313, 12.4313]
dft:
  mode: hybrid              # revPBE0-D3 with ADMM; "gga" is ~13x cheaper
  functional: revPBE
generator:
  model: mace-mp-0          # sampler only
  dispersion: true
subsample:
  method: random
  n_per_pass: 10            # labels added per pass
train:
  num_channels: 96          # small on purpose
loop:
  max_passes: 15
  min_rel_improvement_force: 0.05   # stop when a pass gains < 5%
```

## Try it without CP2K

The smoke config swaps DFT for mock labels so you can check the install in about two
minutes, with no CP2K and no GPU:

```bash
git clone https://github.com/DhruvSkyy/cp2k-forge.git
cd cp2k-forge
python -m pip install -U pip
pip install -e ".[train]"
cp2k-forge --check
cp2k-forge --config configs/smoke.yaml
```

Mock labels test the plumbing only. For a real campaign, see
[Installation](getting-started/installation.md) and
[CP2K as a dependency](getting-started/cp2k-dependency.md).

## Does it work?

The method was tested on two aqueous systems, labelled at hybrid revPBE0-D3 and compared
with a published committee potential at the same level of theory.

<div class="table-scroll">
<table class="academic-results">
  <thead><tr><th>Measure</th><th>CP2K-FORGE</th><th>Committee</th></tr></thead>
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
<p class="table-caption">Both models are scored on the same held-out frames. <sup>*</sup>Committee 11 ps run, length-matched to this work's 10 ps run.</p>

Force error alone did not pick good models. Early water models fitted forces well and
then collapsed in their own MD:

```{figure} assets/figures/fig_water_stability.png
:alt: Minimum oxygen-oxygen distance in a 10 ps own-MD screen for water models trained on 10 to 89 labels; models below 40 labels collapse below 1 angstrom, later models stay near 2.5 angstrom

Closest O-O approach in a 10 ps MD run driven by each water model. Models trained on
fewer than 40 labels collapse despite good force scores.
```

This is why every candidate gets a stability run. Two aqueous systems do not prove the
method transfers everywhere, so validate your own system against data you trust. Full
numbers and limitations: [Results](case-studies/index.md).

## Citation

CP2K-FORGE was developed by Dhruv Sharma for the MPhil in Scientific Computing at the
University of Cambridge (2026). The method and the results above are in the thesis
*Machine-Learned Interatomic Potentials in CP2K*. See
[Provenance and citation](about/provenance.md).
