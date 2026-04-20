# turbomole-cosmo

Reproducible TURBOMOLE 7.8 + COSMO workflow for COSMOtherm, on KU Leuven VSC
(wice / `lp_cheme_cfd`).

## Full workflow — PDB to .cosmo file

### Step 0: Convert PDB to XYZ (manual, with Avogadro)

RCSB PDB files are missing hydrogens and may contain crystal waters, ions,
or multiple chains. This step needs human judgment — it is NOT automated.

1. Go to Open OnDemand: https://ondemand.hpc.kuleuven.be/pun/sys/dashboard/batch_connect/sys/desktop/session_contexts/new
2. Launch a VNC desktop session
3. Open Avogadro
4. File → Open → load your molecule's `.pdb` file
5. Clean up the structure:
   - Remove crystal waters, ions, unwanted chains
   - Build → Add Hydrogens
   - Optionally: Extensions → Optimize Geometry (quick force-field cleanup)
6. Inspect: verify atom count, check that all hydrogens look reasonable
7. File → Save As → choose **XYZ format** → save as `<molecule>.xyz`
8. Place the `.xyz` file in `molecules/<molecule>/`

**Why not automate this?** PDB files from RCSB need chemistry-aware
preprocessing (hydrogen addition, water removal, conformer selection).
A blind format conversion gives garbage DFT results. Everything after
the .xyz is fully automated.

### Step 1: Prep (login node)

```bash
scripts/prep_cosmo.sh vancomycin BP-TZVPD-FINE
```

This runs on the login node (seconds, no SLURM) and does:
- `x2t` to convert XYZ → TURBOMOLE `coord` format
- `define` to set up basis set, DFT functional, RI, grid (via answer file)
- `cosmoprep` to define the COSMO cavity (via answer file)

After this, the molecule directory contains: `coord`, `control`, `basis`,
`mos`, `auxbasis` (for RI), all configured for COSMO.

### Step 2: Submit SCF job

```bash
scripts/submit_cosmo.sh vancomycin BP-TZVPD-FINE
```

Renders the SLURM template with your molecule name and config, submits
via `sbatch`, prints the job ID.

Or do Steps 1+2 together:
```bash
scripts/run_cosmo.sh vancomycin BP-TZVPD-FINE
```

### Step 3: Wait and verify

```bash
# Monitor:
squeue --clusters=wice -j <JOB_ID>

# After job finishes:
scripts/verify_cosmo.sh vancomycin
```

Checks that `.cosmo` file exists and is non-trivial, and that SCF converged.

### Step 4: Use in COSMOtherm

The `.cosmo` file in `molecules/vancomycin/vancomycin.cosmo` is ready
for COSMOtherm with the BP_TZVPD_FINE parameterization.

## Quick reference

```bash
# New molecule from PDB:
# 1. Convert PDB → XYZ in Avogadro (Open OnDemand VNC)
# 2. Place .xyz:
mkdir -p molecules/mymolecule
cp mymolecule.xyz molecules/mymolecule/
# 3. One command:
scripts/run_cosmo.sh mymolecule BP-TZVPD-FINE
# 4. After job finishes:
scripts/verify_cosmo.sh mymolecule
```

## Layout

```
turbomole-cosmo/
├── config.sh                         # edit once (paths, account, resources)
├── protocols/
│   ├── def2-SVP/                     # cheap validation protocol
│   │   ├── define.in                 # HF / def2-SVP
│   │   ├── cosmoprep.in             # all defaults + Bondi radii
│   │   └── slurm.tmpl               # runs dscf, 4 CPU / 20 GB / 6h
│   └── BP-TZVPD-FINE/               # production COSMOtherm protocol
│       ├── define.in                 # BP86 / def2-TZVPD / RI-J / grid m4
│       ├── cosmoprep.in             # FINE cavity (defaults in TM 7.8) + Bondi
│       └── slurm.tmpl               # runs ridft, 16 CPU / 120 GB / 72h
├── scripts/
│   ├── prep_cosmo.sh                 # x2t + define + cosmoprep
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

**BP-TZVPD-FINE** — BP86/def2-TZVPD with RI-J and m4 grid. Uses `ridft`.
FINE cavity (nppa=1082, nspa=92 — these are TURBOMOLE 7.8 defaults).
Matches the standard COSMOtherm BP_TZVPD_FINE parameterization.

## How the answer files work

`define` and `cosmoprep` are interactive tools. Instead of typing answers
by hand, we pipe pre-written answer files into them via stdin redirection.

**define.in** — key things to know:
- Line 1: blank (skips "read default data from control file" prompt)
- Line 2: blank (skips title prompt)
- Line 3: `a coord` (loads atoms from coord file into geometry menu)
- Then: basis, EHT guess, charge=0, occupation
- BP-TZVPD-FINE adds: `dft`/`ri` submenus for BP86 + RI-J + m4 grid

**cosmoprep.in** — prompts in order:
epsilon, refind, LR terms, COSMO RF equil, nppa, nspa, disex, rsolv,
routf, cavity, amat (all `d` for defaults), then `r all b` (Bondi radii),
`*`, output filename, `n` (no correlated calc).

## Important rules

- **Never run cosmoprep inside a SLURM job.** It's interactive. The scripts
  run it on the login node via stdin, which is equivalent.
- **dscf/ridft produce .cosmo at the END of SCF**, not earlier. Don't panic
  if it's absent mid-job.
- **Serial mode is safest** on this install. Scripts set `PARA_ARCH=SMP`
  (no MPI). OMP threads are set from SLURM's `--cpus-per-task`.
- After `scp`, always run `chmod +x scripts/*.sh` on wice.
- **PDB → XYZ must be done manually** in Avogadro (Open OnDemand VNC).
  Do not skip hydrogen addition — DFT needs complete structures.

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
Try increasing `--mem` in config.sh, or check if the geometry from
Avogadro needs further optimization. For large molecules (>150 atoms)
at TZVPD level, 120 GB may not be enough — try 200 GB on a bigmem node.

**Wrong atom count after Avogadro conversion:**
Make sure you removed crystal waters and ions before saving as XYZ.
Check: `head -1 molecules/<molecule>/<molecule>.xyz` should show the
expected atom count.
