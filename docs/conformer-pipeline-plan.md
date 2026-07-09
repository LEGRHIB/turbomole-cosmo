# Conformer-resolved COSMO-RS pipeline — implementation plan

Extension of the existing `turbomole-cosmo` repo into a reproducible, conformer-resolved
COSMO-RS pipeline. This plan reflects decisions confirmed 2026-07-06.

## Starting point (what already exists)

A mature **single-conformer, hand-rolled TURBOMOLE** COSMO pipeline for large charged
biomolecules: structure (PDB/SDF/AF-CIF) → clean/protonate (OpenBabel + PROPKA) → xTB
pre-opt → `x2t`+`define`+`cosmoprep` → tuned `ridft` single-point → `.cosmo` → COSMOtherm
solvent screen. Crown jewels: the **TZVP→TZVPD bootstrap**, **annealed-Fermi** rescue, and
**crash/timeout-safe SLURM** that make the SCF converge on ~1000+ atom proteins where a
stock `ridft` diverges. Config is `config.sh` (bash). No conformer layer, no COSMOconf,
no RMSD gate, no weight/sensitivity parsing, no mock/test scaffold.

## Decisions (confirmed)

| # | Decision | Choice |
|---|----------|--------|
| Target | first end-to-end molecule | **bombesin** (14-residue, neutral; has SDF + AF conformer) |
| Conformers | source for peptides | **MD front-end** (COSMOconf generation skipped for folded/large solutes) |
| AF intake | AlphaFold mmCIF | **ported into Stage 0** (self-contained pLDDT gate + residue grafting); AF model **seeds the MD front-end** (pairs with P5) |
| DFT driver | how TURBOMOLE is driven | **COSMOconf orchestrator + self-contained turbomoleio SCF backend** (decision B); stock for bombesin, hardened deferred |
| Stage 4 MD | build now? | **Fully implemented now** (OpenMM-first, sandbox-testable; GROMACS adapter for HPC) |
| Parametrisation | `.ctd` | **config-driven**, default `BP_TZVPD_FINE_25.ctd`; others licensed → selectable |
| Property | first run | **Relative solubility only** (log x_RS, conformer-weighted; no absolute S, no Tm·ΔHfus) |
| Solvents | first run | the 46-system crystallization panel → `config/solvent_panel.yaml` |

### The one reconciliation that matters
"COSMOconf-driven" + "large-peptide target" collide: `def2-TZVPD` overlap is near-singular
on folded peptides and COSMOconf's stock cascade drives a naked `ridft` that diverges
(documented in `docs/workflow.md`). Resolution: COSMOconf **orchestrates** (clustering,
cascade, packaging the reduced `.cosmo` set for AUTOC), but the SCF step is **pluggable** —
large/diffuse conformers route through the existing bootstrap/anneal/crash-safe backend via
`turbomoleio` `control` editing. Guaranteed fallback: hand-rolled SCF core for the DFT step.
Exact COSMOconf injection hook is verified against the licensed version in P4.

### Independence constraint (confirmed)

Standalone, **additive** pipeline — **no existing file is modified**. `scripts/`,
`protocols/`, `molecules/`, `config.sh`, `README.md`, `docs/workflow.md` stay exactly as
they are. All new code is namespaced under `cosmors/`, `config/`, `tests/`; new files added
inside existing dirs (this plan, `config/solvent_panel.yaml`) are additions, not edits.
Mixture ratios confirmed **v/v**.

**Decision: (B) fully self-contained.** The new package ships its own `turbomoleio`-based
SCF backend — zero runtime dependency on the old tree; the old `scripts/*.sh` are never
called. For **bombesin** (well-conditioned, ~160 atoms) only a **stock** single-point
backend is exercised. The **hardened** (bootstrap/anneal) backend is likewise self-contained
and is implemented when the pipeline is first pointed at a lysozyme-class system.

## Module layout (independent, additive-only)

