# Lysozyme: COSMO-RS solubility prediction vs. crystallization literature

**Status:** plan (Stage 0). Nothing runs on the cluster until (a) `lysozyme.cosmo`
exists and (b) each step is confirmed. Companion data file:
`docs/lysozyme-crystallization-reference.xlsx`.

**Decisions locked (2026-06-16):**
- **Headline = antisolvent / solvent-affinity ranking.** This is COSMO-RS's
  *validated* use case (solvent selection for crystallization/recrystallization),
  so it's the apples-to-apples comparison.
- **NaCl salting-out = secondary "limits of the method" probe** (COSMO-RS's weak
  spot; kept to show where it strains).
- **Antisolvent set = broad organic panel:** ethanol, acetone, 2-propanol,
  acetonitrile, DMSO, methanol.
- **Benchmark = qualitative** — reproduce the *sign / ranking*, not absolute mg/mL.
- **Deliverable = Excel reference table + this writeup.**

---

## 1. Goal

After `lysozyme.cosmo` is generated (BP-TZVPD-FINE-ANNEAL), test how well COSMO-RS
(COSMOtherm, BP_TZVPD_FINE parameterization) reproduces the **antisolvent
crystallization** behavior of hen egg-white lysozyme (HEWL): the protein is highly
soluble in water (and water-rich, polar/protic media), and adding a water-miscible
**organic antisolvent** (ethanol, acetone, 2-propanol, acetonitrile, DMSO …) lowers
its solubility, driving supersaturation and crystallization/precipitation. Concretely:
*does COSMO-RS rank water (and water-rich mixtures) as the best solvent and correctly
order the organic antisolvents by how strongly they drive lysozyme out of solution?*

## 2. What the literature says

**Antisolvent / solvent solubility (the headline benchmark):**
- Direct data: **lysozyme solubility in water + ethanol and water + acetone** vs.
  organic fraction (Fluid Phase Equilibria, 2016) — solubility falls as the organic
  fraction rises (an antisolvent curve). Caveat: the *measured* solubility also
  depends on initial protein concentration (up to ~5× ethanol, ~3× acetone) — a
  kinetic/metastability effect.
- **Preferential solvation** of lysozyme studied with DMSO, DMF, acetonitrile,
  1,4-dioxane, acetone as cosolvents (J. Phys. Chem. B, 2025).
- General rule: protic, hydrophilic, polar solvents keep lysozyme soluble
  (>10 mg/mL); organic antisolvents precipitate it. Lysozyme can be precipitated
  from DMSO solution by adding a "non-dissolving" cosolvent. Supercritical / expanded
  liquid antisolvent processes use acetone and 2-propanol as antisolvents.
- COSMO-RS reference performance: for small-molecule pharma solvent ranking, COSMO-RS
  gives good *qualitative* ranking (RMSLD ~0.5–1.5 log units) — the bar we extrapolate.

**Salt crystallization (secondary axis; see the .xlsx for the full table):**
- Tetragonal P4₃2₁2 via NaCl ~1–7% w/v, 0.1 M Na-acetate, pH ~4.5, ~15–18 °C;
  solubility ↓ with NaCl (salting-out), ↑ with T; (NH₄)₂SO₄ salts out more strongly;
  no salting-in at low ionic strength; local solubility max near ~0.63 M NaCl.

## 3. Reality check — what COSMO-RS can and cannot claim for a 14 kDa protein

**This is the right tool for the headline axis.** Solvent/antisolvent ranking via
γ∞ and ΔG_solv is exactly what COSMO-RS is built and validated for. Use those (and
relative log-S) as the comparison metrics.

**Caveats to state explicitly:**
- **"Solubility in different solvents" for a protein = solubility in water + X% organic,
  not neat-organic solubility.** Lysozyme denatures/precipitates in pure organics, so
  the comparable quantity (and what COSMO-RS computes well) is the aqueous–organic
  mixture vs. antisolvent fraction.
- **Absolute solubility is meaningless:** no real Tₘ/ΔH_fus; the `force_qspr` estimate
  is parameterized on small drug-like molecules. Only *relative* trends/rankings count.
- **Initial-concentration / metastability dependence** of the measured solubility is a
  kinetic effect an equilibrium theory cannot reproduce.
- **Denaturation:** organics can unfold the protein, changing its σ-profile; we use a
  single fixed GFN-FF-preopt conformer, so conformational change is invisible.
- **Single rigid conformer** (no Boltzmann ensemble) — a standard protein caveat.

