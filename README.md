# turbomole-cosmo

Reproducible TURBOMOLE 7.8 + COSMO workflow for COSMOtherm, on KU Leuven VSC
(wice / `lp_cheme_cfd`).

Fully automated pipeline: **PDB + pH → clean → protonate → XYZ → TURBOMOLE → .cosmo file**.
No manual Avogadro step needed.

## Full workflow — PDB to .cosmo file

### One-command pipeline

```bash
scripts/full_pipeline.sh molecules/vancomycin/1SHO.pdb vancomycin 2.6 --chains A,C
```

This single command runs the entire pipeline:
1. Cleans the PDB (removes waters, ions, selects chains, resolves alternate conformers)
2. Protonates at your specified pH using OpenBabel
3. Determines the molecular charge automatically
4. Writes the XYZ file and `charge.txt`
5. Runs TURBOMOLE prep (`x2t` + `define` + `cosmoprep`) on the login node
6. Submits the SLURM job

Options:
- `--chains A,C` — keep only specific chains (default: all)
- `--protocol BP-TZVPD-OPT` — choose protocol (default: `BP-TZVPD-OPT`)
- `--prep-only` — stop after XYZ generation (no TURBOMOLE, for local use)
- `--no-submit` — run TURBOMOLE prep but don't submit the SLURM job

### Step-by-step (if you prefer)

#### Step 0: Prepare molecule (automated)

```bash
python3 scripts/prepare_molecule.py \
    molecules/vancomycin/1SHO.pdb \
    vancomycin \
    2.6 \
    --chains A,C
```

This replaces the old manual Avogadro workflow. It automatically:
- Cleans the PDB: removes crystal waters (HOH), ions (ACT, CL, etc.), keeps only your selected chains
- Resolves alternate conformers (keeps highest-occupancy "A" conformer)
- Filters CONECT records to match surviving atoms
- Protonates at your target pH using OpenBabel (`obabel -p <pH>`)
- Determines total molecular charge from formal charges
- Writes `molecules/<molecule>/<molecule>.xyz` and `molecules/<molecule>/charge.txt`

**Requires:** OpenBabel on your PATH (`brew install open-babel` on macOS,
`apt install openbabel` on Linux).

#### Step 1: Prep (login node)

```bash
scripts/prep_cosmo.sh vancomycin BP-TZVPD-OPT
```

This runs on the login node (seconds, no SLURM) and does:
- `x2t` to convert XYZ → TURBOMOLE `coord` format
- `define` to set up basis set, DFT functional, RI, grid (via answer file)
  — charge is read automatically from `charge.txt`
- `cosmoprep` to define the COSMO cavity (via answer file)

After this, the molecule directory contains: `coord`, `control`, `basis`,
`mos`, `auxbasis` (for RI), all configured for COSMO.

#### Step 2: Submit job

```bash
scripts/submit_cosmo.sh vancomycin BP-TZVPD-OPT
```

Renders the SLURM template with your molecule name and config, submits
via `sbatch`, prints the job ID.

Or do Steps 1+2 together:
```bash
scripts/run_cosmo.sh vancomycin BP-TZVPD-OPT
```

#### Step 3: Wait and verify

```bash
# Monitor:
squeue --clusters=wice -j <JOB_ID>

# After job finishes:
scripts/verify_cosmo.sh vancomycin
```

Checks that `.cosmo` file exists and is non-trivial, and that SCF converged.

#### Step 4: Use in COSMOtherm

The `.cosmo` file in `molecules/vancomycin/vancomycin.cosmo` is ready
for COSMOtherm with the BP_TZVPD_FINE parameterization.

## Quick reference

```bash
# New molecule from PDB — fully automated:
scripts/full_pipeline.sh input.pdb mymolecule 7.4 --chains A,C

# Or step by step:
python3 scripts/prepare_molecule.py input.pdb mymolecule 7.4 --chains A,C
scripts/run_cosmo.sh mymolecule BP-TZVPD-OPT

# After job finishes:
scripts/verify_cosmo.sh mymolecule

# Batch mode — submit all molecules that have .xyz but no .cosmo:
scripts/batch_cosmo.sh
```

## Protonation and charge

The `prepare_molecule.py` script handles pH-dependent protonation automatically
using OpenBabel's pKa model. The determined charge is written to `charge.txt`
and picked up by `prep_cosmo.sh` when configuring TURBOMOLE's `define`.

**Important:** OpenBabel's pH model is generic — it may not get every
ionizable group right for complex peptides. After running `prepare_molecule.py`,
check the reported charge in `prep.log`. For example, vancomycin at pH 2.6
should be charge +2 (N-methyl-leucine amine + vancosamine amine both protonated,
C-terminal carboxyl protonated as COOH). If the charge is wrong, manually edit
`charge.txt` before running `prep_cosmo.sh`.

## Layout