```
cosmors/                      # new installable package (pip install -e .)
  config.py                   # YAML + env override; validates paths; ports config.sh
  models.py                   # Conformer, Ensemble, StageResult, WeightTable dataclasses
  workdir.py                  # idempotent/resumable working dirs + stamps
  stage0_input.py             # SMILES/SDF/xyz/PDB/CIF -> normalized 3D + charge (RDKit; reuse propka)
  stage1_confgen.py           # COSMOconf generation (small/med) OR ingest MD reps (peptides)
  cluster.py                  # RMSD Butina gate — ENFORCED before any DFT
  stage2_dft/
    driver.py                 # COSMOconf orchestration
    turbomole_backend.py      # self-contained SCF (turbomoleio): stock | hardened (bootstrap/anneal)
    cosmo_check.py            # epsilon=inf assertion + .cosmo validity (wraps verify_cosmo.sh)
  stage3_cosmotherm/
    input_builder.py          # folder-of-.cosmo AUTOC + .energy/EHfile; v/v->mole-fraction; solvent panel
    runner.py                 # invoke cosmotherm (wraps cosmotherm_screen.sh); resumable
  parse.py                    # per-phase conformer weights + property columns from CT output
  sensitivity.py              # decision gate: >95% single conf? spread? dominant flip gas/water/target?
  stage4_md/
    openmm_runner.py          # high-T MD / metadynamics (sandbox-testable)
    gromacs_runner.py         # GROMACS adapter (HPC)
    frames.py                 # frames -> RMSD Butina -> cluster reps -> multi-conf SDF
  cli.py                      # per-stage subcommands + `run`; --dry-run/--mock on every stage
config/
  config.template.yaml
  solvent_panel.yaml          # DONE — the 46-system crystallization panel
tests/fixtures/               # tiny synthetic .cosmo, .energy, CT .out, multi-conf SDF
pyproject.toml, environment.yml
```

Nothing under existing `scripts/`, `protocols/`, `molecules/` or the root configs is edited
or called. The SCF backend is self-contained (decision B): a stock single-point for
well-conditioned solutes like bombesin, and a self-contained bootstrap/anneal path added
later for large proteins.

## Phases (each = sandbox-runnable, meaningful commits)

- **P1** Scaffold: package, `config.py` (YAML port of `config.sh` + .ctd list, RMSD cutoffs,
  energy windows, T, solvents), `cli.py` with `--dry-run/--mock` everywhere, `workdir.py`,
  `models.py`. Tests: config load/override, dry-run wiring. Pure sandbox, no science.
- **P2** Stage 0 + Stage 1 (MD-reps ingest path) + **RMSD gate**. Prove near-identical
  geometries are dropped *before* DFT. Fixture-tested.
- **P3** Stage 3 builder + parser + **sensitivity report** — highest scientific value,
  fully fixture-testable. AUTOC multi-`.cosmo`, `.energy`/EHfile, v/v→mole-fraction,
  solvent panel. Property = **relative solubility (log x_RS) only**, conformer-weighted
  (`relative` + `force_qspr`, as in the existing screen template). This produces the
  "do conformers matter?" decision gate.
- **P4** Stage 2 COSMOconf driver + self-contained stock SCF backend + epsilon=∞ hard check.
  (Hardened bootstrap/anneal backend deferred until a large protein needs it.) Mock in
  sandbox; real path documented.
- **P5** Stage 4 MD front-end (full): OpenMM high-T MD / metadynamics, GROMACS adapter,
  frames→Butina→multi-conf SDF feeding Stage 1 with COSMOconf generation skipped.
  Integration-tested on a tiny system in-sandbox. **+ AlphaFold mmCIF intake** (pLDDT
  gate + non-standard-residue grafting, self-contained port of `prepare_alphafold.py`)
  feeding MD as the seed geometry.
- **P6** End-to-end bombesin **mock** run + README (sandbox-vs-HPC split, per-stage HPC
  commands, MD decision logic) + pinned `environment.yml`.

## Dependency justification (brief asks)

- **RDKit** — SMILES→3D, Butina clustering, SDF I/O. Already a transitive dep
  (`prepare_alphafold.py`). Keep.
- **turbomoleio** (GPL-3, pymatgen) — now the **core of the self-contained SCF backend**:
  programmatic `control`/`define` editing (`add_cosmo`, COSMO ε=∞), ridft/energy parsing,
  and `.energy` for EHfile. Isolated so core mock/tests don't hard-require it.
- **OpenMM** — MD front-end; open-source, pip-installable, so Stage 4 is genuinely
  testable in-sandbox on a small peptide. GROMACS is the HPC adapter.
- **PyYAML**, **pytest** — config, tests. Trivial.
- Keep existing **OpenBabel** / **PROPKA** for protonation.

## Assumptions to confirm (non-blocking)

1. Solvent-mixture ratios (95:5, 9:1, …) read as **v/v** → converted to mole fraction.
2. **PBS / phosphate buffer pH 7** approximated as **water** (pH/ionic strength outside COSMO-RS).
3. COSMObase basenames for the panel filled during P3 against the installed BP-TZVPD-FINE DB.

## Sandbox vs HPC split

TURBOMOLE / COSMOconf / COSMOtherm are license-locked and run only on VSC/workstation.
In this sandbox every stage runs in `--dry-run/--mock` against synthetic fixtures; no
scientific numbers are fabricated for real molecules. OpenMM MD (Stage 4) is the one stage
that runs for real in-sandbox on tiny test systems.
