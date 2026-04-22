#!/bin/bash
# full_pipeline.sh — End-to-end: PDB → clean → protonate → XYZ → TURBOMOLE → submit
#
# Universal workflow: specify any PDB, any pH, and optionally which chains.
# Handles protonation, charge determination, and TURBOMOLE setup automatically.
#
# Usage:
#   scripts/full_pipeline.sh <input.pdb> <molecule> <pH> [options]
#
# Options:
#   --chains A,C          Keep only these chains (default: all)
#   --protocol NAME       TURBOMOLE protocol (default: BP-TZVPD-OPT)
#   --prep-only           Stop after prepare_molecule.py (don't run TURBOMOLE prep)
#   --no-submit           Run prep_cosmo.sh but don't submit to SLURM
#
# Examples:
#   # Vancomycin at pH 2.6, chains A+C, full geometry optimization
#   scripts/full_pipeline.sh molecules/vancomycin/1SHO.pdb vancomycin 2.6 --chains A,C
#
#   # Bradykinin at pH 7.4, all chains, single-point only
#   scripts/full_pipeline.sh molecules/bradykinin/bradykinin.pdb bradykinin 7.4 --protocol BP-TZVPD-FINE
#
#   # Just prepare XYZ locally (no HPC needed)
#   scripts/full_pipeline.sh input.pdb mymolecule 7.4 --prep-only
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Parse arguments ----------------------------------------------------------
INPUT_PDB=""
MOLECULE=""
PH=""
CHAINS=""
PROTOCOL="BP-TZVPD-OPT"
PREP_ONLY=false
NO_SUBMIT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --chains)    CHAINS="$2"; shift 2 ;;
    --protocol)  PROTOCOL="$2"; shift 2 ;;
    --prep-only) PREP_ONLY=true; shift ;;
    --no-submit) NO_SUBMIT=true; shift ;;
    --help|-h)
      head -n 25 "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *)
      if [[ -z "$INPUT_PDB" ]]; then
        INPUT_PDB="$1"
      elif [[ -z "$MOLECULE" ]]; then
        MOLECULE="$1"
      elif [[ -z "$PH" ]]; then
        PH="$1"
      else
        echo "ERROR: unexpected argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [[ -z "$INPUT_PDB" || -z "$MOLECULE" || -z "$PH" ]]; then
  echo "Usage: $0 <input.pdb> <molecule> <pH> [--chains A,C] [--protocol NAME]" >&2
  echo "       $0 --help for full usage" >&2
  exit 2
fi

echo "================================================================"
echo "  TURBOMOLE COSMO Full Pipeline"
echo "================================================================"
echo "  Input PDB:  $INPUT_PDB"
echo "  Molecule:   $MOLECULE"
echo "  pH:         $PH"
echo "  Chains:     ${CHAINS:-all}"
echo "  Protocol:   $PROTOCOL"
echo "  Prep only:  $PREP_ONLY"
echo "  No submit:  $NO_SUBMIT"
echo "================================================================"
echo

# --- Step 1: Prepare molecule (PDB → clean → protonate → XYZ + charge) -------
echo ">>> STEP 1: Preparing molecule"
echo "---"

PREP_ARGS=("$INPUT_PDB" "$MOLECULE" "$PH")
if [[ -n "$CHAINS" ]]; then
  PREP_ARGS+=(--chains "$CHAINS")
fi

python3 "$SCRIPT_DIR/prepare_molecule.py" "${PREP_ARGS[@]}"

MOL_DIR="$REPO_ROOT/molecules/$MOLECULE"

# Verify outputs
if [[ ! -f "$MOL_DIR/$MOLECULE.xyz" ]]; then
  echo "ERROR: prepare_molecule.py did not produce $MOL_DIR/$MOLECULE.xyz" >&2
  exit 3
fi
if [[ ! -f "$MOL_DIR/charge.txt" ]]; then
  echo "ERROR: prepare_molecule.py did not produce $MOL_DIR/charge.txt" >&2
  exit 3
fi

CHARGE=$(cat "$MOL_DIR/charge.txt" | tr -d '[:space:]')
N_ATOMS=$(head -n1 "$MOL_DIR/$MOLECULE.xyz")

echo
echo "  XYZ ready:  $MOL_DIR/$MOLECULE.xyz ($N_ATOMS atoms, charge=$CHARGE)"
echo

if $PREP_ONLY; then
  echo ">>> --prep-only specified. Stopping here."
  echo "    XYZ:    $MOL_DIR/$MOLECULE.xyz"
  echo "    Charge: $MOL_DIR/charge.txt (charge=$CHARGE)"
  echo
  echo "    To continue on the HPC login node:"
  echo "    scripts/prep_cosmo.sh $MOLECULE $PROTOCOL"
  echo "    scripts/submit_cosmo.sh $MOLECULE $PROTOCOL"
  exit 0
fi

# --- Step 2: TURBOMOLE prep (x2t + define + cosmoprep) ------------------------
echo ">>> STEP 2: TURBOMOLE prep (x2t + define + cosmoprep)"
echo "---"

"$SCRIPT_DIR/prep_cosmo.sh" "$MOLECULE" "$PROTOCOL"

echo

if $NO_SUBMIT; then
  echo ">>> --no-submit specified. Stopping here."
  echo "    Prepared in: $MOL_DIR"
  echo
  echo "    To submit manually:"
  echo "    scripts/submit_cosmo.sh $MOLECULE $PROTOCOL"
  exit 0
fi

# --- Step 3: Submit SLURM job -------------------------------------------------
echo ">>> STEP 3: Submitting SLURM job"
echo "---"

"$SCRIPT_DIR/submit_cosmo.sh" "$MOLECULE" "$PROTOCOL"

echo
echo "================================================================"
echo "  Pipeline complete for $MOLECULE"
echo "  After job finishes: scripts/verify_cosmo.sh $MOLECULE"
echo "================================================================"
