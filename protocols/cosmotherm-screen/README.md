# COSMO-RS Solubility Screen

Pipeline that runs COSMOtherm (BP_TZVPD_FINE_25.ctd) on each molecule's
DFT-COSMO `.cosmo` file across a panel of pure solvents and binary mixtures,
producing absolute solubility (where Tm/dHfus is available or QSPR-estimable),
mass and molar solubility, plus chemical potential / activity-coefficient data.

## Files

- `solvents-pure.list` — 28 pure solvents (COSMObase basenames, one per line)
- `mixtures-binary.list` — 10 binary mixtures with mole fractions
- `screen-pure.tmpl` — COSMOtherm input template for the pure-solvent screen
  (uses `solub screening solute=1 pure=3 force_qspr iterative`)
- `screen-mixture.tmpl` — COSMOtherm input template for one binary mixture
  (uses `solub iterative force_qspr xs={...}`)

## Usage

```bash
# Source COSMOtherm env once per session (or rely on cosmotherm_screen.sh to do it)
source /data/leuven/385/vsc38535/cosmotherm/cosmotherm-env.sh

# Run full screen for one molecule + DFT protocol pair
scripts/cosmotherm_screen.sh vancomycin BP-TZVPD-FINE

# Aggregate results into a CSV
scripts/cosmotherm_postprocess.py vancomycin BP-TZVPD-FINE
```

Outputs land in `molecules/<molecule>/<dft-protocol>/cosmotherm/`:
- `pure-screen.{inp,out,tab}` — pure-solvent screen
- `mix-<label>.{inp,out,tab}` — one set per binary mixture
- `results.csv` — aggregated post-processed table

## Notes

- All preds use `force_qspr` so molecules without experimental Tm/dH_fus still
  get an absolute solubility estimate. For peptides/proteins (bombesin, lysozyme)
  the absolute number is a coarse approximation; γ∞ and ΔG_solv columns are
  the more trustworthy comparison metric.
- T = 298.15 K throughout. To screen at other temperatures, override `tc=` in
  the templates.
- Solvents not in BP-TZVPD-FINE COSMObase (DCM, MTBE, NMP, propylene glycol) are
  excluded — adding them would require either using BP-TZVP cosmo files (mixing
  parameterizations, not recommended) or computing them ourselves at BP-TZVPD-FINE.
