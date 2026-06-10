# turbomole-cosmo

Reproducible TURBOMOLE 7.8 + COSMO workflow for COSMOtherm, on KU Leuven VSC
(wice / `lp_cheme_cfd`).

Pipeline: **PDB/SDF → clean → protonate → XYZ → (xTB pre-opt) → TURBOMOLE DFT-COSMO → `.cosmo`**.
Supports PDB (crystal structures) and SDF (2D/3D) input.

## Workflow

### 1. Prepare the molecule (local, needs OpenBabel)

```bash
python3 scripts/prepare_molecule.py molecules/vancomycin/1SHO.pdb vancomycin 2.6 --chains A,C
```

Cleans the structure (waters, ions, alternate conformers, chain selection — via
`clean_pdb.py`), protonates at the target pH with OpenBabel, determines total
charge, and writes `molecules/<mol>/<mol>.xyz` + `charge.txt`. Format is
auto-detected; for SDF it builds 3D coords with `--gen3d`.

**Verify the charge** afterward — OpenBabel's pKa model is generic. Check
`prep.log` and edit `charge.txt` if needed. For titratable proteins,
`scripts/propka_prep.py` derives a PROPKA-based charge (e.g. lysozyme +11 at pH 4.6).

### 2. xTB pre-optimization (recommended for SDF / rough geometries)

```bash
scripts/xtb_preopt.sh vancomycin_2d          # GFN2-xTB; --gfn ff fallback for >1500-atom systems
```

Cleans up bond angles, contacts and conformer issues in minutes so the DFT SCF
starts from a sane geometry. Updates the active `<mol>.xyz`.

### 3. Prep — define + cosmoprep + SCF tuning

```bash
scripts/prep_cosmo.sh vancomycin BP-TZVPD-FINE
# large proteins: run prep as a bigmem job — define's EHT guess needs the RAM, not the cores
scripts/prep_cosmo.sh lysozyme BP-TZVPD-FINE-ANNEAL --slurm --partition bigmem --cpus 8 --mem 500000M
```

Runs `x2t` + `define` (basis/DFT/RI/grid; charge from `charge.txt`) + `cosmoprep`
(COSMO cavity), then applies the tuned SCF block (below). Writes `prep_ok.stamp`.

### 4. Submit the SCF

```bash
scripts/submit_cosmo.sh vancomycin BP-TZVPD-FINE
scripts/submit_cosmo.sh lysozyme BP-TZVPD-FINE-ANNEAL --partition bigmem --cpus 72 --mem 2000000M
```

### 5. Verify

```bash
scripts/verify_cosmo.sh vancomycin BP-TZVPD-FINE
```

Checks the `.cosmo` exists and is non-trivial, the SCF converged, and `$cosmo_out`
is in `control`. The `.cosmo` (e.g. `molecules/vancomycin/BP-TZVPD-FINE/vancomycin.cosmo`)
is then ready for COSMOtherm with the BP_TZVPD_FINE parameterization.

## Protocols

**BP-TZVPD-FINE** — BP86 / def2-TZVPD, RI-J, m4 grid, FINE cavity. Single-point
`ridft`. The production protocol; matches COSMOtherm's BP_TZVPD_FINE
parameterization. Use on a good (crystal or xTB-preopt) geometry.

**BP-TZVPD-FINE-ANNEAL** — same DFT setup, but `_tune_scf.sh` injects an *annealed*
Fermi schedule (2000 K → 300 K, 0.95/cycle) for highly-charged proteins whose
near-zero HOMO/LUMO gap makes a constant-300 K Fermi window lose its bracket and
diverge (lysozyme +11). Its `slurm.tmpl` is crash/timeout-safe: `ridft.out` is
checkpointed every 5 min and a warm-restartable `mos` is saved on exit
(`#SBATCH --signal=B:TERM@600`), so a resubmit continues the SCF instead of
cold-starting.

### Auto-tuned SCF (BP-TZVPD-*)

