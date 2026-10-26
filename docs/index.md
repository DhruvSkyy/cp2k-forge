<div class="home-hero">
  <div class="home-hero__copy">
    <div class="eyebrow"><span class="eyebrow__dot"></span> DFT-labelled · dynamics-checked · ready for CP2K</div>
    <h1>Build a small MACE model.<br><span>Make it earn deployment.</span></h1>
    <p class="home-hero__lede">CP2K-FORGE turns selected CP2K calculations into a compact, system-specific potential. Every candidate is checked on held-out forces, short-range behaviour and its own molecular dynamics before it is accepted.</p>
    <div class="home-actions">
      <a class="button button--primary" href="getting-started/quickstart/">Run the two-minute self-test <span aria-hidden="true">→</span></a>
      <a class="button button--quiet" href="case-studies/">See the evidence</a>
    </div>
    <div class="install-line" aria-label="Install command">
      <span class="install-line__prompt">$</span>
      <code>pip install cp2k-forge</code>
      <button type="button" data-copy="pip install cp2k-forge" aria-label="Copy install command">Copy</button>
    </div>
  </div>
  <div class="home-hero__visual" aria-label="The CP2K-FORGE validation loop">
    <div class="model-card model-card--candidate">
      <span class="model-card__label">candidate · pass 14</span>
      <span class="model-card__score">51.8</span>
      <span class="model-card__unit">meV Å<sup>−1</sup> · force RMSE</span>
    </div>
    <div class="gate-stack">
      <div class="gate"><span>01</span><p>held-out forces</p><i>pass</i></div>
      <div class="gate"><span>02</span><p>dimer compression</p><i>pass</i></div>
      <div class="gate"><span>03</span><p>own-MD stability</p><i>pass</i></div>
    </div>
    <div class="model-card model-card--accepted">
      <span class="accepted-check">✓</span>
      <div><span class="model-card__label">accepted model</span><strong>89 DFT labels</strong></div>
    </div>
    <svg class="hero-orbit" viewBox="0 0 520 520" aria-hidden="true">
      <circle cx="260" cy="260" r="206" />
      <circle cx="260" cy="54" r="6" class="hero-orbit__atom" />
      <circle cx="466" cy="260" r="4" class="hero-orbit__atom hero-orbit__atom--small" />
    </svg>
  </div>
</div>

<div class="proof-strip" aria-label="Reported outcomes">
  <div><span>Water</span><strong>89</strong><p>hybrid-DFT labels</p></div>
  <div><span>Fluoride</span><strong>64</strong><p>hybrid-DFT labels</p></div>
  <div><span>Water force RMSE</span><strong>53.3</strong><p>meV Å<sup>−1</sup> on shared frames</p></div>
  <div><span>Fluoride force RMSE</span><strong>57.7</strong><p>meV Å<sup>−1</sup> on shared frames</p></div>
</div>

<section class="home-section home-intro">
  <div class="section-kicker">Purpose</div>
  <div class="section-copy">
    <h2>Spend DFT where it changes the model.</h2>
    <p>A foundation model explores configuration space, but it never supplies a training energy or force. CP2K labels a small selection of frames at the target level of theory. A compact MACE then learns from those labels alone.</p>
    <p>This distinction matters. CP2K-FORGE is not distillation and it does not fine-tune inherited weights. The foundation model proposes where the expensive calculation should be spent; CP2K remains the source of the physics.</p>
  </div>
</section>

<section class="pipeline-panel">
  <div class="pipeline-panel__heading">
    <div>
      <span class="section-kicker">One recorded loop</span>
      <h2>From candidate structures to an accepted model</h2>
    </div>
    <a href="guide/how-it-works/">Read the method <span aria-hidden="true">→</span></a>
  </div>
  <div class="pipeline-flow">
    <article><span>01</span><h3>Sample</h3><p>Explore state points with a foundation model, then switch to the promoted compact model.</p></article>
    <article><span>02</span><h3>Select</h3><p>Thin correlated trajectories and choose a small batch of distinct configurations.</p></article>
    <article><span>03</span><h3>Label</h3><p>Run independent CP2K Quickstep single points at the chosen DFT level.</p></article>
    <article><span>04</span><h3>Train</h3><p>Fit the same compact MACE recipe to the accumulated target-level labels.</p></article>
    <article><span>05</span><h3>Verify</h3><p>Promote only after the force, dimer and live-dynamics checks pass.</p></article>
  </div>
  <div class="pipeline-note"><span>No parent AIMD trajectory</span><p>Every DFT call becomes a training or validation label, and independent labels can fan out across CPU nodes.</p></div>
</section>