**Secondary-axis weakness (salt):** COSMO-RS is a local surface-contact theory with no
native Debye–Hückel/DLVO term; published result (J. Phys. Chem. A, 2017) is that it
*overpredicts* salting-out / Setschenow too large. Expect the correct *sign* for NaCl
but inflated magnitude, and the ~0.63 M dip missed. pH/charge dependence is out of
scope (only one `.cosmo`, +11 @ pH 4.6).

## 4. Comparison design

### Axis A — antisolvent / solvent-affinity ranking (HEADLINE)
Run the existing Phase-7 screen and read **γ∞, ΔG_solv, relative log-solubility** of
lysozyme across pure solvents and, crucially, **water + organic antisolvent mixtures at
increasing organic fraction** for the broad panel: ethanol, acetone, 2-propanol,
acetonitrile, DMSO, methanol.
- Your `mixtures-binary.list` already has water–ethanol (3 ratios), water–methanol,
  water–acetonitrile, water–DMSO. **Add water–acetone and water–2-propanol** (a few
  fractions each) to complete the panel and to hit the ethanol/acetone benchmark
  directly; optionally densen the ethanol grid to match the FPE-2016 points.
- *Pass (qualitative):* (1) water / water-rich = most favorable (lowest γ∞);
  (2) solubility/affinity **decreases monotonically** as antisolvent fraction rises for
  every organic; (3) the *ranking* of antisolvent strength is sensible and, for ethanol
  vs. acetone, consistent with the FPE-2016 direction.

### Axis B — NaCl salting-out (SECONDARY; limits-of-method probe)
Reuse `screen-mixture.tmpl` with the "solvent" = water + explicit Na⁺/Cl⁻ ions, stepping
salt mole fraction up. Optional (NH₄)₂SO₄ cross-check. Report it explicitly as the axis
where COSMO-RS is expected to strain.
- Design decisions to settle before running: ion `.cosmo` availability in the cluster's
  BP-TZVPD-FINE COSMObase; counterion / charge-balance treatment for the +11 solute;
  whether to test COSMOtherm's electrolyte correction vs. plain explicit ions.
- *Pass:* correct sign (solubility ↓ with NaCl), (NH₄)₂SO₄ > NaCl. *Expected misses:*
  inflated magnitude, ~0.63 M dip absent, no salting-in.

## 5. Success criteria (qualitative scorecard)

| Behavior | Literature | COSMO-RS pass condition | Axis |
|---|---|---|---|
| Best solvent | water / polar-protic | water lowest γ∞ | A |
| Add organic antisolvent ↑ | solubility ↓ | affinity ↓ / γ∞ ↑, monotonic | A |
| Ethanol vs acetone | direction from FPE-2016 | same relative ordering | A |
| Antisolvent ranking | EtOH/acetone/IPA/MeCN/DMSO | sensible, consistent order | A |
| Add NaCl ↑ | solubility ↓ (salting-out) | same sign, monotonic | B |
| (NH₄)₂SO₄ vs NaCl | stronger salting-out | Kₛ((NH₄)₂SO₄) > Kₛ(NaCl) | B |
| ~0.63 M NaCl dip | local max | expected MISS (documented) | B |
| Salt magnitude | moderate Kₛ | expected OVERPREDICTION (documented) | B |

## 6. Workflow (staged; gated on `lysozyme.cosmo`)

0. **Done** — this plan + `lysozyme-crystallization-reference.xlsx`.
1. **Axis A (headline)** — once `lysozyme.cosmo` (BP-TZVPD-FINE-ANNEAL) is verified:
   add water–acetone / water–2-propanol rows to `mixtures-binary.list`; run
   `scripts/cosmotherm_screen.sh lysozyme BP-TZVPD-FINE-ANNEAL` →
   `cosmotherm_postprocess.py …`; read γ∞/ΔG_solv vs. antisolvent fraction; fill the
   §5 Axis-A scorecard; plot affinity vs. organic fraction.
2. **Axis B (secondary)** — confirm ion `.cosmo` availability; add `screen-salt.tmpl` +
   `salts.list` (NaCl, (NH₄)₂SO₄ at stepped mole fractions); run; document where it
   strains.
3. **Compare & write up** — qualitative scorecard + plots; clear scope/limits note.

All new templates/lists are edited on the **Mac repo only** (GitHub → Mac → cluster);
youcef drives the cluster and pastes output back. Each cluster step is confirmed before
it runs.

## 7. Open questions for the next planning step
- Exact antisolvent mole-fraction grid (and whether to match specific FPE-2016 points).
- For Axis B: counterion/charge-balance treatment of the +11 solute; explicit ions vs.
  COSMOtherm electrolyte correction.
- Whether MPD/PEG (needs new `.cosmo`) is added later as a crystallization-grade
  organic extension.