`prep_cosmo.sh` → `_tune_scf.sh` applies to `control`:

```
$scfiterlimit      300
$scfdamp   start=0.700  step=0.050  min=0.050
$scforbitalshift  automatic=.3
$fermi tmstrt=…  tmend=300 …     # constant 300 K (FINE) or annealed 2000→300 K (*FINE-ANNEAL)
```

Fermi smearing (`hlcrt=1.0e-3`) only activates when the gap drops below 1 mHa — a
no-op for normal molecules, a rescue for metallic-character proteins/peptides.

## Layout

```
turbomole-cosmo/
├── config.sh                     # paths, account, SLURM resource defaults
├── protocols/
│   ├── BP-TZVPD-FINE/            # production single-point (ridft)
│   ├── BP-TZVPD-FINE-ANNEAL/     # + annealed Fermi, crash/timeout-safe slurm
│   └── cosmotherm-screen/        # Phase 7: COSMO-RS solvent screen
├── scripts/
│   ├── prepare_molecule.py       # PDB/SDF → clean → protonate → XYZ + charge
│   ├── clean_pdb.py              # PDB cleanup (imported by prepare_molecule.py)
│   ├── propka_prep.py            # PROPKA pH-dependent charge (proteins)
│   ├── xtb_preopt.sh             # GFN2 / GFN-FF geometry pre-optimization
│   ├── prep_cosmo.sh             # x2t + define + cosmoprep + SCF tuning
│   ├── _tune_scf.sh              # SCF damping / shift / Fermi injection
│   ├── submit_cosmo.sh           # render slurm.tmpl + sbatch
│   ├── verify_cosmo.sh           # post-job checks
│   ├── audit_cluster.sh          # read-only cluster inventory
│   ├── cosmotherm_setup.sh       # COSMOtherm env validation   (Phase 7)
│   ├── cosmotherm_screen.sh      # pure + binary-mixture screen (Phase 7)
│   └── cosmotherm_postprocess.py # aggregate results.csv        (Phase 7)
└── molecules/<mol>/<protocol>/   # compute artifacts (gitignored)
```

## Important rules

- **Never run `cosmoprep` inside a batch step blindly** — it's interactive; the
  scripts pipe a pre-written answer file into it.
- **`.cosmo` is produced at the END of SCF**, not mid-job.
- **Serial / SMP only** on this install (`PARA_ARCH=SMP`, no MPI); OMP threads
  come from `--cpus-per-task`.
- Code flows GitHub → Mac → cluster (`git pull` on the cluster; never edit there).
  Outputs flow cluster → Mac (cluster is source of truth); `.cosmo` / `mos` /
  `charge.txt` are gitignored.

## Troubleshooting

**SCF won't converge / energy oscillates ±10⁵ Eh** — classic metallic-character
failure (gap < kT; charged peptides/proteins). Use the `*-ANNEAL` protocol. Confirm
the annealed schedule landed: `grep '^\$fermi' control` should show `tmstrt=2000`.
Warm-restart by resubmitting (no re-prep) — the saved `mos` is the guess.

**`define` OOMs on large molecules** — the EHT guess at def2-TZVPD needs >200 GB
for ~2000-atom systems; run prep with `--slurm --partition bigmem`.

**Wrong charge / atom count after `prepare_molecule.py`** — check `prep.log`;
OpenBabel's pH model may miss groups. Edit `charge.txt` (or use `propka_prep.py`)
before prep.

**Permission denied on scripts** — `chmod +x scripts/*.sh` after transfer.

## Audit & hygiene

`scripts/audit_cluster.sh` writes a read-only inventory to `docs/audit/cluster-<date>.md`.
Run it periodically; cleanup decisions are recorded in `docs/cleanup-<date>.md`.
Disk policy: `.cosmo` and success stamps are permanent; `mos` from a failed run is
deleted once the failure is confirmed; `_archive-*/` is pruned after 30 days.