```
turbomole-cosmo/
├── config.sh                         # edit once (paths, account, resources)
├── protocols/
│   ├── def2-SVP/                     # cheap validation protocol
│   │   ├── define.in                 # HF / def2-SVP
│   │   ├── cosmoprep.in             # all defaults + Bondi radii
│   │   └── slurm.tmpl               # runs dscf, 4 CPU / 20 GB / 6h
│   ├── BP-TZVPD-FINE/               # production single-point protocol
│   │   ├── define.in                 # BP86 / def2-TZVPD / RI-J / grid m4
│   │   ├── cosmoprep.in             # FINE cavity + Bondi radii
│   │   └── slurm.tmpl               # runs ridft, 16 CPU / 120 GB / 72h
│   └── BP-TZVPD-OPT/                # geometry optimization protocol
│       ├── define.in                 # BP86 / def2-TZVPD / RI-J / grid m4
│       ├── cosmoprep.in             # FINE cavity + Bondi radii
│       └── slurm.tmpl               # runs jobex -ri, 16 CPU / 120 GB / 168h
├── scripts/
│   ├── prepare_molecule.py           # PDB → clean → protonate → XYZ + charge
│   ├── clean_pdb.py                  # PDB cleanup (waters, ions, alt conformers)
│   ├── full_pipeline.sh              # end-to-end: PDB → SLURM submission
│   ├── prep_cosmo.sh                 # x2t + define + cosmoprep (charge-aware)
│   ├── submit_cosmo.sh               # render SLURM template + sbatch
│   ├── run_cosmo.sh                  # prep + submit in one call
│   ├── verify_cosmo.sh               # post-job checks
│   ├── diff_against_known_good.sh    # regression test vs reference
│   ├── batch_cosmo.sh                # loop over all molecules/
│   └── pdb2xyz.py                    # simple PDB→XYZ (only for clean PDBs)
└── molecules/
    ├── bradykinin/                    # validation case
    └── vancomycin/                    # production case
```

## Protocols

**def2-SVP** — HF/def2-SVP, no DFT, no RI. Uses `dscf`. Fast, cheap,
useful for testing the pipeline.

**BP-TZVPD-FINE** — BP86/def2-TZVPD with RI-J and m4 grid. Uses `ridft`
(single-point SCF). FINE cavity (nppa=1082, nspa=92 — TURBOMOLE 7.8
defaults). Matches the standard COSMOtherm BP_TZVPD_FINE parameterization.
Use this when you already have an optimized geometry.

**BP-TZVPD-OPT** — Same DFT setup as BP-TZVPD-FINE, but runs `jobex -ri`
for geometry optimization with COSMO. This is the recommended protocol for
new molecules: it optimizes the geometry in the COSMO continuum before
extracting the .cosmo file, giving more accurate sigma profiles than a
single-point on a crystal or force-field geometry. Allocated 168h (7 days)
wall time for large molecules.

## How the answer files work

`define` and `cosmoprep` are interactive tools. Instead of typing answers
by hand, we pipe pre-written answer files into them via stdin redirection.

**define.in** — key things to know:
- Line 1: blank (skips "read default data from control file" prompt)
- Line 2: blank (skips title prompt)
- Line 3: `a coord` (loads atoms from coord file into geometry menu)
- Then: basis, EHT guess, `__CHARGE__` placeholder (substituted from charge.txt), occupation
- BP-TZVPD protocols add: `dft`/`ri` submenus for BP86 + RI-J + m4 grid

**cosmoprep.in** — prompts in order:
epsilon, refind, LR terms, COSMO RF equil, nppa, nspa, disex, rsolv,
routf, cavity, amat (all `d` for defaults), then `r all b` (Bondi radii),
`*`, output filename, `n` (no correlated calc).

## Important rules

- **Never run cosmoprep inside a SLURM job.** It's interactive. The scripts
  run it on the login node via stdin, which is equivalent.
- **dscf/ridft produce .cosmo at the END of SCF**, not earlier. Don't panic
  if it's absent mid-job. For `jobex`, the .cosmo is produced after
  geometry convergence.
- **Serial mode is safest** on this install. Scripts set `PARA_ARCH=SMP`
  (no MPI). OMP threads are set from SLURM's `--cpus-per-task`.
- After `scp`, always run `chmod +x scripts/*.sh` on wice.
- **Verify the charge** after `prepare_molecule.py` — OpenBabel's pH model
  is generic and may not handle all ionizable groups correctly for complex
  peptides. Edit `charge.txt` manually if needed.

## Troubleshooting

**define fails with "UNKNOWN COMMAND":**
The answer file has wrong number of blank lines at the top. define asks
two questions before the geometry menu: (1) read default data from control
file? (2) title. Both need a blank line (Enter). Check `logs/define.log`.

**cosmoprep fails with "input variable is not real":**
The prompt sequence is offset. cosmoprep starts with epsilon and refind
before the settings from the original notes. Check `logs/cosmoprep.log`
to see which prompt got the wrong input.

**Permission denied on scripts:**
Run `chmod +x scripts/*.sh` after every `scp`.

**SCF doesn't converge:**
Try increasing `--mem` in config.sh, or check if the starting geometry
needs improvement. For large molecules (>150 atoms) at TZVPD level,
120 GB may not be enough — try 200 GB on a bigmem node.

**Wrong atom count after prepare_molecule.py:**
Check `prep.log` for the cleaning report. Common issues: wrong `--chains`
selection, or the PDB has unusual residue names not in the removal list.

**Wrong charge detected:**
OpenBabel's generic pKa model may miss molecule-specific ionization.
Check `prep.log`, compare against known pKa values for your molecule,
and edit `charge.txt` manually before running `prep_cosmo.sh`.

**jobex doesn't converge (BP-TZVPD-OPT):**
Geometry optimization on large molecules may need more than 200 cycles.
Check `jobex.out` for the convergence history. You can restart by
resubmitting — `jobex` reads the current `coord` and continues.
Increase wall time in config.sh if hitting the 168h limit.