<section class="home-section gates-section">
  <div class="section-kicker">Why verification matters</div>
  <div class="section-copy">
    <h2>A low force error can still hide a bad model.</h2>
    <p>In the water campaign, some warm-started candidates fitted the held-out forces well and then collapsed in dynamics. CP2K-FORGE therefore treats force accuracy as an entry condition, not as proof that a model is safe to deploy.</p>
    <div class="gate-grid">
      <article><span class="gate-icon">ΔF</span><h3>Force improvement</h3><p>The candidate must improve on a frozen held-out set. Two small consecutive gains trigger the pre-set convergence rule.</p></article>
      <article><span class="gate-icon">r</span><h3>Short-range physics</h3><p>A compressed dimer curve screens for unphysical attraction before a candidate enters dynamics.</p></article>
      <article><span class="gate-icon">t</span><h3>Live stability</h3><p>The candidate must drive its own short CP2K trajectory without collapse. Failed models are never promoted.</p></article>
    </div>
  </div>
</section>

<section class="evidence-panel">
  <div class="evidence-panel__copy">
    <span class="section-kicker">Results from the MPhil study</span>
    <h2>Fewer labels, with the comparison kept honest.</h2>
    <p>Both campaigns stopped through the same pre-registered plateau rule, not because the compute budget ran out. The comparison below is limited to the shared ambient target. The published committee models cover a broader range of conditions.</p>
    <a class="text-link" href="case-studies/cost/">Open the cost and data audit <span aria-hidden="true">→</span></a>
  </div>
  <div class="results-table" role="table" aria-label="CP2K-FORGE results compared with published committee models">
    <div class="results-table__head" role="row"><span role="columnheader">Measure</span><span role="columnheader">FORGE</span><span role="columnheader">Committee</span></div>
    <div class="results-table__group">Bulk water · hybrid revPBE0-D3</div>
    <div role="row"><span role="cell">Training labels</span><strong role="cell">89</strong><span role="cell">814</span></div>
    <div role="row"><span role="cell">Force RMSE</span><strong role="cell">53.3</strong><span role="cell">64.6</span></div>
    <div role="row"><span role="cell">RDF overlap with experiment</span><strong role="cell">95.6%</strong><span role="cell">95.6%</span></div>
    <div class="results-table__group">Fluoride in water · hybrid revPBE0-D3</div>
    <div role="row"><span role="cell">Training labels</span><strong role="cell">64</strong><span role="cell">299</span></div>
    <div role="row"><span role="cell">Force RMSE</span><strong role="cell">57.7</strong><span role="cell">69.4</span></div>
    <div role="row"><span role="cell">RDF / VDOS overlap with AIMD</span><strong role="cell">97.2 / 98.7%</strong><span role="cell">97.7 / 97.7%</span></div>
  </div>
  <p class="table-note">Force RMSE is measured on the same held-out frames for each pair of models. Values are in meV Å<sup>−1</sup>. See the case studies for protocols, uncertainties and limitations.</p>
</section>

<section class="figure-story">
  <div class="figure-story__image">
    <img src="assets/figures/fig_water_stability.png" alt="Minimum oxygen to oxygen distance during own-model molecular dynamics, separating collapsed and stable models" loading="lazy">
  </div>
  <div class="figure-story__copy">
    <span class="section-kicker">The check that changed the answer</span>
    <h2>Accuracy chose a candidate. Dynamics decided whether to trust it.</h2>
    <p>Early water models could look acceptable on a force plot and still drive oxygen atoms into unphysical near contact. The own-MD screen separates those candidates from models that preserve a liquid-like excluded volume.</p>
    <p>The accepted 89-label model reached a closest O–O approach of 2.61 Å in its stability run.</p>
    <a class="text-link" href="case-studies/water/">Read the water case study <span aria-hidden="true">→</span></a>
  </div>
</section>

<section class="start-panel">
  <div>
    <span class="section-kicker">Start without spending compute</span>
    <h2>Test the complete loop on a laptop.</h2>
    <p>The smoke campaign exercises sampling, selection, mock labelling, training, validation and resumability. It needs neither CP2K nor a GPU and finishes in about two minutes.</p>
  </div>
  <div class="start-panel__action">
    <pre><code>pip install "cp2k-forge[train]"
cp2k-forge --check
cp2k-forge --config configs/smoke.yaml</code></pre>
    <a class="button button--light" href="getting-started/installation/">Installation guide <span aria-hidden="true">→</span></a>
  </div>
</section>

<p class="home-citation">CP2K-FORGE was developed by Dhruv Sharma as part of the 2026 MPhil in Scientific Computing at the University of Cambridge. The reported values above come from the accompanying thesis and its archived data.</p>
